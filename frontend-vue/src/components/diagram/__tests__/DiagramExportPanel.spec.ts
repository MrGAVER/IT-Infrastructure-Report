import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DiagramExportPanel from '../DiagramExportPanel.vue'

describe('DiagramExportPanel.vue', () => {
  it('без lastFormat основная кнопка — первый формат (.drawio), клик сразу экспортирует его', async () => {
    const wrapper = mount(DiagramExportPanel, { props: { exporting: null, lastFormat: null } })
    expect(wrapper.find('.split-btn-main').text()).toContain('.drawio')

    await wrapper.find('.split-btn-main').trigger('click')
    expect(wrapper.emitted('export')?.[0]).toEqual(['drawio'])
  })

  it('с lastFormat основная кнопка показывает именно его, остальные — в выпадающем списке', async () => {
    const wrapper = mount(DiagramExportPanel, { props: { exporting: null, lastFormat: 'vsdx' } })
    expect(wrapper.find('.split-btn-main').text()).toContain('.vsdx')
    expect(wrapper.find('.split-btn-menu').exists()).toBe(false)

    await wrapper.find('.split-btn-toggle').trigger('click')
    const items = wrapper.findAll('.split-btn-menu-item')
    expect(items.map((i) => i.text())).toEqual(['.drawio', '.svg'])
  })

  it('выбор формата из выпадающего списка эмитит export и закрывает список', async () => {
    const wrapper = mount(DiagramExportPanel, { props: { exporting: null, lastFormat: 'vsdx' } })
    await wrapper.find('.split-btn-toggle').trigger('click')
    await wrapper.findAll('.split-btn-menu-item')[0].trigger('click') // .drawio — первый в списке при lastFormat=vsdx

    expect(wrapper.emitted('export')?.[0]).toEqual(['drawio'])
    expect(wrapper.find('.split-btn-menu').exists()).toBe(false)
  })

  it('клик вне компонента закрывает выпадающий список', async () => {
    const wrapper = mount(DiagramExportPanel, { props: { exporting: null, lastFormat: null }, attachTo: document.body })
    await wrapper.find('.split-btn-toggle').trigger('click')
    expect(wrapper.find('.split-btn-menu').exists()).toBe(true)

    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.split-btn-menu').exists()).toBe(false)
    wrapper.unmount()
  })

  it('блокирует обе видимые кнопки, пока идёт экспорт', () => {
    const wrapper = mount(DiagramExportPanel, { props: { exporting: 'svg', lastFormat: null } })
    for (const btn of wrapper.findAll('button')) {
      expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    }
  })

  it('показывает "Экспорт…" на основной кнопке, когда идёт экспорт именно основного формата', () => {
    const wrapper = mount(DiagramExportPanel, { props: { exporting: 'drawio', lastFormat: null } })
    expect(wrapper.find('.split-btn-main').text()).toContain('Экспорт…')
  })
})
