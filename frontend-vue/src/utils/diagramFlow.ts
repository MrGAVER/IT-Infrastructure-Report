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

/** Подпись trunk-подключения вместо списка VLAN. Совпадает с TRUNK_EDGE_LABEL в
 * backend/app/services/diagram_export/_common.py (экспорт .svg/.drawio/.vsdx подписывает линии так же). */
export const TRUNK_EDGE_LABEL = 'trunk'

function vlanSummary(edge: DiagramEdge): string | undefined {
  if (!edge.vlans.length) return undefined
  // Полный список VLAN на trunk-линии нечитаем (десятки номеров) — пишем режим; сам список остаётся
  // в панели сведений о подключении (DiagramDetailPanel.vue).
  if (edge.is_trunk) return TRUNK_EDGE_LABEL
  return `VLAN ${edge.vlans.map((v) => v.vlan_id).join(', ')}`
}

/** Общая подпись ребра (рисуется посередине линии, см. DiagramConnectionEdge.vue) — список VLAN,
 * если есть, а у trunk-подключения с VLAN — просто «trunk». Раньше сюда же дублировались имена
 * портов ("eth0 ↔ Gi0/3 · VLAN 10, 20"), хотя те же самые имена ОТДЕЛЬНО показываются и у каждого
 * конца линии (edgeSourcePortLabel/edgeTargetPortLabel ниже) — на плотных диаграммах с длинными
 * именами портов и заметным числом связей это удваивало объём текста на линию без новой информации
 * и усиливало наложение подписей друг на друга (пункт 3 правки "диаграмма топологии сети"). */
export function edgeMidLabel(edge: DiagramEdge): string | undefined {
  return vlanSummary(edge)
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

/** Угол линии от (x1,y1) к (x2,y2) в градусах для CSS `rotate()`, под который подписи ребра
 * кладутся ВДОЛЬ линии, а не всегда горизонтально (пункт 3 правки "диаграмма топологии сети").
 * Нормализован в (-90, 90] — не «угол линии как есть», а с разворотом на 180°, если он вышел бы
 * за эти пределы: иначе половина линий (те, что идут справа налево или снизу вверх) укладывала
 * бы текст вверх ногами, читать который пришлось бы буквально наклонив голову. Единый угол на
 * все три подписи ребра (среднюю и обе крайние у портов) — не отдельный тангенс кривой Безье в
 * каждой точке: разница на глаз для типичных, не сильно изогнутых соединений этой диаграммы
 * пренебрежимо мала, а общий угол проще и предсказуемее для всех трёх сразу. */
export function edgeAngleDeg(x1: number, y1: number, x2: number, y2: number): number {
  let angle = (Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI
  if (angle > 90) angle -= 180
  else if (angle < -90) angle += 180
  return angle
}

/** Пункт 4 правки "диаграмма топологии сети": при большом числе связей трудно понять, что куда
 * идёт. Наведение на узел или ребро (см. DiagramView.vue) подсвечивает СВЯЗАННЫЕ с ним рёбра и
 * приглушает остальные — линии никак не перекраиваются, только упрощается проследить взглядом
 * конкретное соединение. Наведение на ребро — точечное (только оно само); наведение на узел —
 * все рёбра, у которых этот узел источник ИЛИ приёмник. hoveredEdgeId в приоритете над
 * hoveredNodeId, если наведены оба одновременно (курсор физически не может быть одновременно
 * над двумя разными элементами, но проверка на всякий случай не помешает).
 */
export function edgeIsRelatedToHover(edge: DiagramEdge, hoveredNodeId: string | null, hoveredEdgeId: string | null): boolean {
  if (hoveredEdgeId !== null) return edge.id === hoveredEdgeId
  if (hoveredNodeId !== null) return edge.source_node_id === hoveredNodeId || edge.target_node_id === hoveredNodeId
  return true
}

export function toFlowNode(n: DiagramNode): Node<DiagramNode> {
  return { id: n.id, type: n.type, position: { x: n.x, y: n.y }, data: n, draggable: true }
}

/** Базовый (не зависящий от подсветки при наведении, см. DiagramView.vue) стиль линии ребра —
 * вынесено отдельно, чтобы watcher подсветки в DiagramView.vue мог ДОБАВИТЬ opacity поверх
 * этого стиля, а не затереть его целиком (иначе неактивное соединение потеряло бы пунктир, как
 * только на диаграмме начиналось наведение на что угодно). */
export function edgeBaseStyle(e: DiagramEdge): Record<string, string> | undefined {
  return e.is_active ? undefined : { strokeDasharray: '6 4' }
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
    style: edgeBaseStyle(e),
  }
}
