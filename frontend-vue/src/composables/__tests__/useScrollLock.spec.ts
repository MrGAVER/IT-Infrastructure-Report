// F-01 (код-ревью main): при открытом окне страница под подложкой не должна прокручиваться.
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { defineComponent, h, nextTick, Suspense } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { useScrollLock } from '../useScrollLock'

const Win = defineComponent({
  setup() {
    useScrollLock()
    return () => h('div')
  },
})

const mounted: VueWrapper[] = []
const open = () => {
  const wrapper = mount(Win)
  mounted.push(wrapper)
  return wrapper
}

beforeEach(() => {
  document.body.style.cssText = ''
})
afterEach(() => {
  while (mounted.length) mounted.pop()!.unmount()
  document.documentElement.style.cssText = ''
})

describe('useScrollLock', () => {
  it('пока окно открыто, у body overflow: hidden; после закрытия значение возвращается', () => {
    document.body.style.overflow = 'auto'
    const wrapper = open()
    expect(document.body.style.overflow).toBe('hidden')
    wrapper.unmount()
    mounted.pop()
    expect(document.body.style.overflow).toBe('auto')
  })

  it('без собственного overflow у body после закрытия он снова пуст, а не остаётся hidden', () => {
    const wrapper = open()
    wrapper.unmount()
    mounted.pop()
    expect(document.body.style.overflow).toBe('')
  })

  it('вложенные окна: страница отпускается только когда закрылось последнее', () => {
    const outer = open()
    const inner = open()
    inner.unmount()
    mounted.splice(mounted.indexOf(inner), 1)
    expect(document.body.style.overflow).toBe('hidden')
    outer.unmount()
    mounted.splice(mounted.indexOf(outer), 1)
    expect(document.body.style.overflow).toBe('')
  })

  it('внутреннее окно закрывается раньше внешнего или позже — исходный overflow возвращается ровно один раз', () => {
    document.body.style.overflow = 'scroll'
    const outer = open()
    const inner = open()
    outer.unmount()
    mounted.splice(mounted.indexOf(outer), 1)
    expect(document.body.style.overflow).toBe('hidden')
    inner.unmount()
    mounted.splice(mounted.indexOf(inner), 1)
    expect(document.body.style.overflow).toBe('scroll')
  })

  it('исчезающая полоса прокрутки компенсируется отступом справа, чтобы страница позади окна не дёргалась', () => {
    Object.defineProperty(document.documentElement, 'clientWidth', { configurable: true, value: 985 })
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1000 })
    document.body.style.paddingRight = '4px'
    const wrapper = open()
    expect(document.body.style.paddingRight).toBe('19px')
    wrapper.unmount()
    mounted.pop()
    expect(document.body.style.paddingRight).toBe('4px')
    Reflect.deleteProperty(document.documentElement, 'clientWidth')
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 })
  })
})

// FE-06 (ревью ветки fix/code-review-main-f06-stage2-f05): unlock вызывался в onBeforeUnmount безусловно, а lock — в onMounted. Окно,
// которое успело пройти setup(), но так и не смонтировалось (родитель переключил v-if в том же такте, ожидающий Suspense снят), всё
// равно уменьшало счётчик без парного увеличения — и страница отпускалась под ещё открытым вторым окном.
describe('useScrollLock: парность lock/unlock на уровне экземпляра (FE-06)', () => {
  /** Окно, которое никогда не смонтируется: его setup() асинхронный и не завершается, Suspense держит его в ожидании. */
  const NeverMounted = defineComponent({
    async setup() {
      useScrollLock()
      await new Promise<void>(() => {})
      return () => h('div')
    },
  })

  async function openPending() {
    const wrapper = mount({ render: () => h(Suspense, null, { default: () => h(NeverMounted), fallback: () => h('span', 'ожидание') }) })
    await nextTick()
    return wrapper
  }

  it('окно, размонтированное до монтирования, не уменьшает счётчик: страница остаётся заблокированной под другим открытым окном', async () => {
    const first = open() // блокировка 1
    expect(document.body.style.overflow).toBe('hidden')

    const pending = await openPending()
    pending.unmount() // setup() прошёл, onMounted не было — парного lock нет

    expect(document.body.style.overflow).toBe('hidden') // под первым окном страница по-прежнему не прокручивается
    first.unmount()
    mounted.splice(mounted.indexOf(first), 1)
    expect(document.body.style.overflow).toBe('') // и отпускается ровно один раз, когда закрылось последнее окно
  })

  it('обычное окно по-прежнему блокирует и отпускает ровно один раз', () => {
    const wrapper = open()
    expect(document.body.style.overflow).toBe('hidden')
    wrapper.unmount()
    mounted.pop()
    expect(document.body.style.overflow).toBe('')
  })
})
