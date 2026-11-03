// UI-22 (ревью 2.158.0): подписи портов не должны ложиться на узел и друг на друга.
import { describe, expect, it } from 'vitest'
import { Position } from '@vue-flow/core'
import type { DiagramEdge } from '../../api/diagrams'
import {
  EDGE_LABEL_MIN_ZOOM,
  PARALLEL_GROUP_MIN,
  PORT_LABEL_SLOTS,
  computeEdgeLabelLayout,
  edgeLabelTexts,
  edgeLabelsVisible,
  portLabelDistance,
} from '../diagramEdgeLabels'

function edge(id: string, source: string, target: string, sourcePort?: number, targetPort?: number, extra: Partial<DiagramEdge> = {}): DiagramEdge {
  return {
    id,
    source_node_id: source,
    source_interface: { id: `${id}-s`, name: `Gi1/0/${sourcePort ?? 0}`, ...(sourcePort !== undefined ? { port_index: sourcePort } : {}) },
    target_node_id: target,
    target_interface: { id: `${id}-t`, name: `Gi2/0/${targetPort ?? 0}`, ...(targetPort !== undefined ? { port_index: targetPort } : {}) },
    connection_type: null,
    is_active: true,
    is_trunk: false,
    vlans: [],
    ...extra,
  }
}

describe('UI-22: edgeLabelsVisible — подписи скрыты на мелком масштабе', () => {
  it('ниже 0,6 скрыты, с 0,6 и выше видны', () => {
    expect(EDGE_LABEL_MIN_ZOOM).toBe(0.6)
    expect(edgeLabelsVisible(0.28)).toBe(false)
    expect(edgeLabelsVisible(0.599)).toBe(false)
    expect(edgeLabelsVisible(0.6)).toBe(true)
    expect(edgeLabelsVisible(1.4)).toBe(true)
  })
})

describe('UI-22: computeEdgeLabelLayout — слоты подписей соседних портов', () => {
  it('концы рёбер у соседних засечек одного узла получают разные слоты, слоты идут по кругу', () => {
    const edges = [0, 1, 2, 3, 4, 5].map((port) => edge(`e${port}`, 'sw', `host${port}`, port, 0))
    const layout = computeEdgeLabelLayout(edges)
    const slots = edges.map((e) => layout.get(e.id)!.sourceSlot)
    expect(slots).toEqual([0, 1, 2, 0, 1, 2])
    for (let i = 1; i < slots.length; i++) expect(slots[i]).not.toBe(slots[i - 1])
    expect(Math.max(...slots)).toBeLessThan(PORT_LABEL_SLOTS)
  })

  it('слоты считаются по порядку засечек, а не по порядку рёбер на входе, и стабильны при перестановке', () => {
    const edges = [edge('b', 'sw', 'h1', 5, 0), edge('a', 'sw', 'h2', 1, 0), edge('c', 'sw', 'h3', 3, 0)]
    const first = computeEdgeLabelLayout(edges)
    const second = computeEdgeLabelLayout([...edges].reverse())
    for (const e of edges) expect(second.get(e.id)).toEqual(first.get(e.id))
    expect(first.get('a')!.sourceSlot).toBe(0) // порт 1 — первая засечка
    expect(first.get('c')!.sourceSlot).toBe(1)
    expect(first.get('b')!.sourceSlot).toBe(2)
  })

  it('источник и приёмник одного узла делят одну нумерацию: слот учитывает все концы, которые у узла есть', () => {
    const layout = computeEdgeLabelLayout([edge('x', 'a', 'b', 0, 0), edge('y', 'b', 'c', 0, 0)])
    // у узла b два конца с портом 0 (приёмник x и источник y) — слоты разные
    expect(layout.get('x')!.targetSlot).not.toBe(layout.get('y')!.sourceSlot)
  })

  it('концы без засечки (свёрнутая группа, custom-значок) тоже разводятся — стабильно по id', () => {
    const layout = computeEdgeLabelLayout([edge('k2', 'grp', 'h2'), edge('k1', 'grp', 'h1'), edge('k3', 'grp', 'h3')])
    expect(['k1', 'k2', 'k3'].map((id) => layout.get(id)!.sourceSlot)).toEqual([0, 1, 2])
  })

  it('параллельные связи между одной парой — в одной группе независимо от направления; счётчик и номер заданы', () => {
    const layout = computeEdgeLabelLayout([edge('p1', 'a', 'b', 0, 0), edge('p2', 'b', 'a', 1, 1), edge('p3', 'a', 'b', 2, 2), edge('other', 'a', 'c', 3, 0)])
    expect(['p1', 'p2', 'p3'].map((id) => layout.get(id)!.parallelCount)).toEqual([3, 3, 3])
    expect(['p1', 'p2', 'p3'].map((id) => layout.get(id)!.parallelIndex)).toEqual([0, 1, 2])
    expect(layout.get('other')).toMatchObject({ parallelCount: 1, parallelIndex: 0 })
  })

  it('пустая диаграмма — пустая раскладка', () => {
    expect(computeEdgeLabelLayout([]).size).toBe(0)
  })
})

describe('UI-22: edgeLabelTexts — группировка «×N»', () => {
  const vlanEdge = (id: string, port: number) => edge(id, 'a', 'b', port, port, { vlans: [{ id: 'v', vlan_id: 10, name: 'users' }] as DiagramEdge['vlans'] })

  it('одиночная связь подписана как раньше: порты у обоих концов', () => {
    const e = edge('e', 'a', 'b', 0, 0)
    const layout = computeEdgeLabelLayout([e]).get('e')
    expect(edgeLabelTexts(e, layout)).toEqual({ mid: undefined, source: 'Gi1/0/0', target: 'Gi2/0/0' })
  })

  it('без раскладки (компонент вне диаграммы) — тоже как раньше', () => {
    expect(edgeLabelTexts(edge('e', 'a', 'b', 0, 0))).toMatchObject({ source: 'Gi1/0/0', target: 'Gi2/0/0' })
  })

  it('две параллельные связи группируются не раньше порога: подписи обеих остаются', () => {
    expect(PARALLEL_GROUP_MIN).toBe(3)
    const edges = [edge('p1', 'a', 'b', 0, 0), edge('p2', 'a', 'b', 1, 1)]
    const layout = computeEdgeLabelLayout(edges)
    for (const e of edges) expect(edgeLabelTexts(e, layout.get(e.id)).source).toBeDefined()
  })

  it('три и больше: первая несёт порты и «×3», остальные подписей не рисуют', () => {
    const edges = [edge('p1', 'a', 'b', 0, 0), edge('p2', 'a', 'b', 1, 1), edge('p3', 'a', 'b', 2, 2)]
    const layout = computeEdgeLabelLayout(edges)
    expect(edgeLabelTexts(edges[0], layout.get('p1'))).toEqual({ mid: '×3', source: 'Gi1/0/0', target: 'Gi2/0/0' })
    expect(edgeLabelTexts(edges[1], layout.get('p2'))).toEqual({})
    expect(edgeLabelTexts(edges[2], layout.get('p3'))).toEqual({})
  })

  it('«×N» дописывается к подписи VLAN первой связи, а не заменяет её', () => {
    const edges = [vlanEdge('p1', 0), vlanEdge('p2', 1), vlanEdge('p3', 2), vlanEdge('p4', 3)]
    const layout = computeEdgeLabelLayout(edges)
    const mid = edgeLabelTexts(edges[0], layout.get('p1')).mid
    expect(mid).toMatch(/ · ×4$/)
    expect(mid!.length).toBeGreaterThan('×4'.length)
  })
})

describe('UI-22: portLabelDistance — подпись не заходит на узел', () => {
  const TEXT = 'Gi1/0/13'

  it('горизонтальная подпись снизу от узла — прежние 14 px (не дальше без нужды)', () => {
    expect(portLabelDistance(TEXT, 0, Position.Bottom, 0)).toBe(14)
  })

  it('вертикальная линия: подпись стоит столбиком и отодвигается на половину своей длины — иначе заходила бы на узел', () => {
    const distance = portLabelDistance(TEXT, 90, Position.Bottom, 0)
    const width = TEXT.length * 5.4 + 12
    expect(distance).toBeGreaterThanOrEqual(width / 2) // край подписи (центр − размах) не ближе нуля к узлу
    expect(distance).toBeGreaterThan(14)
  })

  it('на любом наклоне отступ не меньше прежних 14 px и не больше полудиагонали подписи с зазором (максимум размаха — на угле диагонали, ≈ 74°, а не на 90°)', () => {
    const halfDiagonal = Math.hypot(TEXT.length * 5.4 + 12, 16) / 2 + 4
    for (let angle = 0; angle <= 90; angle += 15) {
      const distance = portLabelDistance(TEXT, angle, Position.Bottom, 0)
      expect(distance).toBeGreaterThanOrEqual(14)
      expect(distance).toBeLessThanOrEqual(halfDiagonal + 1e-9)
    }
    expect(portLabelDistance(TEXT, 75, Position.Bottom, 0)).toBeGreaterThan(portLabelDistance(TEXT, 90, Position.Bottom, 0))
  })

  it('у бокового хэндла всё наоборот: горизонтальная подпись длинная вдоль оси «наружу» — отступ большой, вертикальная — малый', () => {
    expect(portLabelDistance(TEXT, 0, Position.Right, 0)).toBeGreaterThan(portLabelDistance(TEXT, 90, Position.Right, 0))
  })

  it('слот сдвигает подпись дальше вдоль ребра на целое число шагов; Top и Bottom симметричны', () => {
    const base = portLabelDistance(TEXT, 45, Position.Bottom, 0)
    expect(portLabelDistance(TEXT, 45, Position.Bottom, 2) - base).toBe(2 * 16)
    expect(portLabelDistance(TEXT, 45, Position.Top, 1)).toBe(portLabelDistance(TEXT, 45, Position.Bottom, 1))
  })

  it('длинное имя порта отодвигается дальше короткого на том же наклоне', () => {
    expect(portLabelDistance('GigabitEthernet1/0/13', 60, Position.Bottom, 0)).toBeGreaterThan(portLabelDistance('Gi1', 60, Position.Bottom, 0))
  })
})
