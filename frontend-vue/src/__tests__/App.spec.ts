import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import App from '../App.vue'
import { api, getStoredToken } from '../api/client'
import type { AuthMeResponse, AuthUser } from '../api/types'
import { useAuthStore } from '../stores/auth'

const replaceMock = vi.fn()
const mockRoute = { name: 'devices' as string | undefined, fullPath: '/devices?x=1', query: {} as Record<string, string> }
vi.mock('vue-router', () => ({
  useRoute: () => mockRoute,
  useRouter: () => ({ replace: replaceMock }),
}))
vi.mock('../layout/AppShell.vue', () => ({ default: { template: '<div class="app-shell-stub" />' } }))
vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  api: { get: vi.fn() },
  getStoredToken: vi.fn(() => null),
  setStoredToken: vi.fn(),
}))

const ADMIN: AuthUser = { id: 'u1', username: 'admin', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }

beforeEach(() => {
  setActivePinia(createPinia())
  replaceMock.mockClear()
  mockRoute.name = 'devices'
  mockRoute.fullPath = '/devices?x=1'
  vi.mocked(api.get).mockReset()
  vi.mocked(getStoredToken).mockReturnValue(null)
})

describe('App.vue', () => {
  // Фикс auth п.1.1 (батч4): без этого watcher'а пользователь, у которого "из-под ног"
  // включили аутентификацию (см. stores/auth.ts:setEnabled) или истёк токен на сервере (см.
  // main.ts:handleUnauthorized), оставался бы на текущей защищённой странице, пока сам
  // куда-нибудь не перешёл — роутер-гард (router/index.ts) реагирует только на навигацию.
  it('needsLogin становится true "из-под" открытой страницы -> форсирует переход на /login с redirect на текущий путь', async () => {
    const auth = useAuthStore()
    auth.initialized = true // страница уже открыта и работает: инициализация давно закончилась
    const wrapper = mount(App, { global: { stubs: { 'router-view': true } } })
    expect(replaceMock).not.toHaveBeenCalled()

    auth.enabled = true // user всё ещё null -> needsLogin переключается в true
    await wrapper.vm.$nextTick()

    expect(replaceMock).toHaveBeenCalledWith({ name: 'login', query: { redirect: '/devices?x=1' } })
  })

  it('уже на экране входа — повторный принудительный переход не нужен', async () => {
    mockRoute.name = 'login'
    const auth = useAuthStore()
    auth.initialized = true
    mount(App, { global: { stubs: { 'router-view': true } } })

    auth.enabled = true
    await Promise.resolve()

    expect(replaceMock).not.toHaveBeenCalled()
  })

  it('пока пользователь вошёл (needsLogin остаётся false) — переход не форсируется', async () => {
    const auth = useAuthStore()
    auth.initialized = true
    mount(App, { global: { stubs: { 'router-view': true } } })

    auth.enabled = true
    auth.user = ADMIN
    await Promise.resolve()

    expect(replaceMock).not.toHaveBeenCalled()
  })

  // Дефект, найденный при e2e-проверках (поток A ревью веб-интерфейса): F5 или закладка на любой экран, кроме дашборда,
  // при включённой аутентификации вели на /dashboard. init() выставляет enabled = true раньше, чем придёт /auth/me, и на это
  // время needsLogin истинно — watch уводил на /login с redirect = '/' (route в этот момент стартовый), а оттуда после
  // /auth/me — на дашборд.
  describe('обновление страницы с включённой аутентификацией и валидной сессией', () => {
    function deferredMe() {
      let resolve!: (me: AuthMeResponse) => void
      const promise = new Promise<AuthMeResponse>((res) => {
        resolve = res
      })
      return { promise, resolve }
    }

    it('пока init() ждёт /auth/me, needsLogin истинно, но переход на /login не форсируется — запрошенный экран сохраняется', async () => {
      mockRoute.name = undefined // первая навигация ещё стоит в роутер-гарде: route стартовый
      mockRoute.fullPath = '/'
      const me = deferredMe()
      vi.mocked(getStoredToken).mockReturnValue('token')
      vi.mocked(api.get).mockImplementation(((path: string) => (path === '/auth/status' ? Promise.resolve({ enabled: true }) : me.promise)) as typeof api.get)
      const auth = useAuthStore()
      mount(App, { global: { stubs: { 'router-view': true } } })

      const init = auth.init()
      await flushPromises() // /auth/status получен, /auth/me ещё в пути

      expect(auth.enabled).toBe(true)
      expect(auth.needsLogin).toBe(true) // сам механизм дефекта: «нужен вход», хотя сессия ещё не проверена
      expect(auth.initialized).toBe(false)
      expect(replaceMock).not.toHaveBeenCalled()

      me.resolve({ enabled: true, user: ADMIN })
      await init
      await flushPromises()

      expect(auth.needsLogin).toBe(false)
      expect(auth.initialized).toBe(true)
      expect(replaceMock).not.toHaveBeenCalled()
    })

    it('токен недействителен: App сам не перенаправляет — вход для первой навигации решает роутер-гард с настоящим to.fullPath', async () => {
      mockRoute.name = undefined
      mockRoute.fullPath = '/'
      vi.mocked(getStoredToken).mockReturnValue('stale-token')
      vi.mocked(api.get).mockImplementation(((path: string) =>
        path === '/auth/status' ? Promise.resolve({ enabled: true }) : Promise.reject(new Error('401'))) as typeof api.get)
      const auth = useAuthStore()
      mount(App, { global: { stubs: { 'router-view': true } } })

      await auth.init()
      await flushPromises()

      expect(auth.needsLogin).toBe(true)
      expect(replaceMock).not.toHaveBeenCalled()
    })
  })
})
