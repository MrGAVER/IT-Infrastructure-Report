import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import Sidebar from '../Sidebar.vue'
import { useOrganizationStore } from '../../stores/organization'
import { useAuthStore } from '../../stores/auth'
import type { AuthUser } from '../../api/types'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

describe('Sidebar.vue', () => {
  it('по умолчанию показывает "ООО «Организация»"', () => {
    const wrapper = mount(Sidebar, {
      props: { open: false },
      global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
    })
    expect(wrapper.find('.brand-text span').text()).toBe('ООО «Организация»')
  })

  // Регресс на п.6: раньше строка была захардкожена в шаблоне, а не в сторе — изменить
  // наименование можно было только правкой исходников.
  it('отображает наименование организации, заданное в настройках (stores/organization.ts)', () => {
    const organization = useOrganizationStore()
    organization.setName('ООО «Ромашка»')
    const wrapper = mount(Sidebar, {
      props: { open: false },
      global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
    })
    expect(wrapper.find('.brand-text span').text()).toBe('ООО «Ромашка»')
  })

  // п.6: пункт меню "Другие справочники", ведущий на новый OtherCatalogsView.vue.
  it('содержит пункт меню "Другие справочники"', () => {
    const wrapper = mount(Sidebar, {
      props: { open: false },
      global: { stubs: { 'router-link': { template: '<a :href="to"><slot /></a>', props: ['to'] } } },
    })
    const link = wrapper.findAll('a').find((a) => a.text().includes('Другие справочники'))
    expect(link?.attributes('href')).toBe('/other-catalogs')
  })
})

// A-23: журнал аудита содержит имена, IP-адреса и неудачные входы — сервер отдаёт его только администратору (viewer получил бы 403).
describe('Sidebar.vue — пункт «Журнал аудита» по роли', () => {
  const mountSidebar = () =>
    mount(Sidebar, { props: { open: false }, global: { stubs: { 'router-link': { template: '<a :href="to"><slot /></a>', props: ['to'] } } } })
  const hasAuditLink = (wrapper: ReturnType<typeof mountSidebar>) => wrapper.findAll('a').some((a) => a.attributes('href') === '/audit-log')
  const signIn = (role: AuthUser['role']) => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = { id: 'u1', username: role, role, is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' } as AuthUser
  }

  it('viewer не видит пункт, остальные — видят', () => {
    signIn('viewer')
    expect(hasAuditLink(mountSidebar())).toBe(false)
  })

  it('администратор видит пункт', () => {
    signIn('admin')
    expect(hasAuditLink(mountSidebar())).toBe(true)
  })

  it('при выключенной аутентификации пункт виден (пользователь один, журнал открыт)', () => {
    expect(hasAuditLink(mountSidebar())).toBe(true)
  })

  it('прочие пункты раздела «Система» viewer по-прежнему видит', () => {
    signIn('viewer')
    const wrapper = mountSidebar()
    const hrefs = wrapper.findAll('a').map((a) => a.attributes('href'))
    expect(hrefs).toContain('/reports')
    expect(hrefs).toContain('/port-sync-rules')
  })
})
