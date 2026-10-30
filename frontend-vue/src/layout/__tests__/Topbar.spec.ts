import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import Topbar from '../Topbar.vue'
import { useAuthStore } from '../../stores/auth'

const replaceMock = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ replace: replaceMock }),
}))

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  replaceMock.mockClear()
})

describe('Topbar.vue', () => {
  it('фикс auth п.1.2: без аутентификации (по умолчанию) бейдж пользователя не показывается', () => {
    const wrapper = mount(Topbar, { props: { title: 'Дашборд', crumb: 'Главная' } })
    expect(wrapper.find('.user-chip').exists()).toBe(false)
  })

  it('показывает реальные имя пользователя, роль и инициал в кружке вместо статичного "Администратор"', () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = { id: 'u1', username: 'Андрей Л.', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }
    const wrapper = mount(Topbar, { props: { title: 'Дашборд', crumb: 'Главная' } })

    expect(wrapper.find('.who b').text()).toBe('Андрей Л.')
    expect(wrapper.find('.who span').text()).toBe('Администратор')
    expect(wrapper.find('.avatar').text()).toBe('А') // инициал реального имени, не хардкод
  })

  it('роль viewer отображается как "Только просмотр"', () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = { id: 'u2', username: 'Гость', role: 'viewer', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }
    const wrapper = mount(Topbar, { props: { title: 'Дашборд', crumb: 'Главная' } })

    expect(wrapper.find('.who span').text()).toBe('Только просмотр')
  })

  it('клик по бейджу раскрывает выпадающее меню с кнопкой "Выйти", клик вне области его закрывает', async () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = { id: 'u1', username: 'Андрей', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }
    const wrapper = mount(Topbar, { props: { title: 'Дашборд', crumb: 'Главная' }, attachTo: document.body })

    expect(wrapper.find('.user-menu').exists()).toBe(false)
    await wrapper.find('.user-chip-trigger').trigger('click')
    expect(wrapper.find('.user-menu').exists()).toBe(true)
    expect(wrapper.find('.user-menu-item').text()).toContain('Выйти')

    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.user-menu').exists()).toBe(false)

    wrapper.unmount()
  })

  it('фикс auth п.1.1: клик "Выйти" завершает сессию и ведёт на экран входа', async () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = { id: 'u1', username: 'Андрей', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({}))),
    )
    const wrapper = mount(Topbar, { props: { title: 'Дашборд', crumb: 'Главная' } })

    await wrapper.find('.user-chip-trigger').trigger('click')
    await wrapper.find('.user-menu-item').trigger('click')
    await flushPromises()

    expect(auth.user).toBeNull()
    expect(replaceMock).toHaveBeenCalledWith({ name: 'login' })
  })
})
