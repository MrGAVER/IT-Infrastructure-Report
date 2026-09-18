import { describe, it, expect } from 'vitest'
import { Position } from '@vue-flow/core'
import {
  CONNECTION_EDGE_TYPE,
  edgeAngleDeg,
  edgeBaseStyle,
  edgeIsRelatedToHover,
  edgeMidLabel,
  edgeSourcePortLabel,
  edgeTargetPortLabel,
  groupKeyOf,
  offsetAlongHandle,
  sourceHandleId,
  targetHandleId,
  toFlowEdge,
  toFlowNode,
} from '../diagramFlow'
import type { DiagramDeviceNode, DiagramEdge } from '../../api/diagrams'

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

function edge(overrides: Partial<DiagramEdge> = {}): DiagramEdge {
  return {
    id: 'e1',
    source_node_id: 'sw',
    source_interface: { id: 'if-1', name: 'Gi0/1', port_index: 0 },
    target_node_id: 'srv',
    target_interface: { id: 'if-2', name: 'eth0', port_index: 0 },
    connection_type: 'Витая пара',
    is_active: true,
    vlans: [],
    ...overrides,
  }
}

describe('groupKeyOf', () => {
  it('снимает префикс group: с id узла-группы', () => {
    expect(groupKeyOf('group:building:b1')).toBe('building:b1')
  })
  it('возвращает id как есть, если префикса нет', () => {
    expect(groupKeyOf('dev-1')).toBe('dev-1')
  })
})

describe('sourceHandleId / targetHandleId', () => {
  // Контракт (см. backend/app/services/diagram_graph.py:GraphContext.device_supports_port_index)
  // гарантирует, что port_index присутствует, только когда его безопасно использовать как id
  // Handle — фронтенду достаточно просто прочитать поле, без повторной проверки формы/группы.
  it('с известным port_index даёт id засечки — независимо от формы устройства', () => {
    const e = edge({ source_interface: { id: 'if-1', name: 'Gi0/1', port_index: 3 } })
    expect(sourceHandleId(e)).toBe('port-3-source')
  })

  it('без port_index (custom-значок, свёрнутая группа или порт за пределами 32) не анкерит к засечке', () => {
    const e = edge({ source_interface: { id: 'if-1', name: 'Gi0/1' }, target_interface: null })
    expect(sourceHandleId(e)).toBeUndefined()
    expect(targetHandleId(e)).toBeUndefined()
  })
})

describe('edgeMidLabel', () => {
  it('есть VLAN — их список', () => {
    const e = edge({ vlans: [{ id: 'v1', vlan_id: 10, name: 'data' }] })
    expect(edgeMidLabel(e)).toBe('VLAN 10')
  })

  it('несколько VLAN — перечисляются через запятую', () => {
    const e = edge({
      vlans: [
        { id: 'v1', vlan_id: 10, name: 'data' },
        { id: 'v2', vlan_id: 20, name: 'voice' },
      ],
    })
    expect(edgeMidLabel(e)).toBe('VLAN 10, 20')
  })

  it('без VLAN — undefined (подпись не рисуется), даже если оба порта известны', () => {
    // Регрессия (пункт 3 правки "диаграмма топологии сети"): раньше сюда же дублировались
    // имена портов ("Gi0/1 ↔ eth0") — та же информация уже показывается отдельно у каждого
    // конца линии (edgeSourcePortLabel/edgeTargetPortLabel), дублирование лишь усиливало
    // наложение подписей друг на друга на плотных диаграммах.
    expect(edgeMidLabel(edge({ vlans: [] }))).toBeUndefined()
  })
})

describe('edgeSourcePortLabel / edgeTargetPortLabel', () => {
  it('возвращают имя интерфейса своей стороны', () => {
    const e = edge()
    expect(edgeSourcePortLabel(e)).toBe('Gi0/1')
    expect(edgeTargetPortLabel(e)).toBe('eth0')
  })

  it('undefined, если интерфейс этой стороны неизвестен', () => {
    const e = edge({ target_interface: null })
    expect(edgeTargetPortLabel(e)).toBeUndefined()
  })
})

describe('offsetAlongHandle', () => {
  it.each([
    [Position.Top, { x: 100, y: 86 }],
    [Position.Bottom, { x: 100, y: 114 }],
    [Position.Left, { x: 86, y: 100 }],
    [Position.Right, { x: 114, y: 100 }],
  ])('сдвигает точку на 14px наружу от узла для позиции %s', (position, expected) => {
    expect(offsetAlongHandle(100, 100, position)).toEqual(expected)
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
  it('анкерит оба конца по port_index, помечает как кастомный тип ребра, штрихует неактивную связь', () => {
    const e = edge({ is_active: false })
    const flow = toFlowEdge(e)
    expect(flow.type).toBe(CONNECTION_EDGE_TYPE)
    expect(flow.source).toBe('sw')
    expect(flow.target).toBe('srv')
    expect(flow.sourceHandle).toBe('port-0-source')
    expect(flow.targetHandle).toBe('port-0-target')
    expect(flow.style).toEqual({ strokeDasharray: '6 4' })
    expect(flow.data).toBe(e)
  })

  it('активная связь — без штриховки; подписи не кладутся в сам объект ребра (их рисует DiagramConnectionEdge из data)', () => {
    const e = edge({ source_interface: null, target_interface: null })
    const flow = toFlowEdge(e)
    expect(flow.style).toBeUndefined()
    expect(flow.label).toBeUndefined()
    expect(flow.sourceHandle).toBeUndefined()
    expect(flow.targetHandle).toBeUndefined()
  })
})

describe('edgeAngleDeg', () => {
  it('горизонтальная линия слева направо — 0°', () => {
    expect(edgeAngleDeg(0, 0, 100, 0)).toBe(0)
  })

  it('вертикальная линия сверху вниз — 90°', () => {
    expect(edgeAngleDeg(0, 0, 0, 100)).toBe(90)
  })

  it('линия под 45° вниз-вправо', () => {
    expect(edgeAngleDeg(0, 0, 100, 100)).toBeCloseTo(45)
  })

  it('линия справа налево нормализуется в (-90, 90] — не 180°, иначе текст лёг бы вверх ногами', () => {
    // Та же горизонталь, что и в первом тесте, но source/target поменяны местами — без
    // нормализации получилось бы 180°, что для CSS rotate() визуально переворачивает подпись.
    expect(edgeAngleDeg(100, 0, 0, 0)).toBe(0)
  })

  it('линия снизу вверх и влево нормализуется в (-90, 90]', () => {
    // Сырой atan2 здесь дал бы -135°; нормализация (+180°) приводит к 45° — тот же наклон,
    // что и у зеркальной линии сверху-вниз-вправо, только читается слева направо.
    expect(edgeAngleDeg(100, 100, 0, 0)).toBeCloseTo(45)
  })
})

describe('edgeBaseStyle', () => {
  it('активная связь — без стиля', () => {
    expect(edgeBaseStyle(edge({ is_active: true }))).toBeUndefined()
  })
  it('неактивная связь — пунктир', () => {
    expect(edgeBaseStyle(edge({ is_active: false }))).toEqual({ strokeDasharray: '6 4' })
  })
})

describe('edgeIsRelatedToHover', () => {
  const e = edge({ source_node_id: 'a', target_node_id: 'b' })

  it('ничего не наведено — связано (подсветка неактивна, приглушать нечего)', () => {
    expect(edgeIsRelatedToHover(e, null, null)).toBe(true)
  })

  it('наведено само это ребро — связано', () => {
    expect(edgeIsRelatedToHover(e, null, 'e1')).toBe(true)
  })

  it('наведено другое ребро — не связано', () => {
    expect(edgeIsRelatedToHover(e, null, 'other-edge')).toBe(false)
  })

  it('наведён узел-источник или узел-приёмник этого ребра — связано', () => {
    expect(edgeIsRelatedToHover(e, 'a', null)).toBe(true)
    expect(edgeIsRelatedToHover(e, 'b', null)).toBe(true)
  })

  it('наведён посторонний узел — не связано', () => {
    expect(edgeIsRelatedToHover(e, 'c', null)).toBe(false)
  })

  it('наведены и узел, и ребро одновременно — ребро в приоритете', () => {
    expect(edgeIsRelatedToHover(e, 'c', 'e1')).toBe(true) // узел посторонний, но ребро — это оно само
  })
})
