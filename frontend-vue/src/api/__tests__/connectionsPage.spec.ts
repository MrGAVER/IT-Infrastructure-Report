import { describe, it, expect, vi } from 'vitest'
import { fetchConnectionsPage } from '../connectionsPage'

function stubFetch() {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 8, summary: {} })))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('fetchConnectionsPage', () => {
  it('без условий передаёт только offset и limit', async () => {
    const fetchMock = stubFetch()
    await fetchConnectionsPage({ offset: 16, limit: 8 })
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/connections\?offset=16&limit=8$/)
  })

  it('кодирует кириллицу и передаёт все условия; is_active=false не теряется', async () => {
    const fetchMock = stubFetch()
    await fetchConnectionsPage({ q: 'Коммутатор 100%', is_active: false, port_config_status: 'mismatch', offset: 0, limit: 8 })
    const url = new URL(fetchMock.mock.calls[0][0], 'http://x')
    expect(url.searchParams.get('q')).toBe('Коммутатор 100%')
    expect(url.searchParams.get('is_active')).toBe('false')
    expect(url.searchParams.get('port_config_status')).toBe('mismatch')
  })

  it('пустая строка поиска не передаётся', async () => {
    const fetchMock = stubFetch()
    await fetchConnectionsPage({ q: '', offset: 0, limit: 8 })
    expect(fetchMock.mock.calls[0][0]).not.toContain('q=')
  })
})
