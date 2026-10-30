// A-23: журнал аудита — только администратору (сервер отвечает viewer'у 403), поэтому роль «только чтение» в раздел не пускаем:
// её возвращают на дашборд, а не показывают экран с ошибкой.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { router, routes } from '../index'
import { setStoredToken } from '../../api/client'
import { stubPreferencesApi } from '../../stores/__tests__/preferencesApi'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

type Role = 'viewer' | 'admin' | 'auth-off'

function stubServer(role: Role) {
  stubPreferencesApi({})
  const preferencesFetch = globalThis.fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>
  const enabled = role !== 'auth-off'
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/status')) return json({ enabled, session_ttl_hours: 12 })
      if (url.endsWith('/auth/me'))
        return json({
          enabled,
          user: enabled ? { id: 'u1', username: role, role, is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' } : null,
        })
      return preferencesFetch(url, init)
    }),
  )
  if (enabled) setStoredToken('token-1')
}

beforeEach(async () => {
  vi.unstubAllGlobals()
  setActivePinia(createPinia())
  localStorage.clear()
  setStoredToken(null)
  await router.replace('/report-templates').catch(() => undefined)
  setActivePinia(createPinia())
})

describe('meta.requiresAuditAccess в таблице маршрутов', () => {
  it('помечен только журнал аудита', () => {
    const marked = routes.filter((r) => 'meta' in r && (r as { meta?: { requiresAuditAccess?: boolean } }).meta?.requiresAuditAccess).map((r) => r.name)
    expect(marked).toEqual(['audit-log'])
  })
})

describe('router.beforeEach — журнал аудита', () => {
  it('viewer не попадает в /audit-log: его возвращают на дашборд', async () => {
    stubServer('viewer')

    await router.push('/audit-log')

    expect(router.currentRoute.value.name).toBe('dashboard')
  })

  it.each<Role>(['admin', 'auth-off'])('%s открывает /audit-log', async (role) => {
    stubServer(role)

    await router.push('/audit-log')

    expect(router.currentRoute.value.name).toBe('audit-log')
  })

  it('viewer свободно ходит на страницу отчётов', async () => {
    stubServer('viewer')

    await router.push('/reports')

    expect(router.currentRoute.value.name).toBe('reports')
  })
})
