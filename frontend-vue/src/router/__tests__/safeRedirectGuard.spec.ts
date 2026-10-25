// B-10: гард роутера уводит уже вошедшего пользователя с /login на адрес из ?redirect= — но только безопасный.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { router } from '../index'
import { setStoredToken } from '../../api/client'
import { stubPreferencesApi } from '../../stores/__tests__/preferencesApi'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

function stubSignedInAdmin() {
  stubPreferencesApi({})
  const preferencesFetch = globalThis.fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/status')) return json({ enabled: true, session_ttl_hours: 12 })
      if (url.endsWith('/auth/me')) return json({ enabled: true, user: { id: 'u1', username: 'admin', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' } })
      return preferencesFetch(url, init)
    }),
  )
  setStoredToken('token-1')
}

beforeEach(async () => {
  vi.unstubAllGlobals()
  setActivePinia(createPinia())
  localStorage.clear()
  setStoredToken(null)
  await router.replace('/report-templates').catch(() => undefined)
  // Возврат на нейтральный маршрут идёт через гард с настоящим (не подменённым) fetch и мог бы инициализировать стор
  // аутентификации «выключенной аутентификацией» — тесту нужен чистый стор, иначе результат зависит от порядка тестов.
  setActivePinia(createPinia())
})

describe('router.beforeEach — адрес возврата для вошедшего пользователя', () => {
  it('безопасный ?redirect= уважается', async () => {
    stubSignedInAdmin()

    await router.push('/login?redirect=/report-templates?x=1')

    expect(router.currentRoute.value.fullPath).toBe('/report-templates?x=1')
  })

  it.each(['//evil.example', 'https://evil.example', '/login', '/%2e%2e/etc'])('небезопасный ?redirect=%s заменяется на /dashboard', async (redirect) => {
    stubSignedInAdmin()

    await router.push({ name: 'login', query: { redirect } })

    expect(router.currentRoute.value.fullPath).toBe('/dashboard')
  })

  it('без ?redirect= вошедшего с /login уводит на /dashboard', async () => {
    stubSignedInAdmin()

    await router.push('/login')

    expect(router.currentRoute.value.fullPath).toBe('/dashboard')
  })
})
