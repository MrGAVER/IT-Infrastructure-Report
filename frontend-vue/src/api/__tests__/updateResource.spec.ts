import { afterEach, describe, expect, it, vi } from 'vitest'
import { updateResource } from '../client'

type FetchInit = { method?: string; body?: string }

function stubFetch() {
  const fetchMock = vi.fn(
    async (_url: string, _init?: FetchInit) => new Response(JSON.stringify({ id: 'vm-1', updated_at: '2026-11-01T10:05:00Z' }), { status: 200 }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
const sentBody = (fetchMock: ReturnType<typeof stubFetch>) => JSON.parse(fetchMock.mock.calls[0][1]?.body ?? 'null')

afterEach(() => vi.unstubAllGlobals())

describe('api/client: updateResource и оптимистичная блокировка', () => {
  it('PUT /resources/{ресурс}/{id}; с токеном версии тело дополняется expected_updated_at', async () => {
    const fetchMock = stubFetch()
    const saved = await updateResource<{ id: string }>('vms', 'vm-1', { name: 'vm' }, '2026-11-01T10:00:00Z')

    expect(fetchMock.mock.calls[0][0]).toContain('/resources/vms/vm-1')
    expect(fetchMock.mock.calls[0][1]?.method).toBe('PUT')
    expect(sentBody(fetchMock)).toEqual({ name: 'vm', expected_updated_at: '2026-11-01T10:00:00Z' })
    expect(saved.id).toBe('vm-1')
  })

  it.each([undefined, null, ''])('без токена (%j) тело не меняется: запись обновляется без проверки версии', async (token) => {
    const fetchMock = stubFetch()
    await updateResource('vms', 'vm-1', { name: 'vm' }, token)
    expect(sentBody(fetchMock)).toEqual({ name: 'vm' })
  })

  it('переданный объект payload не изменяется', async () => {
    stubFetch()
    const payload = { name: 'vm' }
    await updateResource('vms', 'vm-1', payload, '2026-11-01T10:00:00Z')
    expect(payload).toEqual({ name: 'vm' })
  })
})
