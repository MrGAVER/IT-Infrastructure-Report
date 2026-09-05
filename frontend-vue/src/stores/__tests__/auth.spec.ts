import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../auth'

const adminUser = {
  id: 'u1', username: 'admin', role: 'admin' as const, is_active: true,
  last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00',
}

function stubFetch(handlers: Record<string, (url: string, init?: RequestInit) => Response | Promise<Response>>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      for (const [pattern, handler] of Object.entries(handlers)) {
        if (url.includes(pattern)) return handler(url, init)
      }
      throw new Error(`Незамоканный запрос: ${url}`)
    }),
  )
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

describe('useAuthStore', () => {
  it('init(): при выключенной аутентификации считает пользователя допущенным без входа', async () => {
    stubFetch({ '/auth/status': () => new Response(JSON.stringify({ enabled: false, session_ttl_hours: 12 })) })
    const auth = useAuthStore()

    await auth.init()

    expect(auth.enabled).toBe(false)
    expect(auth.needsLogin).toBe(false)
    expect(auth.isAuthenticated).toBe(true)
  })

  it('init(): при включённой аутентификации и отсутствии токена требует входа', async () => {
    stubFetch({ '/auth/status': () => new Response(JSON.stringify({ enabled: true, session_ttl_hours: 12 })) })
    const auth = useAuthStore()

    await auth.init()

    expect(auth.needsLogin).toBe(true)
    expect(auth.isAuthenticated).toBe(false)
  })

  it('init(): включена + есть сохранённый токен -> подтягивает пользователя через /auth/me', async () => {
    localStorage.setItem('itr:auth-token', 'stored-token')
    stubFetch({
      '/auth/status': () => new Response(JSON.stringify({ enabled: true, session_ttl_hours: 12 })),
      '/auth/me': () => new Response(JSON.stringify({ enabled: true, user: adminUser })),
    })
    const auth = useAuthStore()

    await auth.init()

    expect(auth.needsLogin).toBe(false)
    expect(auth.user?.username).toBe('admin')
  })

  it('init() не выполняет запрос повторно при повторном вызове', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ enabled: false, session_ttl_hours: 12 })))
    vi.stubGlobal('fetch', fetchMock)
    const auth = useAuthStore()

    await auth.init()
    await auth.init()

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('login(): при успехе сохраняет токен и пользователя', async () => {
    stubFetch({
      '/auth/login': () => new Response(JSON.stringify({ token: 'tok-123', user: adminUser })),
    })
    const auth = useAuthStore()

    const ok = await auth.login('admin', 'Admin1234')

    expect(ok).toBe(true)
    expect(auth.user?.username).toBe('admin')
    expect(localStorage.getItem('itr:auth-token')).toBe('tok-123')
    expect(auth.enabled).toBe(true)
  })

  it('login(): при неверном пароле возвращает false и заполняет error, не трогая localStorage', async () => {
    stubFetch({
      '/auth/login': () => new Response(JSON.stringify({ detail: 'Неверное имя пользователя или пароль.' }), { status: 401 }),
    })
    const auth = useAuthStore()

    const ok = await auth.login('admin', 'wrong')

    expect(ok).toBe(false)
    expect(auth.error).toContain('Неверное имя пользователя или пароль')
    expect(auth.user).toBeNull()
    expect(localStorage.getItem('itr:auth-token')).toBeNull()
  })

  it('logout(): очищает пользователя и токен даже если запрос к серверу не удался', async () => {
    localStorage.setItem('itr:auth-token', 'tok-123')
    stubFetch({ '/auth/logout': () => new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }) })
    const auth = useAuthStore()
    auth.user = adminUser

    await auth.logout()

    expect(auth.user).toBeNull()
    expect(localStorage.getItem('itr:auth-token')).toBeNull()
  })

  it('handleUnauthorized(): сбрасывает локальную сессию (реакция на событие 401 из api/client.ts)', () => {
    localStorage.setItem('itr:auth-token', 'tok-123')
    const auth = useAuthStore()
    auth.user = adminUser

    auth.handleUnauthorized()

    expect(auth.user).toBeNull()
    expect(localStorage.getItem('itr:auth-token')).toBeNull()
  })

  it('isAdmin отражает роль текущего пользователя', () => {
    const auth = useAuthStore()
    expect(auth.isAdmin).toBe(false)
    auth.user = adminUser
    expect(auth.isAdmin).toBe(true)
    auth.user = { ...adminUser, role: 'viewer' }
    expect(auth.isAdmin).toBe(false)
  })
})
