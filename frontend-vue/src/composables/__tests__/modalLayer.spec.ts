// Раздел 5 ревью (frontend п. 2): useModalLayer — единая точка входа слоя окна. Стороны слоя (стек, Esc, прокрутка, ловушка фокуса,
// закрытие по подложке) проверены каждая своим спеком; здесь — то, чего по отдельности не видно: они подключены вместе и в нужном
// порядке, и окну достаточно одного вызова.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref, type PropType } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { hasOpenModal, useModalLayer, type ModalLayer } from '../modalLayer'

const mounted: VueWrapper[] = []

/** Минимальное окно по образцу BaseModal: подложка с обработчиками слоя, внутри — диалог с кнопкой и, возможно, вложенное окно. */
const Layer = defineComponent({
  props: {
    onClose: { type: Function as PropType<() => void>, default: () => {} },
    onLayer: { type: Function as PropType<(layer: ModalLayer) => void>, default: () => {} },
    child: { type: Object as PropType<ReturnType<typeof defineComponent>>, default: null },
  },
  setup(props) {
    const overlay = ref<HTMLElement | null>(null)
    const layer = useModalLayer({
      dialog: () => overlay.value?.querySelector<HTMLElement>('[role="dialog"]') ?? overlay.value,
      onClose: () => props.onClose(),
    })
    props.onLayer(layer)
    return () =>
      h('div', { ref: overlay, class: 'overlay', onMousedown: layer.onOverlayPointerDown, onClick: layer.onOverlayClick }, [
        h('div', { role: 'dialog', 'aria-label': 'окно' }, [h('button', { type: 'button' }, 'Кнопка'), props.child ? h(props.child) : null]),
      ])
  },
})

function open(props: Record<string, unknown> = {}) {
  const wrapper = mount(Layer, { props, attachTo: document.body })
  mounted.push(wrapper)
  return wrapper
}

function close(wrapper: VueWrapper) {
  wrapper.unmount()
  mounted.splice(mounted.indexOf(wrapper), 1)
}

const pressEscape = () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))

function clickOn(element: Element) {
  element.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
  element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
}

afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount()
  document.body.innerHTML = ''
  document.body.style.cssText = ''
})

describe('useModalLayer: одним вызовом подключены все стороны слоя', () => {
  it('стек, блокировка прокрутки, Esc и закрытие по подложке работают у одного окна; после закрытия всё снято', () => {
    const onClose = vi.fn()
    let layer!: ModalLayer
    expect(hasOpenModal.value).toBe(false)
    const wrapper = open({ onClose, onLayer: (l: ModalLayer) => (layer = l) })

    expect(hasOpenModal.value).toBe(true)
    expect(layer.depth.value).toBe(0)
    expect(layer.isTop()).toBe(true)
    expect(document.body.style.overflow).toBe('hidden')

    pressEscape()
    expect(onClose).toHaveBeenCalledTimes(1)
    clickOn(wrapper.get('.overlay').element)
    expect(onClose).toHaveBeenCalledTimes(2)
    clickOn(wrapper.get('button').element) // клик внутри диалога окно не закрывает
    expect(onClose).toHaveBeenCalledTimes(2)

    close(wrapper)
    expect(hasOpenModal.value).toBe(false)
    expect(document.body.style.overflow).toBe('')
  })

  it('ловушка фокуса подключена: при открытии фокус уходит в диалог, и у диалога есть tabindex', () => {
    const wrapper = open()
    const dialog = wrapper.get('[role="dialog"]').element as HTMLElement
    expect(dialog.getAttribute('tabindex')).toBe('-1')
    expect(document.activeElement).toBe(dialog)
  })

  it('Esc, уже потраченный кем-то другим (defaultPrevented), окно не закрывает', () => {
    const onClose = vi.fn()
    open({ onClose })
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    event.preventDefault()
    window.dispatchEvent(event)
    expect(onClose).not.toHaveBeenCalled()
  })
})

describe('useModalLayer: вложенные окна', () => {
  function nested() {
    const outerClose = vi.fn()
    const innerClose = vi.fn()
    let outer!: ModalLayer
    let inner!: ModalLayer
    const Inner = defineComponent({ render: () => h(Layer, { onClose: innerClose, onLayer: (l: ModalLayer) => (inner = l) }) })
    const wrapper = open({ onClose: outerClose, onLayer: (l: ModalLayer) => (outer = l), child: Inner })
    return { wrapper, outerClose, innerClose, outer: () => outer, inner: () => inner }
  }

  it('окно, вложенное при первом рендере, выше родителя: стек заполняется в setup(), а не в onMounted', () => {
    const { outer, inner } = nested()
    expect(outer().depth.value).toBe(0)
    expect(inner().depth.value).toBe(1)
    expect(inner().isTop()).toBe(true)
    expect(outer().isTop()).toBe(false)
  })

  it('Esc закрывает только верхнее окно: нижнее остаётся с введённым в нём', () => {
    const { outerClose, innerClose } = nested()
    pressEscape()
    expect(innerClose).toHaveBeenCalledTimes(1)
    expect(outerClose).not.toHaveBeenCalled()
  })

  it('страница отпускается, только когда закрылось последнее окно; inert-признак снимается вместе с ним', () => {
    const { wrapper } = nested()
    expect(document.body.style.overflow).toBe('hidden')
    close(wrapper) // закрываются оба: вложенное размонтируется вместе с родителем
    expect(document.body.style.overflow).toBe('')
    expect(hasOpenModal.value).toBe(false)
  })
})

describe('useModalLayer: порядок сторон', () => {
  it('стек снимается раньше возврата фокуса: к моменту opener.focus() AppShell уже может снять inert с фона', () => {
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()
    const seen: boolean[] = []
    vi.spyOn(opener, 'focus').mockImplementation(() => {
      seen.push(hasOpenModal.value)
    })
    const wrapper = open()
    close(wrapper)
    // Фокус вернулся ровно один раз и уже после того, как окно ушло из стека.
    expect(seen).toEqual([false])
  })

  it('открывший окно элемент запоминается до того, как окно забрало фокус: setup() ничего не двигает', () => {
    const opener = document.createElement('button')
    document.body.append(opener)
    opener.focus()
    const wrapper = open()
    expect(document.activeElement).not.toBe(opener)
    close(wrapper)
    expect(document.activeElement).toBe(opener)
  })
})
