// UI-04 (ревью 2.158.0): Esc закрывает верхнее из открытых окон — одно, а не все сразу.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, type PropType } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { useEscapeClose } from '../useEscapeClose'
import { useOverlayDismiss } from '../useOverlayDismiss'

const mounted: VueWrapper[] = []

/** Окно, которое закрывается по Esc; child — вложенное окно, рисуемое внутри (как «+» быстрого добавления внутри формы). */
const Modal = defineComponent({
  props: {
    onClose: { type: Function as PropType<() => void>, required: true },
    child: { type: Object as PropType<ReturnType<typeof defineComponent>>, default: null },
  },
  setup(props) {
    useEscapeClose(() => props.onClose())
    return () => h('div', { class: 'modal' }, props.child ? [h(props.child)] : [])
  },
})

function press(init: KeyboardEventInit = { key: 'Escape' }, target: EventTarget = document.body): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init })
  target.dispatchEvent(event)
  return event
}

function open(onClose: () => void) {
  const wrapper = mount(Modal, { props: { onClose }, attachTo: document.body })
  mounted.push(wrapper)
  return wrapper
}

afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount()
})

describe('UI-04: useEscapeClose', () => {
  it('Esc закрывает окно и помечает событие обработанным', () => {
    const close = vi.fn()
    open(close)
    const event = press()
    expect(close).toHaveBeenCalledTimes(1)
    expect(event.defaultPrevented).toBe(true)
  })

  it('из нескольких открытых окон закрывается только последнее открытое', () => {
    const first = vi.fn()
    const second = vi.fn()
    open(first)
    open(second)
    press()
    expect(second).toHaveBeenCalledTimes(1)
    expect(first).not.toHaveBeenCalled()
  })

  it('окно, вложенное в другое, оказывается выше родителя — setup родителя идёт раньше', () => {
    const outer = vi.fn()
    const inner = vi.fn()
    const Inner = defineComponent({
      setup() {
        useEscapeClose(inner)
        return () => h('div', { class: 'inner' })
      },
    })
    const wrapper = mount(Modal, { props: { onClose: outer, child: Inner }, attachTo: document.body })
    mounted.push(wrapper)
    press()
    expect(inner).toHaveBeenCalledTimes(1)
    expect(outer).not.toHaveBeenCalled()
  })

  it('после закрытия верхнего окна следующий Esc закрывает нижнее', () => {
    const first = vi.fn()
    const second = vi.fn()
    open(first)
    const top = open(second)
    top.unmount()
    mounted.splice(mounted.indexOf(top), 1)
    press()
    expect(first).toHaveBeenCalledTimes(1)
  })

  it('Esc, уже обработанный мелким элементом (список выбора, подсказка, меню), окно не закрывает', () => {
    const close = vi.fn()
    open(close)
    const consumer = (event: Event) => event.preventDefault()
    document.addEventListener('keydown', consumer) // как HelpTip: слушатель на document срабатывает раньше window
    press()
    document.removeEventListener('keydown', consumer)
    expect(close).not.toHaveBeenCalled()
  })

  it('другие клавиши и Esc во время IME-ввода окно не закрывают', () => {
    const close = vi.fn()
    open(close)
    press({ key: 'Enter' })
    press({ key: 'a' })
    press({ key: 'Escape', isComposing: true })
    expect(close).not.toHaveBeenCalled()
  })

  it('после размонтирования слушатель снят: Esc больше ничего не вызывает', () => {
    const close = vi.fn()
    const wrapper = open(close)
    wrapper.unmount()
    mounted.pop()
    const remove = vi.spyOn(window, 'removeEventListener')
    const event = press()
    expect(close).not.toHaveBeenCalled()
    expect(event.defaultPrevented).toBe(false)
    remove.mockRestore()
  })
})

describe('UI-04: useOverlayDismiss — Esc закрывает окно тем же действием, что клик по подложке', () => {
  it('Esc вызывает onDismiss; клик по подложке по-прежнему тоже', async () => {
    const dismiss = vi.fn()
    const Dialog = defineComponent({
      setup() {
        const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(dismiss)
        return () => h('div', { class: 'overlay', onMousedown: onOverlayPointerDown, onClick: onOverlayClick })
      },
    })
    const wrapper = mount(Dialog, { attachTo: document.body })
    mounted.push(wrapper)

    press()
    expect(dismiss).toHaveBeenCalledTimes(1)

    await wrapper.trigger('mousedown')
    await wrapper.trigger('click')
    expect(dismiss).toHaveBeenCalledTimes(2)
  })
})
