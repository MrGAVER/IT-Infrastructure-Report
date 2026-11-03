// Ревью 2.158.0, поток «исполнитель 1»: семантика и доступность каркаса — UI-15 (название не рвётся по дефису), UI-19 (ARIA меню,
// inert фона, <span> вместо <div> внутри <button>).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { declaration, readStyles, ruleBody } from '../../__tests__/cssSource'
import { useAuthStore } from '../../stores/auth'

vi.mock('vue-router', () => ({
  useRoute: () => ({ name: 'dashboard', meta: {} }),
  useRouter: () => ({ replace: vi.fn() }),
}))

import AppShell from '../AppShell.vue'
import Sidebar from '../Sidebar.vue'
import Topbar from '../Topbar.vue'

const stubs = { 'router-link': { template: '<a href="#"><slot /></a>' }, 'router-view': true, ToastHost: true, PortSyncPlanHost: true }

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
})
afterEach(() => vi.unstubAllGlobals())

describe('UI-15: название в меню', () => {
  it('«ИТ-инфраструктуры» обёрнуто в неразрывный фрагмент, а название организации — отдельным элементом', () => {
    const wrapper = mount(Sidebar, { props: { open: false }, global: { stubs } })
    expect(wrapper.get('.brand-text .nobreak').text()).toBe('ИТ-инфраструктуры')
    expect(wrapper.find('.brand-text .org').exists()).toBe(true)
  })

  it('.nobreak — white-space: nowrap, и правило «вторая строка» больше не цепляет любой span в названии', () => {
    const css = readStyles('src/layout/Sidebar.vue')
    expect(declaration(ruleBody(css, '.nobreak'), 'white-space')).toBe('nowrap')
    expect(ruleBody(css, '.brand-text span')).toBeNull()
    expect(declaration(ruleBody(css, '.brand-text .org'), 'display')).toBe('block')
  })
})

describe('UI-19: гамбургер и фон при открытом меню', () => {
  it('у гамбургера есть aria-controls на меню и aria-expanded, который следует за состоянием', async () => {
    const wrapper = mount(Topbar, { props: { title: 'Дашборд', crumb: 'Главная', sidebarOpen: false } })
    const burger = wrapper.get('.hamburger')
    expect(burger.attributes('aria-controls')).toBe('app-sidebar')
    expect(burger.attributes('aria-expanded')).toBe('false')
    await wrapper.setProps({ sidebarOpen: true })
    expect(burger.attributes('aria-expanded')).toBe('true')
  })

  it('меню — это <aside id="app-sidebar">, на который ссылается гамбургер', () => {
    const wrapper = mount(Sidebar, { props: { open: false }, global: { stubs } })
    expect(wrapper.get('aside').attributes('id')).toBe('app-sidebar')
  })

  it('внутри кнопки чипа пользователя нет <div> — только фразовое содержимое (span)', () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = { id: 'u1', username: 'Андрей', role: 'admin', is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' }
    const wrapper = mount(Topbar, { props: { title: 'Дашборд', crumb: 'Главная' } })
    const trigger = wrapper.get('.user-chip-trigger')
    expect(trigger.findAll('div')).toHaveLength(0)
    expect(trigger.get('.avatar').element.tagName).toBe('SPAN')
    expect(trigger.get('.who').element.tagName).toBe('SPAN')
  })

  describe('inert на основной области', () => {
    const phone = (matches: boolean) =>
      vi.stubGlobal(
        'matchMedia',
        vi.fn(() => ({ matches, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
      )
    const mountShell = () => mount(AppShell, { global: { stubs: { ...stubs, Sidebar: false } }, attachTo: document.body })

    it('на телефоне при открытом меню .main получает inert — фон не доступен ни мышью, ни клавиатурой', async () => {
      phone(true)
      const wrapper = mountShell()
      expect(wrapper.get('.main').attributes('inert')).toBeUndefined()
      await wrapper.get('.hamburger').trigger('click')
      expect(wrapper.get('.main').attributes('inert')).toBeDefined()
      wrapper.unmount()
    })

    it('на десктопе inert не ставится даже при sidebarOpen: меню там постоянное и фон не блокируется', async () => {
      phone(false)
      const wrapper = mountShell()
      await wrapper.get('.hamburger').trigger('click')
      expect(wrapper.get('.main').attributes('inert')).toBeUndefined()
      wrapper.unmount()
    })

    it('при открытии меню фокус уходит в меню (иначе inert оставил бы его на скрытом гамбургере), при закрытии — возвращается на гамбургер', async () => {
      phone(true)
      const wrapper = mountShell()
      const burger = wrapper.get('.hamburger').element as HTMLElement
      burger.focus()
      await wrapper.get('.hamburger').trigger('click')
      await nextTick()
      await nextTick()
      expect(document.activeElement && wrapper.get('aside').element.contains(document.activeElement)).toBe(true)

      await wrapper.get('.backdrop').trigger('click')
      await nextTick()
      await nextTick()
      expect(document.activeElement).toBe(burger)
      wrapper.unmount()
    })
  })
})
