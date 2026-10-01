import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import PageSizeSelect from '../PageSizeSelect.vue'

describe('PageSizeSelect.vue', () => {
  it('показывает все варианты и выделяет текущий', () => {
    const wrapper = mount(PageSizeSelect, { props: { modelValue: 16, options: [8, 16, 32, 64] } })

    const select = wrapper.find('select')
    expect(wrapper.findAll('option').map((o) => o.text())).toEqual(['8', '16', '32', '64'])
    expect((select.element as HTMLSelectElement).value).toBe('16')
    expect(select.attributes('aria-label')).toBe('Количество строк на странице')
    expect(wrapper.text()).toContain('Показывать по')
  })

  it('при выборе отправляет число, а не строку', async () => {
    const wrapper = mount(PageSizeSelect, { props: { modelValue: 8, options: [8, 16, 32, 64] } })

    await wrapper.find('select').setValue('32')

    expect(wrapper.emitted('update:modelValue')).toEqual([[32]])
  })

  it('значение извне (модель) отражается в селекте', async () => {
    const wrapper = mount(PageSizeSelect, { props: { modelValue: 8, options: [8, 16, 32, 64] } })

    await wrapper.setProps({ modelValue: 64 })

    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('64')
  })
})
