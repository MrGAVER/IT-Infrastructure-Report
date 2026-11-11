// F-01/F-03 (код-ревью main): порядок вложенных окон задаёт стек, а не числа z-index и не порядок в DOM.
import { afterEach, describe, expect, it } from 'vitest'
import { createApp, defineComponent, h, nextTick, ref, toRaw, type PropType } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { hasOpenModal, useModalStack, type ModalStackEntry } from '../modalLayer'

const mounted: VueWrapper[] = []

/** Окно в стеке; child — вложенное окно, которое рисуется внутри (как «+» быстрого добавления внутри формы). */
const Win = defineComponent({
  props: {
    onLayer: { type: Function as PropType<(layer: ModalStackEntry) => void>, required: true },
    child: { type: Object as PropType<ReturnType<typeof defineComponent>>, default: null },
  },
  setup(props) {
    props.onLayer(useModalStack())
    return () => h('div', props.child ? [h(toRaw(props.child))] : [])
  },
})

function open(onLayer: (layer: ModalStackEntry) => void) {
  const wrapper = mount(Win, { props: { onLayer } })
  mounted.push(wrapper)
  return wrapper
}

afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount()
})

describe('useModalStack', () => {
  it('одно окно — нижнее и верхнее одновременно', () => {
    let layer!: ModalStackEntry
    open((l) => (layer = l))
    expect(layer.depth.value).toBe(0)
    expect(layer.isTop()).toBe(true)
  })

  it('окно, открытое позже, выше и единственное верхнее', () => {
    let first!: ModalStackEntry
    let second!: ModalStackEntry
    open((l) => (first = l))
    open((l) => (second = l))
    expect(first.depth.value).toBe(0)
    expect(second.depth.value).toBe(1)
    expect(first.isTop()).toBe(false)
    expect(second.isTop()).toBe(true)
  })

  it('окно, вложенное в другое при первом рендере, оказывается выше родителя: setup родителя идёт раньше, хотя onMounted — позже', () => {
    let outer!: ModalStackEntry
    let inner!: ModalStackEntry
    const Inner = defineComponent({
      setup() {
        inner = useModalStack()
        return () => h('div')
      },
    })
    mounted.push(mount(Win, { props: { onLayer: (l: ModalStackEntry) => (outer = l), child: Inner } }))
    expect(outer.depth.value).toBe(0)
    expect(inner.depth.value).toBe(1)
    expect(inner.isTop()).toBe(true)
    expect(outer.isTop()).toBe(false)
  })

  it('закрытое окно уходит из стека: верхним снова становится нижнее, а глубина оставшихся пересчитывается', async () => {
    let first!: ModalStackEntry
    let second!: ModalStackEntry
    let third!: ModalStackEntry
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
    let first!: ModalStackEntry
    open((l) => (first = l))
    const second = open(() => {})
    expect(first.isTop()).toBe(false)
    second.unmount()
    mounted.splice(mounted.indexOf(second), 1)
    expect(first.isTop()).toBe(true)
  })
})

// FE-03 (ревью ветки fix/code-review-main-f06-stage2-f05): по стеку окон AppShell решает, делать ли фон inert, поэтому «есть
// открытое окно» должно быть реактивным и точным: ложь без окон, истина, пока открыто хоть одно.
describe('hasOpenModal', () => {
  it('без окон — false; пока открыто хоть одно — true; после закрытия последнего снова false', async () => {
    expect(hasOpenModal.value).toBe(false)
    const first = open(() => {})
    expect(hasOpenModal.value).toBe(true)
    const second = open(() => {})
    expect(hasOpenModal.value).toBe(true)

    second.unmount()
    mounted.splice(mounted.indexOf(second), 1)
    expect(hasOpenModal.value).toBe(true) // нижнее окно ещё открыто

    first.unmount()
    mounted.splice(mounted.indexOf(first), 1)
    expect(hasOpenModal.value).toBe(false)
  })

  it('реактивно: computed, зависящий от него, пересчитывается при открытии и закрытии окна', async () => {
    const seen: boolean[] = []
    const { watch } = await import('vue')
    const stop = watch(hasOpenModal, (value) => seen.push(value), { flush: 'sync' })
    const wrapper = open(() => {})
    wrapper.unmount()
    mounted.splice(mounted.indexOf(wrapper), 1)
    stop()
    expect(seen).toEqual([true, false])
  })
})

// R2-05 (ревью merge/review-f06-stage2-f05-executors): гипотеза «если setup() окна бросит после регистрации в стеке, запись останется,
// hasOpenModal станет вечно истинным, а AppShell — inert». Проверено на настоящем Vue: в production (ошибка setup() обработана и
// залогирована, приложение живёт дальше) запись снимается в onBeforeUnmount вместе с экземпляром, ничего не залипает.
// Не покрыто и покрыть нечем: в dev-режиме, когда ошибка setup() пробрасывается из mount(), недостроенное дерево Vue не размонтирует —
// ни onBeforeUnmount, ни onScopeDispose (предложенный в отчёте вариант) там не срабатывают, так что замена хука ничего не даёт.
// VTU mount() пробрасывает ошибки setup() сам, поэтому здесь обычный createApp с errorHandler — как в боевом приложении.
describe('useModalStack: запись не залипает при ошибке в setup() (R2-05)', () => {
  function mountBroken(errors: unknown[]) {
    const Broken = defineComponent({
      setup() {
        useModalStack()
        throw new Error('сбой в setup() после регистрации в стеке')
      },
      render: () => h('div'),
    })
    const present = ref(true)
    const app = createApp({ render: () => h('div', present.value ? [h(Broken)] : []) })
    app.config.errorHandler = (error) => {
      errors.push(error)
    }
    app.mount(document.createElement('div'))
    return { app, present }
  }

  it('сломанное окно, которое родитель убрал (v-if), уходит из стека — фон снова доступен', async () => {
    const errors: unknown[] = []
    const { app, present } = mountBroken(errors)
    expect(errors).toHaveLength(1) // ошибка не потеряна: её получил errorHandler приложения

    present.value = false
    await nextTick()

    expect(hasOpenModal.value).toBe(false)
    app.unmount()
  })

  it('сломанное окно уходит из стека и при размонтировании всего приложения', () => {
    const errors: unknown[] = []
    const { app } = mountBroken(errors)

    app.unmount()

    expect(hasOpenModal.value).toBe(false)
  })

  it('сломанное окно не мешает соседнему исправному: порядок и верхнее окно считаются по живым записям', async () => {
    const errors: unknown[] = []
    const { app, present } = mountBroken(errors)
    let healthy!: ModalStackEntry
    open((l) => (healthy = l))

    present.value = false
    await nextTick()

    expect(healthy.depth.value).toBe(0)
    expect(healthy.isTop()).toBe(true)
    app.unmount()
  })
})
