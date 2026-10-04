import { describe, it, expect, vi } from 'vitest'
import { syncVmOpenPorts } from '../vmOpenPorts'
import type { OpenPortDraftRow } from '../types'

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
