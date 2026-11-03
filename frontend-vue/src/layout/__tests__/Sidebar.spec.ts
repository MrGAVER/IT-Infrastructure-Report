import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import Sidebar from '../Sidebar.vue'
import { useOrganizationStore } from '../../stores/organization'
import { useAuthStore } from '../../stores/auth'
import type { AuthUser } from '../../api/types'
import { declaration, mediaBlock, readStyles, ruleBody } from '../../__tests__/cssSource'

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
    expect(wrapper.find('.brand-text .org').text()).toBe('ООО «Организация»')
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
    expect(wrapper.find('.brand-text .org').text()).toBe('ООО «Ромашка»')
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

// Ревью merge/review-2158-executors: вёрстку jsdom не считает, поэтому дефекты проверяются по исходнику стилей,
// а в браузере — по ручным критериям приёмки (390×667 и 1440×900).
describe('Sidebar.vue — вёрстка меню (UI-1, UI-5, UI-10)', () => {
  const styles = readStyles('src/layout/Sidebar.vue')
  const mobile = mediaBlock(styles, '(max-width: 760px)') ?? ''
  const desktop = mediaBlock(styles, '(min-width: 761px)') ?? ''

  // UI-1: на 390×667 высота содержимого 823 px, а у position: fixed меню не было прокрутки —
  // «Шаблоны отчётов», «Правила согласования портов», «Журнал аудита», «Настройки» и «Выйти» были недоступны.
  it('UI-1: мобильное меню прокручивается и не передаёт прокрутку странице', () => {
    const body = ruleBody(mobile, '.sidebar')
    expect(declaration(body, 'overflow-y')).toBe('auto')
    expect(declaration(body, 'overscroll-behavior')).toBe('contain')
    expect(declaration(body, 'padding-bottom')).toContain('env(safe-area-inset-bottom')
  })

  // UI-5: на десктопе сайдбар уезжал вместе со страницей — «Настройки» и «Выйти» оказывались внизу документа.
  it('UI-5: на десктопе сайдбар закреплён на высоту окна и прокручивается сам', () => {
    const body = ruleBody(desktop, '.sidebar')
    expect(declaration(body, 'position')).toBe('sticky')
    expect(declaration(body, 'top')).toBe('0')
    expect(declaration(body, 'align-self')).toBe('flex-start')
    expect(body).toMatch(/height:\s*100dvh/)
    expect(declaration(body, 'overflow-y')).toBe('auto')
  })

  // UI-10: закрытое меню было только сдвинуто за экран — первый Tab попадал на скрытую ссылку «Дашборд».
  it('UI-10: закрытое мобильное меню скрыто из порядка фокуса (visibility: hidden с задержкой после анимации)', () => {
    const body = ruleBody(mobile, '.sidebar:not(.open)')
    expect(declaration(body, 'visibility')).toBe('hidden')
    expect(declaration(body, 'transition')).toContain('visibility 0s')
  })
})

describe('Sidebar.vue — закрытие по Esc (UI-10)', () => {
  const mountSidebar = (open: boolean) =>
    mount(Sidebar, {
      props: { open },
      attachTo: document.body,
      global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
    })
  const pressEscape = () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))

  it('Esc при открытом меню просит его закрыть', () => {
    const wrapper = mountSidebar(true)
    pressEscape()
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })

  it('Esc при закрытом меню ничего не делает, а после размонтирования слушатель снят', () => {
    const closed = mountSidebar(false)
    pressEscape()
    expect(closed.emitted('close')).toBeUndefined()
    closed.unmount()

    const opened = mountSidebar(true)
    opened.unmount()
    pressEscape()
    expect(opened.emitted('close')).toBeUndefined()
  })

  it('другие клавиши меню не закрывают', () => {
    const wrapper = mountSidebar(true)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    expect(wrapper.emitted('close')).toBeUndefined()
    wrapper.unmount()
  })
})

// UI-11: «Информационные системы», «Стеки устройств», «Другие справочники» и «Шаблоны отчётов» делили i-layers,
// ВМ и контейнеры — i-box, диаграмма и подразделения — i-sitemap, подключения и правила портов — i-network.
describe('Sidebar.vue — иконки пунктов меню (UI-11)', () => {
  it('у каждого пункта меню своя иконка', () => {
    const wrapper = mount(Sidebar, {
      props: { open: false },
      global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
    })
    const icons = wrapper.findAll('.nav use').map((use) => use.attributes('href'))
    expect(icons.length).toBeGreaterThanOrEqual(14)
    const duplicates = icons.filter((icon, index) => icons.indexOf(icon) !== index)
    expect(duplicates).toEqual([])
  })

  it('и при включённой аутентификации (добавляется «Выйти») иконки не повторяются', () => {
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = {
      id: 'u1',
      username: 'admin',
      role: 'admin',
      is_active: true,
      last_login_at: null,
      locked: false,
      created_at: '2026-01-01T00:00:00',
    } as AuthUser
    const wrapper = mount(Sidebar, {
      props: { open: false },
      global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
    })
    const icons = wrapper.findAll('use').map((use) => use.attributes('href'))
    expect(icons.filter((icon, index) => icons.indexOf(icon) !== index)).toEqual([])
  })
})
