import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../auth'

const adminUser = {
  id: 'u1',
  username: 'admin',
  role: 'admin' as const,
  is_active: true,
  last_login_at: null,
  locked: false,
  created_at: '2026-01-01T00:00:00',
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

  it('login(): при 429 TOO_MANY_ATTEMPTS сохраняет код и Retry-After; следующая удачная попытка их сбрасывает (B-12)', async () => {
    let attempt = 0
    stubFetch({
      '/auth/login': () =>
        ++attempt === 1
          ? new Response(JSON.stringify({ detail: { code: 'TOO_MANY_ATTEMPTS', message: 'Слишком много неудачных попыток входа.' } }), {
              status: 429,
              headers: { 'Retry-After': '9' },
            })
          : new Response(JSON.stringify({ token: 'tok-1', user: adminUser })),
    })
    const auth = useAuthStore()

    expect(await auth.login('admin', 'x')).toBe(false)
    expect(auth.errorCode).toBe('TOO_MANY_ATTEMPTS')
    expect(auth.errorRetryAfter).toBe(9)

    expect(await auth.login('admin', 'Admin1234')).toBe(true)
    expect(auth.errorCode).toBeNull()
    expect(auth.errorRetryAfter).toBeNull()
    expect(auth.error).toBeNull()
  })

  it('login(): обычная ошибка (401) оставляет errorCode и errorRetryAfter пустыми (B-12)', async () => {
    stubFetch({ '/auth/login': () => new Response(JSON.stringify({ detail: 'Неверное имя пользователя или пароль.' }), { status: 401 }) })
    const auth = useAuthStore()

    await auth.login('admin', 'wrong')

    expect(auth.errorCode).toBeNull()
    expect(auth.errorRetryAfter).toBeNull()
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

  // Фикс auth п.1.1 (батч4): включение аутентификации должно немедленно потребовать вход,
  // а не только на следующей проваленной попытке запроса — см. комментарий в stores/auth.ts.
  it('setEnabled(true): сбрасывает токен и пользователя сразу, needsLogin становится true синхронно с ответом', async () => {
    localStorage.setItem('itr:auth-token', 'tok-123')
    stubFetch({ '/auth/settings': () => new Response(JSON.stringify({ enabled: true, session_ttl_hours: 12 })) })
    const auth = useAuthStore()
    auth.enabled = false
    auth.user = adminUser // теоретически мог остаться от предыдущего включения — тоже должен сброситься

    await auth.setEnabled(true)

    expect(auth.enabled).toBe(true)
    expect(auth.user).toBeNull()
    expect(auth.needsLogin).toBe(true)
    expect(localStorage.getItem('itr:auth-token')).toBeNull()
  })

  it('setEnabled(false): не трогает уже вошедшего пользователя (выключение — не выход)', async () => {
    localStorage.setItem('itr:auth-token', 'tok-123')
    stubFetch({ '/auth/settings': () => new Response(JSON.stringify({ enabled: false, session_ttl_hours: 12 })) })
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = adminUser

    await auth.setEnabled(false)

    expect(auth.enabled).toBe(false)
    expect(auth.user).toEqual(adminUser)
    expect(localStorage.getItem('itr:auth-token')).toBe('tok-123')
  })

  it('isAdmin отражает роль текущего пользователя', () => {
    const auth = useAuthStore()
    expect(auth.isAdmin).toBe(false)
    auth.user = adminUser
    expect(auth.isAdmin).toBe(true)
    auth.user = { ...adminUser, role: 'viewer' }
    expect(auth.isAdmin).toBe(false)
  })

  it('fetchMySessions(): заполняет sessions из ответа сервера', async () => {
    stubFetch({
      '/auth/sessions': () =>
        new Response(
          JSON.stringify([
            { id: 's1', created_at: '2026-01-01T00:00:00', expires_at: '2026-01-01T12:00:00', user_agent: null, ip_address: '127.0.0.1', current: true },
          ]),
        ),
    })
    const auth = useAuthStore()

    await auth.fetchMySessions()

    expect(auth.sessions).toHaveLength(1)
    expect(auth.sessions[0].current).toBe(true)
    expect(auth.sessionsLoading).toBe(false)
  })

  it('revokeSession(): убирает сессию из локального списка после успешного DELETE', async () => {
    stubFetch({ '/auth/sessions/s2': () => new Response(null, { status: 204 }) })
    const auth = useAuthStore()
    auth.sessions = [
      { id: 's1', created_at: '', expires_at: '', user_agent: null, ip_address: null, current: true },
      { id: 's2', created_at: '', expires_at: '', user_agent: null, ip_address: null, current: false },
    ]

    await auth.revokeSession('s2')

    expect(auth.sessions.map((s) => s.id)).toEqual(['s1'])
  })

  it('changeOwnPassword(): обновляет user из ответа сервера', async () => {
    const updated = { ...adminUser, username: 'admin' }
    stubFetch({ '/auth/me/password': () => new Response(JSON.stringify(updated)) })
    const auth = useAuthStore()

    const result = await auth.changeOwnPassword('OldPass1234', 'NewPass1234')

    expect(result).toEqual(updated)
    expect(auth.user).toEqual(updated)
  })

  it('changeOwnPassword(): пробрасывает ApiError при неверном текущем пароле', async () => {
    stubFetch({ '/auth/me/password': () => new Response(JSON.stringify({ detail: 'Текущий пароль указан неверно.' }), { status: 401 }) })
    const auth = useAuthStore()

    await expect(auth.changeOwnPassword('wrong', 'NewPass1234')).rejects.toMatchObject({ status: 401 })
  })
})

// Список учётных записей и список сессий — тот же класс гонок, что у остальных сторов (utils/latestRequest.ts): загрузка, начатая ДО
// подтверждённого изменения, отвечает позже и приносит снимок без него.
describe('useAuthStore: загрузка списков и подтверждённые изменения', () => {
  const bob = { ...adminUser, id: 'u2', username: 'bob', role: 'viewer' as const }
  const session = (id: string) => ({
    id,
    created_at: '2026-01-01T00:00:00',
    expires_at: '2026-01-02T00:00:00',
    user_agent: null,
    ip_address: null,
    current: false,
  })

  type Call = { url: string; method: string; respond: (status: number, body?: unknown) => void }

  /** fetch, ответами на который управляет тест: запрос ждёт, пока его не вызовут respond. */
  function manualFetch() {
    const calls: Call[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (url: string, init?: RequestInit) =>
          new Promise<Response>((resolve) => {
            const respond = (status: number, body?: unknown) => resolve(new Response(body === undefined ? null : JSON.stringify(body), { status }))
            calls.push({ url, method: init?.method ?? 'GET', respond })
          }),
      ),
    )
    /** Ждёт, пока стор отправит `numberth` запрос с этим методом и адресом (до отправки он проходит через несколько await). */
    async function request(method: string, urlPart: string, index = 0): Promise<Call> {
      for (let attempt = 0; attempt < 20; attempt++) {
        const found = calls.filter((c) => c.method === method && c.url.includes(urlPart))[index]
        if (found) return found
        await new Promise((resolve) => setTimeout(resolve, 0))
      }
      throw new Error(`Запрос ${method} ${urlPart} №${index + 1} не был отправлен`)
    }
    return { request }
  }

  it('fetchUsers(): ответ более раннего запроса не затирает ответ более позднего', async () => {
    const http = manualFetch()
    const auth = useAuthStore()

    const first = auth.fetchUsers()
    const second = auth.fetchUsers()
    ;(await http.request('GET', '/auth/users', 1)).respond(200, [adminUser, bob])
    await second
    ;(await http.request('GET', '/auth/users', 0)).respond(200, [adminUser])
    await first

    expect(auth.users.map((u) => u.id)).toEqual(['u1', 'u2'])
    expect(auth.usersLoading).toBe(false)
  })

  it('createUser(): загрузка списка, начатая до создания, не стирает новую учётку; список перечитывается', async () => {
    const http = manualFetch()
    const auth = useAuthStore()

    const load = auth.fetchUsers()
    const create = auth.createUser('bob', 'Password1234', 'viewer')
    ;(await http.request('POST', '/auth/users')).respond(201, bob)
    await create
    ;(await http.request('GET', '/auth/users', 0)).respond(200, [adminUser]) // запоздалый снимок без bob
    await load
    expect(auth.users.map((u) => u.id)).toEqual(['u2'])
    expect(auth.usersLoading).toBe(true) // шла повторная загрузка — флаг не сбросил ответ отброшенной

    ;(await http.request('GET', '/auth/users', 1)).respond(200, [adminUser, bob])
    await vi.waitFor(() => expect(auth.usersLoading).toBe(false))
    expect(auth.users.map((u) => u.id)).toEqual(['u1', 'u2'])
  })

  it('deleteUser(): загрузка списка, начатая до удаления, не возвращает удалённую учётку', async () => {
    const http = manualFetch()
    const auth = useAuthStore()
    auth.users = [adminUser, bob]

    const load = auth.fetchUsers()
    const removal = auth.deleteUser('u2')
    ;(await http.request('DELETE', '/auth/users/u2')).respond(204)
    await removal
    ;(await http.request('GET', '/auth/users', 0)).respond(200, [adminUser, bob]) // запоздалый снимок с удалённым
    await load
    expect(auth.users.map((u) => u.id)).toEqual(['u1'])

    ;(await http.request('GET', '/auth/users', 1)).respond(200, [adminUser])
    await vi.waitFor(() => expect(auth.usersLoading).toBe(false))
    expect(auth.users.map((u) => u.id)).toEqual(['u1'])
  })

  it('updateUser(): загрузка списка, начатая до правки, не откатывает изменённую учётку', async () => {
    const http = manualFetch()
    const auth = useAuthStore()
    auth.users = [adminUser, bob]

    const load = auth.fetchUsers()
    const update = auth.updateUser('u2', { role: 'admin' })
    ;(await http.request('PUT', '/auth/users/u2')).respond(200, { ...bob, role: 'admin' })
    await update
    ;(await http.request('GET', '/auth/users', 0)).respond(200, [adminUser, bob]) // запоздалый снимок с прежней ролью
    await load

    expect(auth.users.find((u) => u.id === 'u2')?.role).toBe('admin')
    ;(await http.request('GET', '/auth/users', 1)).respond(200, [adminUser, { ...bob, role: 'admin' }])
    await vi.waitFor(() => expect(auth.usersLoading).toBe(false))
  })

  it('revokeSession(): загрузка списка сессий, начатая до отзыва, не возвращает отозванную сессию', async () => {
    const http = manualFetch()
    const auth = useAuthStore()
    auth.sessions = [session('s1'), session('s2')]

    const load = auth.fetchMySessions()
    const revoke = auth.revokeSession('s2')
    ;(await http.request('DELETE', '/auth/sessions/s2')).respond(204)
    await revoke
    ;(await http.request('GET', '/auth/sessions', 0)).respond(200, [session('s1'), session('s2')])
    await load
    expect(auth.sessions.map((s) => s.id)).toEqual(['s1'])
    expect(auth.sessionsLoading).toBe(true)

    ;(await http.request('GET', '/auth/sessions', 1)).respond(200, [session('s1')])
    await vi.waitFor(() => expect(auth.sessionsLoading).toBe(false))
    expect(auth.sessions.map((s) => s.id)).toEqual(['s1'])
  })

  it('мутация без загрузки в полёте не запускает повторную загрузку списка', async () => {
    const http = manualFetch()
    const auth = useAuthStore()
    auth.users = [adminUser, bob]

    const removal = auth.deleteUser('u2')
    ;(await http.request('DELETE', '/auth/users/u2')).respond(204)
    await removal

    expect(auth.users.map((u) => u.id)).toEqual(['u1'])
    expect(vi.mocked(fetch).mock.calls.filter(([, init]) => (init?.method ?? 'GET') === 'GET')).toHaveLength(0)
  })
})
