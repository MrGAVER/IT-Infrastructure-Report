import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, DOMWrapper } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { vTruncateTooltip } from '../truncateTooltip'

/** Подсказка создаётся через document.body.appendChild, а не в дереве компонента. */
function popup(): DOMWrapper<HTMLElement> | null {
  const el = document.querySelector<HTMLElement>('.truncate-tooltip-popup')
  return el ? new DOMWrapper(el) : null
}

/** jsdom не считает layout — scrollWidth/clientWidth всегда 0/0 по умолчанию, поэтому
 * "обрезанность" нужно проставлять вручную под каждый сценарий теста. */
function setOverflow(target: Element, overflowing: boolean) {
  const el = target as HTMLElement
  Object.defineProperty(el, 'scrollWidth', { value: overflowing ? 300 : 100, configurable: true })
  Object.defineProperty(el, 'clientWidth', { value: 100, configurable: true })
  Object.defineProperty(el, 'scrollHeight', { value: 20, configurable: true })
  Object.defineProperty(el, 'clientHeight', { value: 20, configurable: true })
}

const TestCell = defineComponent({
  directives: { truncateTooltip: vTruncateTooltip },
  props: { text: { type: String, default: 'Очень длинный текст ячейки' }, explicitValue: { type: String, default: undefined } },
  template: `<span class="cell" v-truncate-tooltip="explicitValue">{{ text }}</span>`,
})

beforeEach(() => {
  vi.useFakeTimers()
  document.body.innerHTML = ''
})
afterEach(() => {
  vi.useRealTimers()
})

describe('v-truncate-tooltip (п.3)', () => {
  it('текст не обрезан — подсказка не появляется даже после задержки и наведения', async () => {
    const wrapper = mount(TestCell, { attachTo: document.body })
    setOverflow(wrapper.find('.cell').element, false)

    await wrapper.find('.cell').trigger('mouseenter')
    vi.advanceTimersByTime(1500)

    expect(popup()).toBeNull()
    wrapper.unmount()
  })

  it('текст обрезан — подсказка появляется не раньше чем через секунду после наведения', async () => {
    const wrapper = mount(TestCell, { attachTo: document.body })
    setOverflow(wrapper.find('.cell').element, true)

    await wrapper.find('.cell').trigger('mouseenter')
    vi.advanceTimersByTime(600)
    expect(popup()).toBeNull() // ещё рано

    vi.advanceTimersByTime(500) // итого 1100мс
    expect(popup()?.text()).toBe('Очень длинный текст ячейки')
    wrapper.unmount()
  })

  it('уход курсора до истечения секунды отменяет показ', async () => {
    const wrapper = mount(TestCell, { attachTo: document.body })
    setOverflow(wrapper.find('.cell').element, true)

    await wrapper.find('.cell').trigger('mouseenter')
    vi.advanceTimersByTime(400)
    await wrapper.find('.cell').trigger('mouseleave')
    vi.advanceTimersByTime(1000)

    expect(popup()).toBeNull()
    wrapper.unmount()
  })

  it('клик по элементу прячет уже показанную подсказку', async () => {
    const wrapper = mount(TestCell, { attachTo: document.body })
    setOverflow(wrapper.find('.cell').element, true)

    await wrapper.find('.cell').trigger('mouseenter')
    vi.advanceTimersByTime(1000)
    expect(popup()).not.toBeNull()

    await wrapper.find('.cell').trigger('click')
    expect(popup()).toBeNull()
    wrapper.unmount()
  })

  it('явное значение директивы показывается вместо textContent элемента', async () => {
    const wrapper = mount(TestCell, { props: { text: 'кратко', explicitValue: 'Полное пояснение, отличное от видимого текста' }, attachTo: document.body })
    setOverflow(wrapper.find('.cell').element, true)

    await wrapper.find('.cell').trigger('mouseenter')
    vi.advanceTimersByTime(1000)

    expect(popup()?.text()).toBe('Полное пояснение, отличное от видимого текста')
    wrapper.unmount()
  })

  it('размонтирование компонента убирает уже показанную подсказку и не оставляет висящий таймер', async () => {
    const wrapper = mount(TestCell, { attachTo: document.body })
    setOverflow(wrapper.find('.cell').element, true)

    await wrapper.find('.cell').trigger('mouseenter')
    vi.advanceTimersByTime(1000)
    expect(popup()).not.toBeNull()

    wrapper.unmount()
    expect(popup()).toBeNull()
    expect(() => vi.advanceTimersByTime(5000)).not.toThrow() // нет утёкшего setTimeout, ссылающегося на удалённый el
  })

  it('обновление текста реактивным пропом обновляет уже показанную подсказку', async () => {
    const text = ref('Первое длинное значение ячейки')
    const wrapper = mount(TestCell, { props: { text: text.value }, attachTo: document.body })
    setOverflow(wrapper.find('.cell').element, true)

    await wrapper.find('.cell').trigger('mouseenter')
    vi.advanceTimersByTime(1000)
    expect(popup()?.text()).toBe('Первое длинное значение ячейки')

    await wrapper.setProps({ text: 'Второе значение после обновления' })
    expect(popup()?.text()).toBe('Второе значение после обновления')
    wrapper.unmount()
  })
})
