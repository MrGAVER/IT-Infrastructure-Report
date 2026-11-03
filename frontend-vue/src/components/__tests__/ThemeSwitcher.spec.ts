import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ThemeSwitcher from '../ThemeSwitcher.vue'
import { useThemeStore, COLOR_SCHEMES } from '../../stores/theme'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

describe('ThemeSwitcher.vue', () => {
  it('рендерит кнопку на каждую цветовую схему', () => {
    const wrapper = mount(ThemeSwitcher)
    const buttons = wrapper.findAll('.swatch-btn')
    expect(buttons).toHaveLength(COLOR_SCHEMES.length)
  })

  it('клик по образцу переключает схему в сторе', async () => {
    const wrapper = mount(ThemeSwitcher)
    const theme = useThemeStore()
    expect(theme.schemeId).toBe('teal')

    const indigoBtn = wrapper.findAll('.swatch-btn')[1]
    await indigoBtn.trigger('click')

    expect(theme.schemeId).toBe('indigo')
    expect(indigoBtn.attributes('aria-pressed')).toBe('true')
  })

  it('в compact-режиме не показывает подписи названий схем', () => {
    const wrapper = mount(ThemeSwitcher, { props: { compact: true } })
    expect(wrapper.find('.swatch-name').exists()).toBe(false)
  })

  it('UI-16: у каждой кнопки есть aria-label с названием схемы — в компактном режиме текста внутри нет', () => {
    const wrapper = mount(ThemeSwitcher, { props: { compact: true } })
    const labels = wrapper.findAll('.swatch-btn').map((b) => b.attributes('aria-label'))
    expect(labels).toEqual(COLOR_SCHEMES.map((scheme) => `Цветовая схема: ${scheme.name}`))
  })

  it('UI-16: выбранная схема различима не только галочкой — aria-pressed есть у каждой кнопки и true только у выбранной', async () => {
    const wrapper = mount(ThemeSwitcher)
    const pressed = () => wrapper.findAll('.swatch-btn').map((b) => b.attributes('aria-pressed'))
    expect(pressed()).toEqual(['true', 'false', 'false'])
    await wrapper.findAll('.swatch-btn')[2].trigger('click')
    expect(pressed()).toEqual(['false', 'false', 'true'])
  })
})
