import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StructuralUnitTree from '../StructuralUnitTree.vue'
import type { StructuralUnitNode } from '../../stores/catalogs'

const nodes: StructuralUnitNode[] = [
  {
    id: 'root-1',
    name: 'Дирекция ИТ',
    parent_id: null,
    children: [{ id: 'child-1', name: 'Отдел эксплуатации', parent_id: 'root-1', children: [] }],
  },
  { id: 'root-2', name: 'Служба безопасности', parent_id: null, children: [] },
]

describe('StructuralUnitTree.vue', () => {
  it('рекурсивно рендерит вложенные узлы', () => {
    const wrapper = mount(StructuralUnitTree, { props: { nodes, selected: [] } })
    expect(wrapper.text()).toContain('Дирекция ИТ')
    expect(wrapper.text()).toContain('Отдел эксплуатации')
    expect(wrapper.text()).toContain('Служба безопасности')
  })

  it('узел без детей рендерится как leaf-чекбокс без <details>', () => {
    const wrapper = mount(StructuralUnitTree, { props: { nodes, selected: [] } })
    const leafLabels = wrapper.findAll('.leaf')
    // "Служба безопасности" (root-2) и "Отдел эксплуатации" (child-1) — оба листья
    expect(leafLabels).toHaveLength(2)
  })

  it('клик по чекбоксу эмитит toggle с id узла', async () => {
    const wrapper = mount(StructuralUnitTree, { props: { nodes, selected: [] } })
    const rootCheckbox = wrapper.find('summary input[type="checkbox"]')
    await rootCheckbox.trigger('change')

    expect(wrapper.emitted('toggle')).toBeTruthy()
    expect(wrapper.emitted('toggle')![0]).toEqual(['root-1'])
  })

  it('отмечает как checked узлы из props.selected', () => {
    const wrapper = mount(StructuralUnitTree, { props: { nodes, selected: ['child-1'] } })
    const checkboxes = wrapper.findAll('input[type="checkbox"]')
    const childCheckbox = checkboxes.find((c) => c.element.parentElement?.textContent?.includes('Отдел эксплуатации'))
    expect((childCheckbox?.element as HTMLInputElement).checked).toBe(true)
  })
})
