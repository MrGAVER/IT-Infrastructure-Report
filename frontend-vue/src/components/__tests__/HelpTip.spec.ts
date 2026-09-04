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
})
