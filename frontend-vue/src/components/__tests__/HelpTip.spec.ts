import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import HelpTip from '../HelpTip.vue'

describe('HelpTip.vue', () => {
  it('панель с текстом скрыта, пока кнопка "?" не нажата', () => {
    const wrapper = mount(HelpTip, { props: { text: 'Пояснение' }, attachTo: document.body })
    expect(wrapper.find('.help-tip-panel').exists()).toBe(false)
    wrapper.unmount()
  })

  it('клик по кнопке "?" показывает текст, повторный клик скрывает', async () => {
    const wrapper = mount(HelpTip, { props: { text: 'Пояснение по шаблону' }, attachTo: document.body })

    await wrapper.find('.help-tip-btn').trigger('click')
    expect(wrapper.find('.help-tip-panel').text()).toBe('Пояснение по шаблону')

    await wrapper.find('.help-tip-btn').trigger('click')
    expect(wrapper.find('.help-tip-panel').exists()).toBe(false)
    wrapper.unmount()
  })

  it('клик вне компонента закрывает панель', async () => {
    const wrapper = mount(HelpTip, { props: { text: 'Пояснение' }, attachTo: document.body })
    await wrapper.find('.help-tip-btn').trigger('click')
    expect(wrapper.find('.help-tip-panel').exists()).toBe(true)

    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.help-tip-panel').exists()).toBe(false)
    wrapper.unmount()
  })

  it('Escape закрывает панель', async () => {
    const wrapper = mount(HelpTip, { props: { text: 'Пояснение' }, attachTo: document.body })
    await wrapper.find('.help-tip-btn').trigger('click')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.help-tip-panel').exists()).toBe(false)
    wrapper.unmount()
  })

  it('UI-04: Esc при открытой подсказке закрывает её и забирает событие — окно вокруг не закроется', async () => {
    const wrapper = mount(HelpTip, { props: { text: 'Пояснение' }, attachTo: document.body })
    await wrapper.find('.help-tip-btn').trigger('click')

    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    document.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    wrapper.unmount()
  })

  it('UI-04: Esc при закрытой подсказке событие не трогает — оно дойдёт до окна', () => {
    const wrapper = mount(HelpTip, { props: { text: 'Пояснение' }, attachTo: document.body })
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    document.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
    wrapper.unmount()
  })
})
