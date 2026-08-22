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
})
