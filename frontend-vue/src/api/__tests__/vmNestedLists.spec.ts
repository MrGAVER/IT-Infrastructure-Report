import { describe, it, expect, vi } from 'vitest'
import { syncVmDeployedSoftware, syncVmIpAddresses, syncVmOpenPorts } from '../vmNestedLists'
import type { OpenPortDraftRow, SoftwareAssetDraftRow, VmIpDraftRow } from '../types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function stubFetch(responseBody: unknown = { items: [] }, status = 200) {
  const fetchMock = vi.fn(async () => jsonResponse(responseBody, status))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const sentBody = (fetchMock: ReturnType<typeof stubFetch>) => JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)

describe('syncVmOpenPorts', () => {
  it('отправляет один PUT со всем списком портов, сохраняя id существующих строк', async () => {
    const fetchMock = stubFetch({ items: [{ id: 'op-1' }, { id: 'op-new' }] })
    const rows: OpenPortDraftRow[] = [
      { id: 'op-1', protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: 'админ' },
      { protocol_catalog_id: 'cat-https', transport_protocol: 'UDP', description: '' },
    ]

    const saved = await syncVmOpenPorts('vm-1', rows)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/vms/vm-1/open-ports')
    expect(init.method).toBe('PUT')
    expect(sentBody(fetchMock)).toEqual({
      open_ports: [
        { id: 'op-1', protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: 'админ' },
        { protocol_catalog_id: 'cat-https', transport_protocol: 'UDP', description: null },
      ],
    })
    expect(saved).toEqual([{ id: 'op-1' }, { id: 'op-new' }])
  })

  it('не отправляет строки без выбранной записи справочника и подставляет TCP по умолчанию', async () => {
    const fetchMock = stubFetch()
    const rows: OpenPortDraftRow[] = [
      { protocol_catalog_id: '', transport_protocol: 'TCP', description: '' },
      { protocol_catalog_id: 'cat-ssh', transport_protocol: '', description: '' },
    ]

    await syncVmOpenPorts('vm-1', rows)

    expect(sentBody(fetchMock).open_ports).toEqual([{ protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: null }])
  })

  it('пустой список отправляется как пустой массив — сервер удалит порты ВМ', async () => {
    const fetchMock = stubFetch()

    await syncVmOpenPorts('vm-1', [])

    expect(sentBody(fetchMock)).toEqual({ open_ports: [] })
  })

  it('ошибка сервера пробрасывается вызывающему, а не проглатывается', async () => {
    stubFetch({ detail: 'ВМ «app»: номера открытых портов не должны повторяться — 80' }, 422)

    await expect(syncVmOpenPorts('vm-1', [{ protocol_catalog_id: 'cat-http', transport_protocol: 'TCP', description: '' }])).rejects.toThrow()
  })
})

describe('syncVmIpAddresses', () => {
  it('отправляет один PUT со всем списком адресов, сохраняя id существующих строк', async () => {
    const fetchMock = stubFetch({ items: [{ id: 'ip-1' }, { id: 'ip-new' }] })
    const rows: VmIpDraftRow[] = [
      { id: 'ip-1', ip_address: ' 10.0.0.5 ', prefix_length: '24', purpose: 'LAN', is_management: true },
      { ip_address: '10.0.0.6', prefix_length: '', purpose: '', is_management: false },
    ]

    const saved = await syncVmIpAddresses('vm-1', rows)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/vms/vm-1/ip-addresses')
    expect(init.method).toBe('PUT')
    expect(sentBody(fetchMock)).toEqual({
      ip_addresses: [
        { id: 'ip-1', ip_address: '10.0.0.5', prefix_length: 24, purpose: 'LAN', is_management: true },
        { ip_address: '10.0.0.6', prefix_length: null, purpose: null, is_management: false },
      ],
    })
    expect(saved).toEqual([{ id: 'ip-1' }, { id: 'ip-new' }])
  })

  it('не отправляет строки с пустым адресом; пустой список — пустой массив', async () => {
    const fetchMock = stubFetch()

    await syncVmIpAddresses('vm-1', [{ ip_address: '   ', prefix_length: '24', purpose: '', is_management: false }])
    expect(sentBody(fetchMock)).toEqual({ ip_addresses: [] })
  })

  it('ошибка сервера пробрасывается вызывающему', async () => {
    stubFetch({ detail: 'IP-адрес: некорректный адрес' }, 422)

    await expect(syncVmIpAddresses('vm-1', [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '', is_management: false }])).rejects.toThrow()
  })
})

describe('syncVmDeployedSoftware', () => {
  it('отправляет один PUT со всем списком ПО, сохраняя id существующих строк', async () => {
    const fetchMock = stubFetch({ items: [{ id: 'sw-1' }, { id: 'sw-new' }] })
    const rows: SoftwareAssetDraftRow[] = [
      { id: 'sw-1', software_asset_id: 'asset-nginx', version: '1.25' },
      { software_asset_id: 'asset-1c', version: '' },
    ]

    const saved = await syncVmDeployedSoftware('vm-1', rows)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/vms/vm-1/deployed-software')
    expect(init.method).toBe('PUT')
    expect(sentBody(fetchMock)).toEqual({
      deployed_software: [
        { id: 'sw-1', software_asset_id: 'asset-nginx', version: '1.25' },
        { software_asset_id: 'asset-1c', version: null },
      ],
    })
    expect(saved).toEqual([{ id: 'sw-1' }, { id: 'sw-new' }])
  })

  it('не отправляет строки без выбранного актива; пустой список — пустой массив', async () => {
    const fetchMock = stubFetch()

    await syncVmDeployedSoftware('vm-1', [{ software_asset_id: '', version: '8.3' }])
    expect(sentBody(fetchMock)).toEqual({ deployed_software: [] })
  })

  it('ошибка сервера пробрасывается вызывающему', async () => {
    stubFetch({ detail: 'Программный актив не найден в справочнике' }, 422)

    await expect(syncVmDeployedSoftware('vm-1', [{ software_asset_id: 'нет', version: '' }])).rejects.toThrow()
  })
})
