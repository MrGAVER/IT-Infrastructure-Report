// F-01 (код-ревью main, WCAG 2.4.3 / 2.1.2): после открытия окна фокус внутри него, Tab и Shift+Tab из окна не выходят,
// после закрытия фокус возвращается на кнопку, открывшую окно, а из вложенных окон реагирует только верхнее.
// jsdom не двигает фокус по Tab сам, поэтому проверяется то, что делает ловушка: перехваченное событие (defaultPrevented) и
// элемент, на который она переставила фокус.
import { afterEach, describe, expect, it } from 'vitest'
import { defineComponent, h, ref, type PropType, type VNode } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { useModalStack } from '../modalLayer'
import { useFocusTrap } from '../useFocusTrap'

const mounted: VueWrapper[] = []
const openers: HTMLElement[] = []

/** Окно: подложка с диалогом внутри; child — вложенное окно внутри диалога (как «+» быстрого добавления в форме устройства). */
const Win = defineComponent({
  props: {
    name: { type: String, default: 'win' },
    child: { type: Object as PropType<ReturnType<typeof defineComponent>>, default: null },
    extra: { type: Function as PropType<() => VNode[]>, default: () => [] },
  },
  setup(props) {
    const dialog = ref<HTMLElement | null>(null)
    const { isTop } = useModalStack()
    useFocusTrap(dialog, isTop)
    return () =>
      h('div', { class: 'overlay' }, [
        h('div', { ref: dialog, role: 'dialog', 'data-name': props.name }, [
          h('button', { id: `${props.name}-first` }, 'Закрыть'),
          h('input', { id: `${props.name}-field` }),
          ...props.extra(),
          h('button', { id: `${props.name}-last` }, 'Сохранить'),
          props.child ? h(props.child) : null,
        ]),
      ])
  },
})

/** Кнопка, открывшая окно: в фокусе к моменту монтирования. */
function opener(id = 'opener'): HTMLButtonElement {
  const button = document.createElement('button')
  button.id = id
  document.body.appendChild(button)
  button.focus()
  openers.push(button)
  return button
}

function open(props: Record<string, unknown> = {}) {
  const wrapper = mount(Win, { props, attachTo: document.body })
  mounted.push(wrapper)
  return wrapper
}

/** Кто в фокусе — строкой: при падении сравнения DOM-узлов с внутренностями Vue vitest печатает гигантский дифф и подвисает. */
function active(): string {
  const el = document.activeElement
  if (!el) return 'none'
  if (el.getAttribute('role') === 'dialog') return `dialog:${el.getAttribute('data-name') ?? ''}`
  return el.id || el.tagName
}

function byId(id: string): HTMLElement {
  return document.getElementById(id)!
}

function tab(init: KeyboardEventInit = {}): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true, ...init })
  ;(document.activeElement ?? document.body).dispatchEvent(event)
  return event
}

afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount()
  while (openers.length) openers.pop()!.remove()
})

describe('useFocusTrap: при открытии', () => {
  it('фокус уходит с кнопки-открывателя внутрь окна — на сам диалог, который становится фокусируемым программно (tabindex="-1")', () => {
    opener()
    open()
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!
    expect(active()).toBe('dialog:win')
    expect(dialog.getAttribute('tabindex')).toBe('-1')
  })

  it('элемент с autofocus получает фокус, а не диалог', () => {
    opener()
    open({ extra: () => [h('input', { id: 'name', autofocus: true })] })
    expect(active()).toBe('name')
  })

  it('отключённый autofocus-элемент пропускается — фокус на диалоге', () => {
    opener()
    open({ extra: () => [h('input', { id: 'name', autofocus: true, disabled: true })] })
    expect(active()).toBe('dialog:win')
  })

  it('фокус, уже занятый дочерним компонентом, не отбирается', () => {
    opener()
    const Child = defineComponent({
      mounted() {
        ;(this.$el as HTMLElement).focus()
      },
      render: () => h('input', { id: 'child-input' }),
    })
    open({ child: Child })
    expect(active()).toBe('child-input')
  })
})

describe('useFocusTrap: Tab и Shift+Tab', () => {
  it('Tab с последнего элемента переходит на первый', () => {
    opener()
    open()
    byId('win-last').focus()
    const event = tab()
    expect(event.defaultPrevented).toBe(true)
    expect(active()).toBe('win-first')
  })

  it('Shift+Tab с первого элемента переходит на последний', () => {
    opener()
    open()
    byId('win-first').focus()
    const event = tab({ shiftKey: true })
    expect(event.defaultPrevented).toBe(true)
    expect(active()).toBe('win-last')
  })

  it('Shift+Tab с самого диалога (фокус при открытии) тоже уходит на последний, а не на страницу под окном', () => {
    opener()
    open()
    const event = tab({ shiftKey: true })
    expect(event.defaultPrevented).toBe(true)
    expect(active()).toBe('win-last')
  })

  it('Tab с диалога и Tab из середины окна не перехватываются — дальше работает обычный порядок браузера', () => {
    opener()
    open()
    expect(tab().defaultPrevented).toBe(false)
    byId('win-field').focus()
    expect(tab().defaultPrevented).toBe(false)
    expect(tab({ shiftKey: true }).defaultPrevented).toBe(false)
  })

  it('фокус вне окна (клик по подложке уводит его на body): Tab возвращает его внутрь, Shift+Tab — на последний элемент', () => {
    const outside = opener('outside')
    open()
    outside.focus()
    expect(tab().defaultPrevented).toBe(true)
    expect(active()).toBe('win-first')

    outside.focus()
    expect(tab({ shiftKey: true }).defaultPrevented).toBe(true)
    expect(active()).toBe('win-last')
  })

  it('отключённые и скрытые элементы границами окна не считаются', () => {
    opener()
    open({ extra: () => [h('button', { id: 'off', disabled: true }), h('button', { id: 'gone', hidden: true })] })
    byId('win-last').focus()
    tab()
    expect(active()).toBe('win-first')
  })

  it('невыбранная радиокнопка группы не граница окна: Tab останавливается только на выбранной', () => {
    opener()
    open({
      extra: () => [h('input', { id: 'r1', type: 'radio', name: 'mode', checked: true }), h('input', { id: 'r2', type: 'radio', name: 'mode' })],
    })
    byId('win-last').focus()
    tab()
    expect(active()).toBe('win-first')
  })

  it('окно без единого фокусируемого элемента: Tab никуда не уводит и оставляет фокус на диалоге', () => {
    opener()
    const Bare = defineComponent({
      setup() {
        const dialog = ref<HTMLElement | null>(null)
        const { isTop } = useModalStack()
        useFocusTrap(dialog, isTop)
        return () => h('div', { ref: dialog, role: 'dialog' }, 'Только текст')
      },
    })
    mounted.push(mount(Bare, { attachTo: document.body }))
    const event = tab()
    expect(event.defaultPrevented).toBe(true)
    expect(active()).toBe('dialog:')
  })

  it('другие клавиши и уже обработанный Tab игнорируются', () => {
    opener()
    open()
    byId('win-last').focus()
    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    document.activeElement!.dispatchEvent(enter)
    expect(active()).toBe('win-last')

    byId('win-last').addEventListener('keydown', (e) => e.preventDefault())
    tab()
    expect(active()).toBe('win-last')
  })
})

describe('useFocusTrap: вложенные окна', () => {
  const Inner = defineComponent({
    render: () => h(Win, { name: 'inner' }),
  })

  it('Tab перехватывает только верхнее окно: цикл идёт внутри вложенного, а не внешнего', () => {
    opener()
    open({ child: Inner })
    // вложенное окно монтируется первым (его onMounted идёт раньше родительского) и забирает фокус — верхнее окно остаётся верхним
    expect(active()).toBe('dialog:inner')

    byId('inner-last').focus()
    tab()
    expect(active()).toBe('inner-first')

    // фокус остался в нижнем окне: ловушка верхнего возвращает его внутрь себя, а нижняя на Tab не реагирует
    byId('win-last').focus()
    expect(tab().defaultPrevented).toBe(true)
    expect(active()).toBe('inner-first')
  })

  it('после закрытия вложенного окна верхним снова становится внешнее', async () => {
    opener()
    const wrapper = open({ child: Inner })
    await wrapper.setProps({ child: null })
    byId('win-last').focus()
    tab()
    expect(active()).toBe('win-first')
  })
})

describe('useFocusTrap: при закрытии', () => {
  it('фокус возвращается на кнопку, открывшую окно', () => {
    opener()
    const wrapper = open()
    expect(active()).not.toBe('opener')
    wrapper.unmount()
    mounted.pop()
    expect(active()).toBe('opener')
  })

  it('если кнопки уже нет в документе, фокус не падает с ошибкой и остаётся на body', () => {
    const button = opener()
    const wrapper = open()
    button.remove()
    expect(() => wrapper.unmount()).not.toThrow()
    mounted.pop()
    expect(active()).toBe('BODY')
  })

  it('слушатель Tab снимается: после закрытия окно ничего не перехватывает', () => {
    opener()
    const wrapper = open()
    wrapper.unmount()
    mounted.pop()
    opener('probe')
    expect(tab().defaultPrevented).toBe(false)
    expect(active()).toBe('probe')
  })

  it('закрылись сразу оба окна — фокус на кнопке под нижним, а не на кнопке во внешнем окне, которого уже нет', async () => {
    opener('base')
    const Inner = defineComponent({ render: () => h(Win, { name: 'inner' }) })
    const wrapper = open()
    // вложенное окно открывается кнопкой внутри внешнего: это и есть его «открыватель»
    byId('win-first').focus()
    await wrapper.setProps({ child: Inner })
    expect(active()).toBe('dialog:inner')

    wrapper.unmount()
    mounted.pop()
    expect(active()).toBe('base')
  })

  it('закрылось только вложенное окно — фокус на кнопке внешнего окна, открывшей его', async () => {
    opener('base')
    const Inner = defineComponent({ render: () => h(Win, { name: 'inner' }) })
    const wrapper = open()
    byId('win-field').focus()
    await wrapper.setProps({ child: Inner })
    await wrapper.setProps({ child: null })
    expect(active()).toBe('win-field')
  })
})
