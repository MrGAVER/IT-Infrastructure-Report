import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DiagramGroupNode from '../DiagramGroupNode.vue'
import type { DiagramGroupNode as GroupNodeData } from '../../../api/diagrams'
import { makeNodeProps } from './nodeTestHelpers'

const stubs = { Handle: true }

describe('DiagramGroupNode.vue', () => {
  it('показывает метку и количество устройств', () => {
    const data: GroupNodeData = { id: 'group:building:b1', type: 'group', label: 'Здание 1 (23)', device_count: 23, x: 0, y: 0 }
    const wrapper = mount(DiagramGroupNode, { props: makeNodeProps(data), global: { stubs } })
    expect(wrapper.text()).toContain('Здание 1 (23)')
  })

  it('выделенный узел получает класс selected', () => {
    const data: GroupNodeData = { id: 'group:x', type: 'group', label: 'X (5)', device_count: 5, x: 0, y: 0 }
    const wrapper = mount(DiagramGroupNode, { props: makeNodeProps(data, { selected: true }), global: { stubs } })
    expect(wrapper.find('.diagram-group-node').classes()).toContain('selected')
  })
})
