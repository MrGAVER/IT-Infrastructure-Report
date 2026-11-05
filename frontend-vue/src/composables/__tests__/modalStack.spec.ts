// F-01/F-03 (код-ревью main): порядок вложенных окон задаёт стек, а не числа z-index и не порядок в DOM.
import { afterEach, describe, expect, it } from 'vitest'
import { defineComponent, h, nextTick, type PropType } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { useModalStack, type ModalLayer } from '../modalStack'

const mounted: VueWrapper[] = []

/** Окно в стеке; child — вложенное окно, которое рисуется внутри (как «+» быстрого добавления внутри формы). */
const Win = defineComponent({
  props: {
    onLayer: { type: Function as PropType<(layer: ModalLayer) => void>, required: true },
    child: { type: Object as PropType<ReturnType<typeof defineComponent>>, default: null },
  },
  setup(props) {
    props.onLayer(useModalStack())
    return () => h('div', props.child ? [h(props.child)] : [])
  },
})

function open(onLayer: (layer: ModalLayer) => void) {
  const wrapper = mount(Win, { props: { onLayer } })
  mounted.push(wrapper)
  return wrapper
}

afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount()
})

describe('useModalStack', () => {
  it('одно окно — нижнее и верхнее одновременно', () => {
    let layer!: ModalLayer
    open((l) => (layer = l))
    expect(layer.depth.value).toBe(0)
    expect(layer.isTop()).toBe(true)
  })

  it('окно, открытое позже, выше и единственное верхнее', () => {
    let first!: ModalLayer
    let second!: ModalLayer
    open((l) => (first = l))
    open((l) => (second = l))
    expect(first.depth.value).toBe(0)
    expect(second.depth.value).toBe(1)
    expect(first.isTop()).toBe(false)
    expect(second.isTop()).toBe(true)
  })

  it('окно, вложенное в другое при первом рендере, оказывается выше родителя: setup родителя идёт раньше, хотя onMounted — позже', () => {
    let outer!: ModalLayer
    let inner!: ModalLayer
    const Inner = defineComponent({
      setup() {
        inner = useModalStack()
        return () => h('div')
      },
    })
    mounted.push(mount(Win, { props: { onLayer: (l: ModalLayer) => (outer = l), child: Inner } }))
    expect(outer.depth.value).toBe(0)
    expect(inner.depth.value).toBe(1)
    expect(inner.isTop()).toBe(true)
    expect(outer.isTop()).toBe(false)
  })

  it('закрытое окно уходит из стека: верхним снова становится нижнее, а глубина оставшихся пересчитывается', async () => {
    let first!: ModalLayer
    let second!: ModalLayer
    let third!: ModalLayer
    const a = open((l) => (first = l))
    open((l) => (second = l))
    open((l) => (third = l))
    expect(third.depth.value).toBe(2)

    a.unmount()
    mounted.splice(mounted.indexOf(a), 1)
    await nextTick()
    expect(second.depth.value).toBe(0)
    expect(third.depth.value).toBe(1)
    expect(third.isTop()).toBe(true)
    expect(first.isTop()).toBe(false)
  })

  it('после закрытия верхнего окна верхним снова становится окно под ним', () => {
    let first!: ModalLayer
    open((l) => (first = l))
    const second = open(() => {})
    expect(first.isTop()).toBe(false)
    second.unmount()
    mounted.splice(mounted.indexOf(second), 1)
    expect(first.isTop()).toBe(true)
  })
})
