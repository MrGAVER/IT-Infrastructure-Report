// FE-03 (ревью ветки fix/code-review-main-f06-stage2-f05, WCAG 2.4.3 / 1.3.2): при открытом модальном окне фон страницы недоступен
// не только клавише Tab (её держит ловушка фокуса), но и виртуальному курсору скринридера и указателю — для этого меню и основная
// область получают inert. Уведомления (ToastHost) лежат рядом с ними, а не внутри, поэтому остаются доступны: «Сохранено» в момент
// закрытия формы должно озвучиваться. Единственный владелец атрибута — AppShell: окно лишь сообщает, что оно открыто (стек в modalLayer.ts).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { realModalTeleport } from '../../__tests__/realModalTeleport'
import { useToast } from '../../composables/useToast'

vi.mock('vue-router', () => ({
  useRoute: () => ({ name: 'dashboard', meta: {} }),
  useRouter: () => ({ replace: vi.fn() }),
}))

import AppShell from '../AppShell.vue'
import BaseModal from '../../components/BaseModal.vue'

const stubs = { 'router-link': { template: '<a href="#"><slot /></a>' }, 'router-view': true, PortSyncPlanHost: true }

const phone = (matches: boolean) =>
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({ matches, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  )

/** Окно по образцу реальных (диалог с именем внутри BaseModal); `show` переключает его так же, как v-if в экране. */
function modalHost(show = ref(true), second = ref(false)) {
  const Dialog = (name: string, child?: () => unknown) =>
    h(BaseModal, { onClose: () => {} }, () => h('div', { class: 'modal card', role: 'dialog', 'aria-modal': 'true', 'aria-label': name }, [child?.() as never]))
  const Host = defineComponent({
    setup: () => () => (show.value ? Dialog('Первое', () => (second.value ? Dialog('Вложенное') : null)) : null),
  })
  return { Host, show, second }
}

const mounted: VueWrapper[] = []
function track<T extends VueWrapper>(wrapper: T): T {
  mounted.push(wrapper)
  return wrapper
}
const mountShell = () => track(mount(AppShell, { global: { stubs: { ...stubs, Sidebar: false } }, attachTo: document.body }))
const mountModal = (host: ReturnType<typeof modalHost>) => track(mount(host.Host, { attachTo: document.body, global: { ...realModalTeleport } }))

const main = () => document.querySelector<HTMLElement>('.app-shell > .main')!
const sidebar = () => document.querySelector<HTMLElement>('.app-shell > .sidebar')!

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  useToast().toasts.splice(0)
  phone(false)
})
afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('inert фона при открытом модальном окне', () => {
  it('пока окон нет, ни основная область, ни меню не inert', async () => {
    mountShell()
    await nextTick()
    expect(main().hasAttribute('inert')).toBe(false)
    expect(sidebar().hasAttribute('inert')).toBe(false)
  })

  it('при открытии окна .main и меню получают inert, после закрытия — теряют', async () => {
    mountShell()
    const host = modalHost()
    host.show.value = false
    const modal = mountModal(host)
    await nextTick()
    expect(main().hasAttribute('inert')).toBe(false)

    host.show.value = true
    await nextTick()
    expect(main().hasAttribute('inert')).toBe(true)
    expect(sidebar().hasAttribute('inert')).toBe(true)

    host.show.value = false
    await nextTick()
    expect(main().hasAttribute('inert')).toBe(false)
    expect(sidebar().hasAttribute('inert')).toBe(false)
    modal.unmount()
    mounted.splice(mounted.indexOf(modal), 1)
  })

  it('само окно (в <body>) не inert: оно не внутри .main и меню', async () => {
    mountShell()
    mountModal(modalHost())
    await nextTick()
    const overlay = document.body.querySelector('.modal-overlay')!
    expect(overlay).not.toBeNull()
    expect(overlay.closest('[inert]')).toBeNull()
  })

  it('уведомления доступны, пока окно открыто: ToastHost не лежит внутри inert-области', async () => {
    mountShell()
    mountModal(modalHost())
    useToast().notify('Сохранено', 'success')
    await nextTick()
    const host = document.querySelector('.toast-host')!
    expect(host).not.toBeNull()
    expect(main().hasAttribute('inert')).toBe(true)
    expect(host.closest('[inert]')).toBeNull()
    expect(host.querySelector('[role="status"]')?.textContent).toContain('Сохранено')
  })

  it('вложенные окна: inert снимается только после закрытия последнего', async () => {
    mountShell()
    const host = modalHost()
    host.second.value = true
    mountModal(host)
    await nextTick()
    expect(main().hasAttribute('inert')).toBe(true)

    host.second.value = false // закрылось вложенное, нижнее ещё открыто
    await nextTick()
    expect(main().hasAttribute('inert')).toBe(true)
    expect(sidebar().hasAttribute('inert')).toBe(true)

    host.show.value = false
    await nextTick()
    expect(main().hasAttribute('inert')).toBe(false)
    expect(sidebar().hasAttribute('inert')).toBe(false)
  })

  it('мобильное меню открыто, окно открылось и закрылось: inert от меню остаётся', async () => {
    phone(true)
    const shell = mountShell()
    await shell.get('.hamburger').trigger('click')
    expect(main().hasAttribute('inert')).toBe(true) // inert от меню

    const host = modalHost()
    mountModal(host)
    await nextTick()
    expect(main().hasAttribute('inert')).toBe(true)

    host.show.value = false // окно закрыто, меню всё ещё открыто
    await nextTick()
    expect(main().hasAttribute('inert')).toBe(true)

    await shell.get('.backdrop').trigger('click') // меню закрыто — теперь inert уходит
    await nextTick()
    expect(main().hasAttribute('inert')).toBe(false)
  })

  it('открытое окно, затем меню закрылось: inert от окна остаётся', async () => {
    phone(true)
    const shell = mountShell()
    await shell.get('.hamburger').trigger('click')
    const host = modalHost()
    mountModal(host)
    await nextTick()

    await shell.get('.backdrop').trigger('click')
    await nextTick()
    expect(main().hasAttribute('inert')).toBe(true) // окно по-прежнему открыто
  })

  it('inert снят ДО возврата фокуса на кнопку, открывшую окно: на inert-элемент браузер фокус не передаёт', async () => {
    mountShell()
    const opener = document.createElement('button')
    opener.textContent = 'Открыть'
    document.querySelector('.app-shell .content')!.appendChild(opener)
    opener.focus()

    const original = HTMLElement.prototype.focus
    const states: boolean[] = []
    vi.spyOn(HTMLElement.prototype, 'focus').mockImplementation(function (this: HTMLElement, ...args: Parameters<HTMLElement['focus']>) {
      if (this === opener) states.push(this.closest('[inert]') !== null)
      return original.apply(this, args)
    })

    const host = modalHost()
    mountModal(host) // окно запоминает кнопку, на которой стоял фокус
    await nextTick()
    expect(main().hasAttribute('inert')).toBe(true)

    host.show.value = false
    await nextTick()
    expect(states.length).toBeGreaterThan(0) // фокус на кнопку возвращался
    expect(states.at(-1)).toBe(false) // и к этому моменту фон уже не inert
  })
})
