import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StructuralUnitCrudNode from '../StructuralUnitCrudNode.vue'
import type { StructuralUnitNode } from '../../stores/catalogs'

const node: StructuralUnitNode = {
  id: 'root-1',
  name: 'Дирекция ИТ',
  parent_id: null,
  children: [
    { id: 'child-1', name: 'Отдел эксплуатации', parent_id: 'root-1', children: [] },
  ],
}

describe('StructuralUnitCrudNode.vue', () => {
  it('рекурсивно рендерит узел и его потомков', () => {
    const wrapper = mount(StructuralUnitCrudNode, { props: { node, depth: 0 } })
    expect(wrapper.text()).toContain('Дирекция ИТ')
    expect(wrapper.text()).toContain('Отдел эксплуатации')
  })

  it('эмитит add-child с id узла при клике на "добавить"', async () => {
    const wrapper = mount(StructuralUnitCrudNode, { props: { node, depth: 0 } })
    await wrapper.find('button[aria-label="Добавить дочернюю единицу"]').trigger('click')
    expect(wrapper.emitted('addChild')?.[0]).toEqual(['root-1'])
  })

  it('эмитит edit с самим узлом при клике на "редактировать"', async () => {
    const wrapper = mount(StructuralUnitCrudNode, { props: { node, depth: 0 } })
    await wrapper.find('button[aria-label="Редактировать"]').trigger('click')
    expect(wrapper.emitted('edit')?.[0][0]).toMatchObject({ id: 'root-1' })
  })

  it('событие remove от вложенного потомка всплывает до внешнего слушателя', async () => {
    const wrapper = mount(StructuralUnitCrudNode, { props: { node, depth: 0 } })
    const buttons = wrapper.findAll('button[aria-label="Удалить"]')
    // первая — корень, вторая — вложенный потомок
    await buttons[1].trigger('click')
    expect(wrapper.emitted('remove')?.[0][0]).toMatchObject({ id: 'child-1' })
  })
})
