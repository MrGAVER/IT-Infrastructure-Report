import { describe, it, expect, vi, afterEach } from 'vitest'
import { DEVICE_OPTIONS_PAGE_SIZE, FREE_INTERFACES_PAGE_SIZE, fetchAllFreeInterfaces, fetchDeviceInterfaceConnections, fetchDeviceOptionsPage, fetchFreeInterfacesPage } from '../deviceConnectivity'
import type { FreeInterface } from '../deviceConnectivity'

const port = (n: number): FreeInterface => ({ id: `p-${n}`, name: `Gi0/${n}`, is_management: false, is_data_transfer: true, vlan_mode: 'access', all_vlans: false, occupied: false })

/** Фейковый сервер: отдаёт срез из `ports` по offset/limit из запроса, как backend. */
function stubServer(ports: FreeInterface[]) {
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
    const params = new URLSearchParams(url.split('?')[1])
    const offset = Number(params.get('offset'))
    const limit = Number(params.get('limit'))
    return new Response(JSON.stringify({ items: ports.slice(offset, offset + limit), total: ports.length, offset, limit }))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
const queryOf = (call: unknown[]) => new URLSearchParams((call[0] as string).split('?')[1])

afterEach(() => vi.unstubAllGlobals())

describe('fetchFreeInterfacesPage', () => {
  it('строит запрос: id устройства экранируется, offset/limit по умолчанию, include повторяется, q обрезается', async () => {
    const fetchMock = stubServer([])

    await fetchFreeInterfacesPage('dev/1', { q: '  Gi0  ', include: ['a', 'b'], offset: 10, limit: 5 })

    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toContain('/devices/dev%2F1/free-interfaces?')
    const params = queryOf(fetchMock.mock.calls[0])
    expect(params.get('q')).toBe('Gi0')
    expect(params.getAll('include')).toEqual(['a', 'b'])
    expect(params.get('offset')).toBe('10')
    expect(params.get('limit')).toBe('5')
  })

  it('без параметров: первая страница стандартного размера, без q и include', async () => {
    const fetchMock = stubServer([])

    await fetchFreeInterfacesPage('dev-1', { q: '   ' })

    const params = queryOf(fetchMock.mock.calls[0])
    expect(params.has('q')).toBe(false)
    expect(params.has('include')).toBe(false)
    expect(params.get('offset')).toBe('0')
    expect(params.get('limit')).toBe(String(FREE_INTERFACES_PAGE_SIZE))
  })
})

describe('fetchAllFreeInterfaces', () => {
  it('собирает все страницы по порядку и останавливается, когда набрано total', async () => {
    const ports = Array.from({ length: FREE_INTERFACES_PAGE_SIZE * 2 + 50 }, (_, i) => port(i))
    const fetchMock = stubServer(ports)

    const all = await fetchAllFreeInterfaces('dev-1', ['p-1'])

    expect(all).toEqual(ports)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls.map((c) => queryOf(c).get('offset'))).toEqual(['0', String(FREE_INTERFACES_PAGE_SIZE), String(FREE_INTERFACES_PAGE_SIZE * 2)])
    expect(fetchMock.mock.calls.every((c) => queryOf(c).getAll('include').join() === 'p-1')).toBe(true)
  })

  it('у устройства без свободных портов — один запрос и пустой список', async () => {
    const fetchMock = stubServer([])

    expect(await fetchAllFreeInterfaces('dev-1')).toEqual([])
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('не зацикливается, если сервер вернул пустую страницу раньше, чем набралось total (набор изменился между запросами)', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const offset = Number(new URLSearchParams(url.split('?')[1]).get('offset'))
      const items = offset === 0 ? [port(0), port(1)] : []
      return new Response(JSON.stringify({ items, total: 10, offset, limit: FREE_INTERFACES_PAGE_SIZE }))
    })
    vi.stubGlobal('fetch', fetchMock)

    const all = await fetchAllFreeInterfaces('dev-1')

    expect(all).toHaveLength(2)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('ошибка сервера прокидывается вызывающему (редактор покажет её, а не пустой список)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Устройство не найдено' }), { status: 404 })))

    await expect(fetchAllFreeInterfaces('dev-x')).rejects.toThrow('Устройство не найдено')
  })
})

describe('fetchDeviceInterfaceConnections', () => {
  it('запрашивает подключения устройства и возвращает список items', async () => {
    const item = { interface_id: 'if-1', connection_id: 'c-1', connection_type_id: 'ct-1', description: null, peer_interface_id: 'b-1', peer_interface_name: 'Gi0/1', peer_device_id: 'dev-b', peer_device_name: 'sw-b', peer_is_management: false, peer_is_data_transfer: true, peer_vlan_mode: 'access' }
    const fetchMock = vi.fn(async (_url: string) => new Response(JSON.stringify({ items: [item] })))
    vi.stubGlobal('fetch', fetchMock)

    expect(await fetchDeviceInterfaceConnections('dev-1')).toEqual([item])
    expect(fetchMock.mock.calls[0][0]).toContain('/devices/dev-1/interface-connections')
  })
})

describe('fetchDeviceOptionsPage', () => {
  it('строит запрос: q обрезается, include и exclude повторяются, страница по умолчанию — 50 записей', async () => {
    const fetchMock = vi.fn(async (_url: string) => new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 50 })))
    vi.stubGlobal('fetch', fetchMock)

    await fetchDeviceOptionsPage({ q: '  sw  ', include: ['a', 'b'], exclude: ['me'], offset: 100 })

    const url = fetchMock.mock.calls[0][0]
    expect(url).toContain('/devices/options?')
    const params = new URLSearchParams(url.split('?')[1])
    expect(params.get('q')).toBe('sw')
    expect(params.getAll('include')).toEqual(['a', 'b'])
    expect(params.getAll('exclude')).toEqual(['me'])
    expect(params.get('offset')).toBe('100')
    expect(params.get('limit')).toBe(String(DEVICE_OPTIONS_PAGE_SIZE))
  })

  it('без параметров: первая страница, без q, include и exclude', async () => {
    const fetchMock = vi.fn(async (_url: string) => new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 50 })))
    vi.stubGlobal('fetch', fetchMock)

    await fetchDeviceOptionsPage({ q: '   ' })

    const params = new URLSearchParams(fetchMock.mock.calls[0][0].split('?')[1])
    expect([params.has('q'), params.has('include'), params.has('exclude')]).toEqual([false, false, false])
    expect(params.get('offset')).toBe('0')
  })

  it('возвращает страницу как есть; ошибка сервера прокидывается вызывающему', async () => {
    const page = { items: [{ id: 'd-1', label: 'sw-1', system_name: 'sw-1', serial_number: 'S1' }], total: 7, offset: 0, limit: 50 }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(page))))
    expect(await fetchDeviceOptionsPage()).toEqual(page)

    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'База недоступна' }), { status: 500 })))
    await expect(fetchDeviceOptionsPage()).rejects.toThrow('База недоступна')
  })
})
