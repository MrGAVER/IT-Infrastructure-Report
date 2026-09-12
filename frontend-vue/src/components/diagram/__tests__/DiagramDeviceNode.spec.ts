import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DiagramDeviceNode from '../DiagramDeviceNode.vue'
import type { DiagramDeviceNode as DeviceNodeData } from '../../../api/diagrams'
import { makeNodeProps } from './nodeTestHelpers'

// Handle из @vue-flow/core требует полноценный контекст родителя <VueFlow> (внутренний стор
// размеров/позиций), а сам по себе не несёт данных, которые эти тесты проверяют (форма/цвет/
// засечки/подписи) — стаб позволяет монтировать компонент узла напрямую по props, не поднимая
// ResizeObserver/getBoundingClientRect-заглушки ради полноценного канваса (это отдельно
// проверяется на уровне DiagramView.vue, где Handle учитывается по факту наличия/id).
const stubs = { Handle: true }

const baseDevice: DeviceNodeData = {
  id: 'dev-1',
  type: 'device',
  label: 'sw-01',
  serial_number: 'SN-1',
  system_name: 'sw-01',
  category_id: null,
  manufacturer: null,
  model: null,
  ip_addresses: [],
  icon: { mode: 'generated', shape: 'server', color: '#4f7cff', manufacturer_label: '', model_label: '' },
  x: 0,
  y: 0,
}

function mountNode(data: DeviceNodeData, selected = false) {
  return mount(DiagramDeviceNode, {
    props: makeNodeProps(data, { selected }),
    global: { stubs },
  })
}

describe('DiagramDeviceNode.vue', () => {
  it('показывает подпись устройства и не рисует засечки для не-switch формы', () => {
    const wrapper = mountNode(baseDevice)
    expect(wrapper.text()).toContain('sw-01')
    expect(wrapper.find('.port-ticks').exists()).toBe(false)
  })

  it('для shape=switch рисует засечки портов по числу port_ticks и бейдж overflow', () => {
    const switchDevice: DeviceNodeData = {
      ...baseDevice,
      icon: { mode: 'generated', shape: 'switch', color: '#4f7cff', port_ticks: 5, port_overflow: 12, manufacturer_label: 'Cisco', model_label: 'C2960' },
    }
    const wrapper = mountNode(switchDevice)
    expect(wrapper.findAll('.port-tick')).toHaveLength(5)
    expect(wrapper.text()).toContain('+12')
    expect(wrapper.text()).toContain('Cisco')
  })

  it('иконка mode=custom встраивает svg_markup как есть', () => {
    const customDevice: DeviceNodeData = { ...baseDevice, icon: { mode: 'custom', svg_markup: '<circle r="4" class="mark"/>' } }
    const wrapper = mountNode(customDevice)
    expect(wrapper.find('.custom-icon .mark').exists()).toBe(true)
  })

  it('порог в 32 засечки не превышается даже при большем port_ticks в данных', () => {
    const overflowingDevice: DeviceNodeData = {
      ...baseDevice,
      icon: { mode: 'generated', shape: 'switch', color: '#4f7cff', port_ticks: 40, manufacturer_label: '', model_label: '' },
    }
    const wrapper = mountNode(overflowingDevice)
    expect(wrapper.findAll('.port-tick')).toHaveLength(32)
  })

  it('выделенный узел получает класс selected', () => {
    const wrapper = mountNode(baseDevice, true)
    expect(wrapper.find('.diagram-device-node').classes()).toContain('selected')
  })
})
