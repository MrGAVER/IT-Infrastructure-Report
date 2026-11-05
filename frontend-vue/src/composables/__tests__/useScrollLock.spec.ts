// F-01 (код-ревью main): при открытом окне страница под подложкой не должна прокручиваться.
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
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
