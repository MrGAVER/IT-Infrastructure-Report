// B-04: редакторы шаблонов отчётов сохраняют изменения (запись), поэтому роль «только чтение» в них не попадает —
// её уводит на список шаблонов, где формирование отчёта по-прежнему доступно.
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
      if (url.endsWith('/auth/me')) return json({ enabled, user: enabled ? { id: 'u1', username: role, role, is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' } : null })
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
  await router.replace('/report-templates').catch(() => undefined) // не оставляем состояния от прошлого теста
})

describe('meta.requiresWrite в таблице маршрутов', () => {
  it('помечены ровно два редактора шаблонов (xlsx и docx), остальные маршруты — нет', () => {
    const marked = routes.filter((r) => 'meta' in r && (r as { meta?: { requiresWrite?: boolean } }).meta?.requiresWrite).map((r) => r.name)
    expect(marked.sort()).toEqual(['report-template-editor', 'report-template-editor-docx'])
  })
})

describe('router.beforeEach — маршруты, требующие записи', () => {
  it.each(['/report-templates/t-1/editor', '/report-templates/t-1/editor-docx'])('viewer не попадает в %s: его возвращают на список шаблонов', async (path) => {
    stubServer('viewer')

    await router.push(path)

    expect(router.currentRoute.value.name).toBe('report-templates')
  })

  it.each<[Role, string]>([
    ['admin', '/report-templates/t-1/editor'],
    ['auth-off', '/report-templates/t-1/editor'],
    ['admin', '/report-templates/t-1/editor-docx'],
    ['auth-off', '/report-templates/t-1/editor-docx'],
  ])('%s открывает %s', async (role, path) => {
    stubServer(role)

    await router.push(path)

    expect(router.currentRoute.value.fullPath).toBe(path)
  })

  it('viewer свободно ходит на список шаблонов — формирование отчётов ему доступно', async () => {
    stubServer('viewer')

    await router.push('/report-templates')

    expect(router.currentRoute.value.name).toBe('report-templates')
  })
})
