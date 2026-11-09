// F-01/F-03 (код-ревью main): BaseModal — единственная основа всех модальных окон. Здесь включён настоящий Teleport
// (в остальных тестах он отключён — см. src/__tests__/setup.ts), поэтому окно ищется в document.body.
import { afterEach, describe, expect, it } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { realModalTeleport } from '../../__tests__/realModalTeleport'
import { readSource } from '../../__tests__/cssSource'
import { MODAL_TELEPORT_DISABLED } from '../baseModalKeys'
import BaseModal from '../BaseModal.vue'
import { useModalStack } from '../../composables/modalLayer'

const mounted: VueWrapper[] = []

/** Окно по образцу реальных: диалог с именем, кнопка в шапке, поле и кнопка в подвале; child — вложенное окно внутри. */
function Win(name: string, child?: ReturnType<typeof defineComponent>) {
  return defineComponent({
    emits: ['close'],
    setup(_, { emit }) {
      return () =>
        h(BaseModal, { onClose: () => emit('close') }, () =>
          h('div', { class: 'modal card', role: 'dialog', 'aria-modal': 'true', 'aria-label': name }, [
            h('button', { id: `${name}-close`, type: 'button' }, 'Закрыть'),
            h('input', { id: `${name}-field` }),
            h('button', { id: `${name}-save`, type: 'button' }, 'Сохранить'),
            child ? h(child) : null,
          ]),
        )
    },
  })
}

function open(component: ReturnType<typeof defineComponent>, props: Record<string, unknown> = {}) {
  const wrapper = mount(component, { props, attachTo: document.body, global: { ...realModalTeleport } })
  mounted.push(wrapper)
  return wrapper
}

const overlays = () => Array.from(document.body.querySelectorAll<HTMLElement>('.modal-overlay'))
const active = () => document.activeElement?.id || document.activeElement?.getAttribute('aria-label') || document.activeElement?.tagName

function key(init: KeyboardEventInit, target: EventTarget = document.body): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init })
  target.dispatchEvent(event)
  return event
}

afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount()
  document.body.innerHTML = ''
  document.body.style.cssText = ''
})

describe('BaseModal: разметка', () => {
  it('выносит окно в <body> — подложка не лежит внутри обёртки компонента', () => {
    const wrapper = open(Win('a'))
    expect(overlays()).toHaveLength(1)
    expect(wrapper.html()).not.toContain('modal-overlay')
    expect(overlays()[0].parentElement).toBe(document.body)
    expect(overlays()[0].querySelector('[role="dialog"]')).not.toBeNull()
  })

  it('атрибуты родителя (data-testid) попадают на подложку', () => {
    open(Win('a'), { 'data-testid': 'my-dialog' })
    expect(overlays()[0].getAttribute('data-testid')).toBe('my-dialog')
  })

  it('по умолчанию окно у верхнего края с отступом 40px; align="center" и offset меняют раскладку', () => {
    open(Win('a'))
    expect(overlays()[0].classList.contains('modal-overlay--center')).toBe(false)
    expect(overlays()[0].style.getPropertyValue('--modal-offset')).toBe('40px')

    open(Win('b'), { offset: 60 })
    expect(overlays()[1].style.getPropertyValue('--modal-offset')).toBe('60px')

    open(Win('c'), { align: 'center' })
    expect(overlays()[2].classList.contains('modal-overlay--center')).toBe(true)
  })
})

describe('BaseModal: закрытие', () => {
  it('клик по подложке закрывает окно (событие close), клик внутри карточки — нет', async () => {
    const wrapper = open(Win('a'))
    const overlay = overlays()[0]
    overlay.querySelector('[role="dialog"]')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    overlay.querySelector('[role="dialog"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(wrapper.emitted('close')).toBeUndefined()

    overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    overlay.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('выделение текста в карточке, закончившееся над подложкой, окно не закрывает', () => {
    const wrapper = open(Win('a'))
    const overlay = overlays()[0]
    overlay.querySelector('input')!.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    overlay.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(wrapper.emitted('close')).toBeUndefined()
  })

  it('Esc закрывает окно', () => {
    const wrapper = open(Win('a'))
    expect(key({ key: 'Escape' }).defaultPrevented).toBe(true)
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('из вложенных окон по Esc закрывается только верхнее', async () => {
    const wrapper = open(Win('outer', Win('inner')))
    const [outerModal, innerModal] = wrapper.findAllComponents(BaseModal)
    expect(overlays()).toHaveLength(2)
    key({ key: 'Escape' })
    expect(outerModal.emitted('close')).toBeUndefined()
    expect(innerModal.emitted('close')).toHaveLength(1)
  })
})

// FE-05 (ревью ветки fix/code-review-main-f06-stage2-f05): в боевом BaseModal жил тестовый шов, зависевший от внутренностей Vue
// (getCurrentInstance) и от имени компонента-владельца (type.__name), а setup.ts хранил список имён окон. Теперь шов — обычный булев
// ключ, а решение «где рисовать окно» принимает тестовая инфраструктура.
describe('BaseModal: тестовый переключатель Teleport не вшит в боевой код (FE-05)', () => {
  it('BaseModal не использует внутренности Vue и не знает имён окон-владельцев', () => {
    const source = readSource('src/components/BaseModal.vue')
    expect(source).not.toContain('getCurrentInstance')
    expect(source).not.toContain('__name')
    expect(source).not.toContain('ownerName')
  })

  it('в приложении ключ не задаётся, поэтому значение по умолчанию — «Teleport включён»: окно в <body>', () => {
    // Тесты всегда задают ключ (setup.ts), поэтому умолчание проверяется по исходнику: inject(ключ, false).
    expect(readSource('src/components/BaseModal.vue')).toContain('inject(MODAL_TELEPORT_DISABLED, false)')
  })

  const Host = defineComponent({
    setup: () => () => h(BaseModal, null, () => h('div', { class: 'modal card', role: 'dialog', 'aria-label': 'Окно' })),
  })
  const hosts: VueWrapper[] = []
  afterEach(() => {
    while (hosts.length) hosts.pop()!.unmount()
  })

  it('ключ true — окно рисуется на месте, внутри обёртки теста', () => {
    const wrapper = mount(Host, { attachTo: document.body, global: { provide: { [MODAL_TELEPORT_DISABLED]: true } } })
    hosts.push(wrapper)
    expect(wrapper.find('.modal-overlay').exists()).toBe(true)
  })

  it('ключ false — окно уходит в <body>, вне обёртки теста', () => {
    const wrapper = mount(Host, { attachTo: document.body, global: { provide: { [MODAL_TELEPORT_DISABLED]: false } } })
    hosts.push(wrapper)
    expect(wrapper.find('.modal-overlay').exists()).toBe(false)
    expect(document.body.querySelector(':scope > .modal-overlay')).not.toBeNull()
  })
})

describe('BaseModal: Esc и фокус опираются на один стек окон (FE-06)', () => {
  it('Esc закрывает окно только пока оно верхнее в общем стеке: тот, кто встал в стек выше, забирает «верхнее» и у Esc', async () => {
    // Раньше у Esc был свой, второй стек (useEscapeClose), и BaseModal под таким «чужим» верхним слоем всё равно закрывался по Esc,
    // хотя ловушка фокуса уже считала верхним не его.
    const wrapper = open(Win('a'))
    const above = mount(
      defineComponent({
        setup() {
          useModalStack()
          return () => h('div', { class: 'foreign-layer' })
        },
      }),
      { attachTo: document.body },
    )
    mounted.push(above)

    key({ key: 'Escape' })
    expect(wrapper.findComponent(BaseModal).emitted('close')).toBeUndefined()

    above.unmount()
    mounted.splice(mounted.indexOf(above), 1)
    key({ key: 'Escape' })
    expect(wrapper.findComponent(BaseModal).emitted('close')).toHaveLength(1)
  })

  it('по одному нажатию Esc закрывается ровно одно окно из трёх вложенных, и событие помечено обработанным', () => {
    const wrapper = open(Win('a', Win('b', Win('c'))))
    const [first, second, third] = wrapper.findAllComponents(BaseModal)
    const event = key({ key: 'Escape' })
    expect(third.emitted('close')).toHaveLength(1)
    expect(second.emitted('close')).toBeUndefined()
    expect(first.emitted('close')).toBeUndefined()
    expect(event.defaultPrevented).toBe(true)
  })
})

describe('BaseModal: фокус', () => {
  it('при открытии фокус уходит с кнопки-открывателя в окно, при закрытии возвращается на неё', async () => {
    const opener = document.createElement('button')
    opener.id = 'opener'
    document.body.appendChild(opener)
    opener.focus()

    const wrapper = open(Win('a'))
    expect(active()).toBe('a')
    expect(overlays()[0].contains(document.activeElement)).toBe(true)

    wrapper.unmount()
    mounted.pop()
    await nextTick()
    expect(active()).toBe('opener')
  })

  it('Tab с последней кнопки окна переходит на первую, Shift+Tab с первой — на последнюю: из окна в фон фокус не уходит', () => {
    open(Win('a'))
    document.getElementById('a-save')!.focus()
    expect(key({ key: 'Tab' }, document.activeElement!).defaultPrevented).toBe(true)
    expect(active()).toBe('a-close')

    expect(key({ key: 'Tab', shiftKey: true }, document.activeElement!).defaultPrevented).toBe(true)
    expect(active()).toBe('a-save')
  })

  it('вложенное окно забирает фокус себе, и цикл Tab идёт внутри него', () => {
    open(Win('outer', Win('inner')))
    expect(active()).toBe('inner')
    document.getElementById('inner-save')!.focus()
    key({ key: 'Tab' }, document.activeElement!)
    expect(active()).toBe('inner-close')
  })
})

describe('BaseModal: слои и прокрутка', () => {
  it('вложенное окно лежит выше родителя независимо от порядка в DOM', () => {
    open(Win('outer', Win('inner')))
    const depths = overlays().map((o) => Number(o.style.getPropertyValue('--modal-depth')))
    // Teleport вложенного окна вставляется в body раньше родительского — порядок в DOM обратный, поэтому слой берётся из стека
    const byDialog = Object.fromEntries(
      overlays().map((o) => [o.querySelector('[role="dialog"]')!.getAttribute('aria-label'), Number(o.style.getPropertyValue('--modal-depth'))]),
    )
    expect(byDialog.outer).toBe(0)
    expect(byDialog.inner).toBe(1)
    expect(depths.sort()).toEqual([0, 1])
  })

  it('пока окно открыто, прокрутка страницы заблокирована; после закрытия последнего окна — снята', () => {
    const outer = open(Win('outer'))
    const inner = open(Win('inner'))
    expect(document.body.style.overflow).toBe('hidden')
    inner.unmount()
    mounted.splice(mounted.indexOf(inner), 1)
    expect(document.body.style.overflow).toBe('hidden')
    outer.unmount()
    mounted.splice(mounted.indexOf(outer), 1)
    expect(document.body.style.overflow).toBe('')
  })

  it('после закрытия окна подложка убирается из <body>', () => {
    const wrapper = open(Win('a'))
    wrapper.unmount()
    mounted.pop()
    expect(overlays()).toHaveLength(0)
  })
})
