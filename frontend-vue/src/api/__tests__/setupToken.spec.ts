import { describe, it, expect, beforeEach, vi } from 'vitest'
import { api, getStoredSetupToken, setStoredSetupToken } from '../client'

function stubFetch() {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({})))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function sentHeaders(fetchMock: ReturnType<typeof stubFetch>): Record<string, string> {
  return (fetchMock.mock.calls[0][1]?.headers ?? {}) as Record<string, string>
}

describe('токен первичной настройки (X-Setup-Token)', () => {
  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
  })

  it('уходит только на /auth/*', async () => {
    setStoredSetupToken('s3cret')
    const fetchMock = stubFetch()
    await api.get('/auth/users')
    expect(sentHeaders(fetchMock)['X-Setup-Token']).toBe('s3cret')

    const other = stubFetch()
    await api.get('/resources/devices')
    expect(sentHeaders(other)['X-Setup-Token']).toBeUndefined()
  })

  it('без сохранённого токена заголовка нет', async () => {
    const fetchMock = stubFetch()
    await api.get('/auth/users')
    expect(sentHeaders(fetchMock)['X-Setup-Token']).toBeUndefined()
  })

  it('хранится в sessionStorage и сбрасывается пустым значением', () => {
    setStoredSetupToken('abc')
    expect(sessionStorage.getItem('itr:setup-token')).toBe('abc')
    expect(localStorage.getItem('itr:setup-token')).toBeNull()
    expect(getStoredSetupToken()).toBe('abc')
    setStoredSetupToken(null)
    expect(getStoredSetupToken()).toBeNull()
  })
})
