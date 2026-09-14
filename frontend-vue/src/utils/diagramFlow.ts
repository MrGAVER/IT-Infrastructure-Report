// Преобразование DiagramNode/DiagramEdge (контракт раздела 4.4 ТЗ) в формат узлов/рёбер
// @vue-flow/core — вынесено из DiagramView.vue в чистые функции без побочных эффектов: подъём
// реального <VueFlow> в jsdom требует ResizeObserver/layout-заглушек (известное ограничение
// тестирования этой библиотеки в jsdom), а логика анкеринга к засечкам портов и подписей рёбер —
// это как раз то, что здесь важнее всего перепроверить тестами. По той же причине рендер самого
// ребра вынесен в тонкий компонент DiagramConnectionEdge.vue, который только раскладывает
// результаты этих функций по BaseEdge/EdgeLabelRenderer и сам не тестируется напрямую — вся
// логика (и её тесты) здесь. См. src/utils/__tests__/diagramFlow.spec.ts.
import { Position, type Edge, type Node } from '@vue-flow/core'
import type { DiagramEdge, DiagramInterfaceRef, DiagramNode } from '../api/diagrams'

export const GROUP_PREFIX = 'group:'

/** Тип кастомного компонента ребра (см. DiagramConnectionEdge.vue), под которым он
 * зарегистрирован в DiagramView.vue — единственное место, где имя типа должно совпадать. */
export const CONNECTION_EDGE_TYPE = 'connection'

/** Отступ подписи конкретного порта от точки, где линия физически подключается к устройству
 * (px, в системе координат канваса, не экрана) — раздел 4.4 ТЗ, "надо визуально показать, какой
 * порт к какому подключён". Один относительно небольшой отступ, чтобы подпись читалась как
 * "бирка у разъёма", а не сливалась с общей подписью ребра посередине линии. */
export const PORT_LABEL_OFFSET = 14

export function groupKeyOf(nodeId: string): string {
  return nodeId.startsWith(GROUP_PREFIX) ? nodeId.slice(GROUP_PREFIX.length) : nodeId
}

/** Раздел 4.4 ТЗ: анкеринг ребра к засечке порта — backend присылает port_index уже только
 * тогда, когда это безопасно использовать как id Handle на канвасе: устройство со сгенерированным
 * (не custom) значком И этот конец ребра отрисован как узел самого устройства, а не свёрнут в
 * группу (см. GraphContext.device_supports_port_index в services/diagram_graph.py). Раньше эта
 * проверка дублировалась и на фронтенде через поиск по shape="switch" в списке узлов — теперь
 * контракт сам это гарантирует, и здесь достаточно просто прочитать port_index. */
export function sourceHandleId(edge: DiagramEdge): string | undefined {
  const idx = edge.source_interface?.port_index
  return idx !== undefined ? `port-${idx}-source` : undefined
}

export function targetHandleId(edge: DiagramEdge): string | undefined {
  const idx = edge.target_interface?.port_index
  return idx !== undefined ? `port-${idx}-target` : undefined
}

function interfaceName(ref: DiagramInterfaceRef | null): string | undefined {
  return ref?.name || undefined
}

function vlanSummary(edge: DiagramEdge): string | undefined {
  return edge.vlans.length ? `VLAN ${edge.vlans.map((v) => v.vlan_id).join(', ')}` : undefined
}

/** Общая подпись ребра (рисуется посередине линии, см. DiagramConnectionEdge.vue): раньше несла
 * только VLAN, из-за чего на канвасе не было НИКАКОГО текстового указания порта, даже когда сами
 * линии уже анкерились к разным засечкам. Теперь показывает оба конца связи по именам портов и,
 * если есть, список VLAN — например "eth0 ↔ Gi0/3 · VLAN 10, 20". */
export function edgeMidLabel(edge: DiagramEdge): string | undefined {
  const from = interfaceName(edge.source_interface)
  const to = interfaceName(edge.target_interface)
  const ports = from && to ? `${from} ↔ ${to}` : undefined
  return [ports, vlanSummary(edge)].filter((part): part is string => !!part).join(' · ')
}

/** Подпись конкретного порта у самого устройства (доп. к общей подписи посередине линии, раздел
 * 4.4 ТЗ) — по одной у каждого конца ребра, чтобы было видно, в какой именно порт упирается линия,
 * даже когда к одному устройству подходит несколько связей одновременно. */
export function edgeSourcePortLabel(edge: DiagramEdge): string | undefined {
  return interfaceName(edge.source_interface)
}

export function edgeTargetPortLabel(edge: DiagramEdge): string | undefined {
  return interfaceName(edge.target_interface)
}

/** Сдвигает точку (x, y) на `distance` px в направлении, в котором Handle "торчит" из узла —
 * т.е. наружу от устройства вдоль линии. Используется, чтобы подпись порта легла рядом с
 * устройством, а не поверх самой линии или центра узла. Чистая геометрия, никакого доступа к
 * DOM/канвасу, поэтому полностью проверяется юнит-тестами (см. diagramFlow.spec.ts). */
export function offsetAlongHandle(x: number, y: number, position: Position, distance = PORT_LABEL_OFFSET): { x: number; y: number } {
  switch (position) {
    case Position.Top:
      return { x, y: y - distance }
    case Position.Bottom:
      return { x, y: y + distance }
    case Position.Left:
      return { x: x - distance, y }
    case Position.Right:
      return { x: x + distance, y }
    default:
      return { x, y }
  }
}

export function toFlowNode(n: DiagramNode): Node<DiagramNode> {
  return { id: n.id, type: n.type, position: { x: n.x, y: n.y }, data: n, draggable: true }
}

export function toFlowEdge(e: DiagramEdge): Edge<DiagramEdge> {
  return {
    id: e.id,
    type: CONNECTION_EDGE_TYPE,
    source: e.source_node_id,
    target: e.target_node_id,
    sourceHandle: sourceHandleId(e),
    targetHandle: targetHandleId(e),
    data: e,
    updatable: false,
    style: e.is_active ? undefined : { strokeDasharray: '6 4' },
  }
}
