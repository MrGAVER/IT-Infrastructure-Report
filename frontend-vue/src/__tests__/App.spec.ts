import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import App from '../App.vue'
import { useAuthStore } from '../stores/auth'

const replaceMock = vi.fn()
const mockRoute = { name: 'devices' as string, fullPath: '/devices?x=1', query: {} as Record<string, string> }
vi.mock('vue-router', () => ({
  useRoute: () => mockRoute,
  useRouter: () => ({ replace: replaceMock }),
}))
vi.mock('../layout/AppShell.vue', () => ({ default: { template: '<div class="app-shell-stub" />' } }))

beforeEach(() => {
  setActivePinia(createPinia())
  replaceMock.mockClear()
  mockRoute.name = 'devices'
})

describe('App.vue', () => {
  // Фикс auth п.1.1 (батч4): без этого watcher'а пользователь, у которого "из-под ног"
  // включили аутентификацию (см. stores/auth.ts:setEnabled) или истёк токен на сервере (см.
  // main.ts:handleUnauthorized), оставался бы на текущей защищённой странице, пока сам
  // куда-нибудь не перешёл — роутер-гард (router/index.ts) реагирует только на навигацию.
  it('needsLogin становится true "из-под" открытой страницы -> форсирует переход на /login с redirect на текущий путь', async () => {
    const auth = useAuthStore()
    const wrapper = mount(App, { global: { stubs: { 'router-view': true } } })
    expect(replaceMock).not.toHaveBeenCalled()

    auth.enabled = true // user всё ещё null -> needsLogin переключается в true
    await wrapper.vm.$nextTick()

    expect(replaceMock).toHaveBeenCalledWith({ name: 'login', query: { redirect: '/devices?x=1' } })
  })

  it('уже на экране входа — повторный принудительный переход не нужен', async () => {
    mockRoute.name = 'login'
    const auth = useAuthStore()
    mount(App, { global: { stubs: { 'router-view': true } } })

    auth.enabled = true
    await Promise.resolve()

    expect(replaceMock).not.toHaveBeenCalled()
  })

  it('пока пользователь вошёл (needsLogin остаётся false) — переход не форсируется', async () => {
    const auth = useAuthStore()
    mount(App, { global: { stubs: { 'router-view': true } } })

    auth.enabled = true
    auth.user = { id: 'u1', username: 'admin', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }
    await Promise.resolve()

    expect(replaceMock).not.toHaveBeenCalled()
  })
})
