import { describe, it, expect, vi } from 'vitest'
import { approveMatchingPortConfig, approvePortConfig, revokePortConfigApproval, setPortRole } from '../portConfig'

function stubFetch(body: unknown = {}) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify(body), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('api/portConfig', () => {
  it('setPortRole: PUT /interfaces/{id}/port-role с флагами роли', async () => {
    const fetchMock = stubFetch()
    await setPortRole('if-1', 'management_data')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/interfaces/if-1/port-role')
    expect(init?.method).toBe('PUT')
    expect(JSON.parse(init!.body as string)).toEqual({ is_management: true, is_data_transfer: true })
  })

  it('setPortRole("none") снимает оба флага', async () => {
    const fetchMock = stubFetch()
    await setPortRole('if-1', 'none')
    expect(JSON.parse(fetchMock.mock.calls[0][1]!.body as string)).toEqual({ is_management: false, is_data_transfer: false })
  })

  it('approvePortConfig: POST /connections/port-config/approve со списком id', async () => {
    const fetchMock = stubFetch({ items: [], skipped_ids: [] })
    await approvePortConfig(['c-1', 'c-2'])
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/connections/port-config/approve')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init!.body as string)).toEqual({ connection_ids: ['c-1', 'c-2'] })
  })

  it('revokePortConfigApproval: DELETE /connections/{id}/port-config/approval', async () => {
    const fetchMock = stubFetch()
    await revokePortConfigApproval('c-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/connections/c-1/port-config/approval')
    expect(init?.method).toBe('DELETE')
  })

  it('approveMatchingPortConfig: POST с условиями match, без connection_ids', async () => {
    const fetchMock = stubFetch({ items: [], skipped_ids: [], approved_count: 12 })
    const result = await approveMatchingPortConfig({ q: 'ядро', is_active: true })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/connections/port-config/approve')
    expect(JSON.parse(init!.body as string)).toEqual({ match: { q: 'ядро', is_active: true } })
    expect(result.approved_count).toBe(12)
  })
})
