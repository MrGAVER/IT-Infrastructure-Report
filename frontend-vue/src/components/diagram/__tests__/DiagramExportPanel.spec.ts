import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DiagramExportPanel from '../DiagramExportPanel.vue'

describe('DiagramExportPanel.vue', () => {
  it('рендерит три кнопки формата и эмитит export с нужным значением', async () => {
    const wrapper = mount(DiagramExportPanel, { props: { exporting: null } })
    const buttons = wrapper.findAll('button')
    expect(buttons).toHaveLength(3)

    await buttons[1].trigger('click')
    expect(wrapper.emitted('export')?.[0]).toEqual(['vsdx'])
  })

  it('блокирует все кнопки, пока идёт экспорт', () => {
    const wrapper = mount(DiagramExportPanel, { props: { exporting: 'svg' } })
    for (const btn of wrapper.findAll('button')) {
      expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    }
    expect(wrapper.text()).toContain('Экспорт…')
  })
})
