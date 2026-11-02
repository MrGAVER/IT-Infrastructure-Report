import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import Topbar from '../Topbar.vue'
import { useAuthStore } from '../../stores/auth'
import { declaration, readStyles, ruleBody } from '../../__tests__/cssSource'

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

// Ревью merge/review-2158-executors.
describe('Topbar.vue — вёрстка (UI-5, UI-7)', () => {
  const styles = readStyles('src/layout/Topbar.vue')

  // UI-7: --surface-1 — алиас на --surface (theme.css), то есть ровно фон топбара и самого меню, поэтому hover не был виден.
  it('UI-7: hover чипа пользователя и пункта меню заметен — фон --surface-2, а не --surface-1', () => {
    for (const selector of ['.user-chip-trigger:hover', '.user-menu-item:hover']) {
      expect(declaration(ruleBody(styles, selector), 'background'), selector).toBe('var(--surface-2)')
    }
  })

  // UI-5: топбар прокручивался вместе со страницей; z-index ниже подложки мобильного меню (25), самого меню (30) и модалок (60+).
  it('UI-5: топбар закреплён вверху окна под подложкой меню и модалками', () => {
    const body = ruleBody(styles, '.topbar')
    expect(declaration(body, 'position')).toBe('sticky')
    expect(declaration(body, 'top')).toBe('0')
    expect(Number(declaration(body, 'z-index'))).toBeLessThan(25)
    expect(Number(declaration(body, 'z-index'))).toBeGreaterThan(0)
  })
})

describe('Topbar.vue — закрытие меню пользователя по Esc (UI-10)', () => {
  const signInAndMount = () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = { id: 'u1', username: 'Андрей', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }
    return mount(Topbar, { props: { title: 'Дашборд', crumb: 'Главная' }, attachTo: document.body })
  }
  const pressEscape = () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))

  it('Esc закрывает открытое меню и возвращает фокус на кнопку-чип', async () => {
    const wrapper = signInAndMount()
    await wrapper.find('.user-chip-trigger').trigger('click')
    expect(wrapper.find('.user-menu').exists()).toBe(true)

    pressEscape()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.user-menu').exists()).toBe(false)
    expect(document.activeElement).toBe(wrapper.find('.user-chip-trigger').element)
    wrapper.unmount()
  })

  it('Esc при закрытом меню фокус не трогает', async () => {
    const wrapper = signInAndMount()
    const outside = document.createElement('input')
    document.body.appendChild(outside)
    outside.focus()

    pressEscape()
    await wrapper.vm.$nextTick()

    expect(document.activeElement).toBe(outside)
    wrapper.unmount()
  })

  it('после размонтирования слушатель Esc снят', async () => {
    const wrapper = signInAndMount()
    const trigger = wrapper.find('.user-chip-trigger').element as HTMLElement
    await wrapper.find('.user-chip-trigger').trigger('click')
    wrapper.unmount()
    document.body.focus()

    pressEscape()

    expect(document.activeElement).not.toBe(trigger)
  })
})
