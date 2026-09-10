// Преобразование DiagramNode/DiagramEdge (контракт раздела 4.4 ТЗ) в формат узлов/рёбер
// @vue-flow/core — вынесено из DiagramView.vue в чистые функции без побочных эффектов: подъём
// реального <VueFlow> в jsdom требует ResizeObserver/layout-заглушек (известное ограничение
// тестирования этой библиотеки в jsdom), а логика анкеринга к засечкам портов — это как раз то,
// что здесь важнее всего перепроверить тестами. См. src/utils/__tests__/diagramFlow.spec.ts.
import type { Edge, Node } from '@vue-flow/core'
import type { DiagramEdge, DiagramNode } from '../api/diagrams'

export const GROUP_PREFIX = 'group:'

export function groupKeyOf(nodeId: string): string {
  return nodeId.startsWith(GROUP_PREFIX) ? nodeId.slice(GROUP_PREFIX.length) : nodeId
}

/** Раздел 4.4 ТЗ: анкеринг ребра к засечке порта существует только для узлов shape="switch" и
 * только когда backend прислал port_index (в пределах первых 32 портов, см.
 * backend/app/services/diagram_icons.py:MAX_PORT_TICKS) — иначе ребро подключается к
 * единственному дефолтному Handle узла ("ближайшая сторона", см. DiagramDeviceNode.vue). */
export function isSwitchNode(nodes: DiagramNode[], nodeId: string): boolean {
  const node = nodes.find((n) => n.id === nodeId)
  return !!node && node.type === 'device' && node.icon.mode === 'generated' && node.icon.shape === 'switch'
}

export function sourceHandleId(nodes: DiagramNode[], edge: DiagramEdge): string | undefined {
  const idx = edge.source_interface?.port_index
  return isSwitchNode(nodes, edge.source_node_id) && idx !== undefined ? `port-${idx}-source` : undefined
}

export function targetHandleId(nodes: DiagramNode[], edge: DiagramEdge): string | undefined {
  const idx = edge.target_interface?.port_index
  return isSwitchNode(nodes, edge.target_node_id) && idx !== undefined ? `port-${idx}-target` : undefined
}

export function toFlowNode(n: DiagramNode): Node<DiagramNode> {
  return { id: n.id, type: n.type, position: { x: n.x, y: n.y }, data: n, draggable: true }
}

export function toFlowEdge(nodes: DiagramNode[], e: DiagramEdge): Edge<DiagramEdge> {
  return {
    id: e.id,
    source: e.source_node_id,
    target: e.target_node_id,
    sourceHandle: sourceHandleId(nodes, e),
    targetHandle: targetHandleId(nodes, e),
    label: e.vlans.length ? `VLAN ${e.vlans.map((v) => v.vlan_id).join(', ')}` : undefined,
    data: e,
    updatable: false,
    style: e.is_active ? undefined : { strokeDasharray: '6 4' },
  }
}
