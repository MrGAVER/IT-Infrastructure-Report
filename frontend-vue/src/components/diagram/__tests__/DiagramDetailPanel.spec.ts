import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DiagramDetailPanel from '../DiagramDetailPanel.vue'
import type { DiagramSelection } from '../../../stores/diagram'

beforeEach(() => {
  setActivePinia(createPinia()) // компонент читает authStore.canWrite («Развернуть группу» — только запись)
})

describe('DiagramDetailPanel.vue', () => {
  it('не рендерится, если ничего не выделено', () => {
    const wrapper = mount(DiagramDetailPanel, { props: { selection: null } })
    expect(wrapper.find('.detail-panel').exists()).toBe(false)
  })

  it('показывает серийный номер, системное имя и IP-адреса устройства без дублей источников', () => {
    const selection: DiagramSelection = {
      kind: 'node',
      node: {
        id: 'dev-1',
        type: 'device',
        label: 'sw-01',
        serial_number: 'SN-42',
        system_name: 'sw-01',
        category_id: null,
        manufacturer: 'Cisco',
        model: 'Catalyst 2960',
        ip_addresses: [
          { address: '10.0.0.1/24', purpose: 'управление', is_management: true },
          { address: '10.0.0.2/24', purpose: null, is_management: false },
        ],
        icon: {
          mode: 'generated',
          shape: 'switch',
          color: '#4f7cff',
          glyph: 'M1 4h3v4H1z',
          port_ticks: 24,
          manufacturer_label: 'Cisco',
          model_label: 'Catalyst 2960',
        },
        x: 0,
        y: 0,
      },
    }
    const wrapper = mount(DiagramDetailPanel, { props: { selection } })
    expect(wrapper.text()).toContain('SN-42')
    expect(wrapper.text()).toContain('sw-01')
    expect(wrapper.text()).toContain('10.0.0.1/24')
    expect(wrapper.text()).toContain('10.0.0.2/24')
    expect(wrapper.findAll('.badge.mgmt')).toHaveLength(1)
  })

  it('для узла-группы показывает количество устройств и кнопку разворачивания', async () => {
    const selection: DiagramSelection = {
      kind: 'node',
      node: { id: 'group:building:b1', type: 'group', label: 'Здание 1 (23)', device_count: 23, x: 0, y: 0 },
    }
    const wrapper = mount(DiagramDetailPanel, { props: { selection } })
    expect(wrapper.text()).toContain('23')
    await wrapper.find('.expand-btn').trigger('click')
    expect(wrapper.emitted('expand-group')?.[0]).toEqual(['building:b1'])
  })

  it('для ребра показывает порты источника/назначения и список VLAN без дублей', () => {
    const selection: DiagramSelection = {
      kind: 'edge',
      edge: {
        id: 'conn-1',
        source_node_id: 'dev-1',
        source_interface: { id: 'if-1', name: 'Gi0/1' },
        target_node_id: 'dev-2',
        target_interface: { id: 'if-2', name: 'eth0' },
        connection_type: 'Витая пара',
        is_active: true,
        is_trunk: true,
        vlans: [
          { id: 'v1', vlan_id: 10, name: 'data' },
          { id: 'v2', vlan_id: 20, name: 'voice' },
        ],
      },
    }
    const wrapper = mount(DiagramDetailPanel, { props: { selection } })
    expect(wrapper.text()).toContain('Gi0/1')
    expect(wrapper.text()).toContain('eth0')
    expect(wrapper.text()).toContain('VLAN 10')
    expect(wrapper.text()).toContain('VLAN 20')
    expect(wrapper.text()).toContain('активно')
  })

  it('клик по закрытию эмитит close', async () => {
    const selection: DiagramSelection = {
      kind: 'node',
      node: { id: 'group:x', type: 'group', label: 'X (5)', device_count: 5, x: 0, y: 0 },
    }
    const wrapper = mount(DiagramDetailPanel, { props: { selection } })
    await wrapper.find('.panel-head button').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })
})
