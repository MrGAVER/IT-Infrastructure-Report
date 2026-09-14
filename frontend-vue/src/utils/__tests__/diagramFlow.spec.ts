import { describe, it, expect } from 'vitest'
import { groupKeyOf, isSwitchNode, sourceHandleId, targetHandleId, toFlowEdge, toFlowNode } from '../diagramFlow'
import type { DiagramDeviceNode, DiagramEdge, DiagramGroupNode } from '../../api/diagrams'

function device(overrides: Partial<DiagramDeviceNode> = {}): DiagramDeviceNode {
  return {
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
    x: 10,
    y: 20,
    ...overrides,
  }
}

const group: DiagramGroupNode = { id: 'group:building:b1', type: 'group', label: 'Здание 1 (23)', device_count: 23, x: 0, y: 0 }

describe('groupKeyOf', () => {
  it('снимает префикс group: с id узла-группы', () => {
    expect(groupKeyOf('group:building:b1')).toBe('building:b1')
  })
  it('возвращает id как есть, если префикса нет', () => {
    expect(groupKeyOf('dev-1')).toBe('dev-1')
  })
})

describe('isSwitchNode', () => {
  it('true только для устройства с сгенерированной иконкой shape=switch', () => {
    const nodes = [device({ id: 'sw', icon: { mode: 'generated', shape: 'switch', color: '#fff', manufacturer_label: '', model_label: '' } })]
    expect(isSwitchNode(nodes, 'sw')).toBe(true)
  })
  it('false для другой формы, custom-иконки, узла-группы и отсутствующего узла', () => {
    const nodes = [
      device({ id: 'srv' }), // shape=server
      device({ id: 'custom', icon: { mode: 'custom', svg_markup: '<svg/>' } }),
      group,
    ]
    expect(isSwitchNode(nodes, 'srv')).toBe(false)
    expect(isSwitchNode(nodes, 'custom')).toBe(false)
    expect(isSwitchNode(nodes, 'group:building:b1')).toBe(false)
    expect(isSwitchNode(nodes, 'unknown')).toBe(false)
  })
})

describe('sourceHandleId / targetHandleId', () => {
  const switchNode = device({ id: 'sw', icon: { mode: 'generated', shape: 'switch', color: '#fff', manufacturer_label: '', model_label: '' } })
  const serverNode = device({ id: 'srv' })
  const nodes = [switchNode, serverNode]

  it('для switch-узла с известным port_index даёт id засечки', () => {
    const edge: DiagramEdge = {
      id: 'e1',
      source_node_id: 'sw',
      source_interface: { id: 'if-1', name: 'Gi0/1', port_index: 3 },
      target_node_id: 'srv',
      target_interface: { id: 'if-2', name: 'eth0' },
      connection_type: null,
      is_active: true,
      vlans: [],
    }
    expect(sourceHandleId(nodes, edge)).toBe('port-3-source')
    expect(targetHandleId(nodes, edge)).toBeUndefined() // srv не switch — дефолтный Handle узла
  })

  it('для switch-узла БЕЗ port_index (интерфейс за пределами 32 портов) не анкерит к засечке', () => {
    const edge: DiagramEdge = {
      id: 'e2',
      source_node_id: 'sw',
      source_interface: { id: 'if-40', name: 'Gi0/40' },
      target_node_id: 'srv',
      target_interface: null,
      connection_type: null,
      is_active: true,
      vlans: [],
    }
    expect(sourceHandleId(nodes, edge)).toBeUndefined()
  })
})

describe('toFlowNode', () => {
  it('переносит id/позицию/тип и кладёт исходные данные узла в data', () => {
    const d = device()
    const flow = toFlowNode(d)
    expect(flow).toEqual({ id: 'dev-1', type: 'device', position: { x: 10, y: 20 }, data: d, draggable: true })
  })
})

describe('toFlowEdge', () => {
  const switchNode = device({ id: 'sw', icon: { mode: 'generated', shape: 'switch', color: '#fff', manufacturer_label: '', model_label: '' } })
  const serverNode = device({ id: 'srv' })
  const nodes = [switchNode, serverNode]

  it('формирует подпись из VLAN и штриховку для неактивной связи', () => {
    const edge: DiagramEdge = {
      id: 'e1',
      source_node_id: 'sw',
      source_interface: { id: 'if-1', name: 'Gi0/1', port_index: 0 },
      target_node_id: 'srv',
      target_interface: { id: 'if-2', name: 'eth0' },
      connection_type: 'Витая пара',
      is_active: false,
      vlans: [{ id: 'v1', vlan_id: 10, name: 'data' }],
    }
    const flow = toFlowEdge(nodes, edge)
    expect(flow.source).toBe('sw')
    expect(flow.target).toBe('srv')
    expect(flow.sourceHandle).toBe('port-0-source')
    expect(flow.label).toBe('VLAN 10')
    expect(flow.style).toEqual({ strokeDasharray: '6 4' })
    expect(flow.data).toBe(edge)
  })

  it('без VLAN подпись не задаётся, активная связь — без штриховки', () => {
    const edge: DiagramEdge = {
      id: 'e2',
      source_node_id: 'sw',
      source_interface: null,
      target_node_id: 'srv',
      target_interface: null,
      connection_type: null,
      is_active: true,
      vlans: [],
    }
    const flow = toFlowEdge(nodes, edge)
    expect(flow.label).toBeUndefined()
    expect(flow.style).toBeUndefined()
  })
})
