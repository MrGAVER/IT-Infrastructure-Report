// Роутер-гард: настройки интерфейса грузятся с сервера ДО отрисовки маршрута (иначе списки создали бы свои
// сторы с умолчаниями), один раз на пользователя, а без сессии чужие настройки не показываются.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { router } from '../index'
import { usePreferencesStore } from '../../stores/preferences'
import { setStoredToken } from '../../api/client'
import { stubPreferencesApi, type PreferencesApiStub } from '../../stores/__tests__/preferencesApi'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

let api: PreferencesApiStub

/** Настройки — через общий помощник; /auth/status и /auth/me — отдельно (аутентификация включена или нет). */
function stubServer(auth: { enabled: boolean; user?: { id: string; username: string; role: string } }) {
  api = stubPreferencesApi({ user: { color_scheme: 'indigo' } })
  const preferencesFetch = globalThis.fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/status')) return json({ enabled: auth.enabled, session_ttl_hours: 12 })
      if (url.endsWith('/auth/me')) return json({ enabled: auth.enabled, user: auth.user ?? null })
      return preferencesFetch(url, init)
    }),
  )
}

beforeEach(async () => {
  vi.unstubAllGlobals()
  setActivePinia(createPinia())
  localStorage.clear()
  setStoredToken(null)
})

describe('router.beforeEach — настройки интерфейса', () => {
  it('аутентификация выключена: настройки загружаются один раз на первой навигации и не перезапрашиваются на следующих', async () => {
    stubServer({ enabled: false })

    await router.push('/devices')
    await router.push('/vms')
    await router.push('/dashboard')

    expect(api.gets).toBe(1)
    const prefs = usePreferencesStore()
    expect(prefs.loadedFor).toBe('anonymous')
    expect(prefs.user.color_scheme).toBe('indigo')
  })

  it('вход выполнен: настройки загружаются под конкретного пользователя', async () => {
    setStoredToken('token-1')
    stubServer({ enabled: true, user: { id: 'user-7', username: 'engineer', role: 'viewer' } })

    await router.push('/containers')

    expect(usePreferencesStore().loadedFor).toBe('user-7')
    expect(api.gets).toBe(1)
  })

  it('нужен вход: настройки не запрашиваются, а ранее загруженные чужие сбрасываются', async () => {
    stubServer({ enabled: true }) // без токена — сессии нет
    const prefs = usePreferencesStore()
    prefs.user = { color_scheme: 'copper' }
    prefs.loadedFor = 'user-1'

    await router.push('/information-systems')

    expect(router.currentRoute.value.name).toBe('login')
    expect(api.gets).toBe(0)
    expect(prefs.loaded).toBe(false)
    expect(prefs.user).toEqual({})
  })
})
