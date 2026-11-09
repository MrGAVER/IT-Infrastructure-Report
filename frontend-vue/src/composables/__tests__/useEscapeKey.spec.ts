// UI-04 (ревью 2.158.0): Esc закрывает верхнее из открытых окон — одно, а не все сразу.
// FE-06 (ревью ветки fix/code-review-main-f06-stage2-f05): «верхнее» определяет единый стек окон (modalLayer.ts), а не второй, независимый
// стек Esc, согласованность которого с первым держалась на одинаковом порядке вызовов в setup().
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, type PropType } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { useEscapeKey } from '../modalLayer'
import { useModalStack } from '../modalLayer'

const mounted: VueWrapper[] = []

/** Окно по образцу BaseModal: стоит в общем стеке и по Esc закрывается, если оно верхнее; child — вложенное окно внутри. */
const Modal = defineComponent({
  props: {
    onClose: { type: Function as PropType<() => void>, required: true },
    child: { type: Object as PropType<ReturnType<typeof defineComponent>>, default: null },
  },
  setup(props) {
    const { isTop } = useModalStack()
    useEscapeKey((event) => {
      if (!isTop()) return
      event.preventDefault()
      props.onClose()
    })
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

describe('useEscapeKey', () => {
  it('Esc вызывает обработчик с событием; закрывшее окно помечает событие обработанным', () => {
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
        const { isTop } = useModalStack()
        useEscapeKey((event) => {
          if (!isTop()) return
          event.preventDefault()
          inner()
        })
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

  it('другие клавиши и Esc во время IME-ввода обработчик не вызывают', () => {
    const close = vi.fn()
    open(close)
    press({ key: 'Enter' })
    press({ key: 'a' })
    press({ key: 'Escape', isComposing: true })
    expect(close).not.toHaveBeenCalled()
  })

  it('после размонтирования слушатель снят с window: Esc больше ничего не вызывает', () => {
    const close = vi.fn()
    const remove = vi.spyOn(window, 'removeEventListener')
    const wrapper = open(close)
    wrapper.unmount()
    mounted.pop()
    expect(remove).toHaveBeenCalledWith('keydown', expect.any(Function))
    remove.mockRestore()
    const event = press()
    expect(close).not.toHaveBeenCalled()
    expect(event.defaultPrevented).toBe(false)
  })

  it('слушатель висит на window, а не на document: обработчики на document успевают забрать свой Esc первыми', () => {
    const order: string[] = []
    const close = vi.fn(() => order.push('window'))
    open(close)
    const onDocument = () => order.push('document')
    document.addEventListener('keydown', onDocument)
    press()
    document.removeEventListener('keydown', onDocument)
    expect(order).toEqual(['document', 'window'])
  })
})
