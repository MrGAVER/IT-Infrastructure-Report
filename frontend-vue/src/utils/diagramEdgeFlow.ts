// Подключение трассировки к Vue Flow (B-08: выделено из diagramEdgeRouting.ts): ключ provide/inject для маршрутов и перевод состояния
// канваса (узлы с измеренными хэндлами, рёбра) во входные данные трассировки. С самой трассировкой не связано — только с формой
// объектов Vue Flow.
import type { Position } from '@vue-flow/core'
import type { InjectionKey, Ref } from 'vue'
import { sideOfPosition, type EdgeRouteMap, type Point, type RouteEnd, type RouteNode, type RouteRequest } from './diagramEdgeGeometry'

/** Маршруты всех рёбер диаграммы передаются компонентам рёбер через provide/inject: это результат совместного расчёта, одному ребру он не виден. */
export const EDGE_ROUTES_KEY: InjectionKey<Ref<EdgeRouteMap>> = Symbol('diagram-edge-routes')

// Структурные типы вместо GraphNode/GraphEdge Vue Flow: функции ниже проверяются юнит-тестами на простых объектах, а сам GraphNode им
// удовлетворяет (computedPosition, dimensions и handleBounds — поля, которые Vue Flow заполняет после измерения узла в DOM).
export interface FlowHandleLike {
  id?: string | null
  position: Position | string
  x: number
  y: number
  width: number
  height: number
}

export interface FlowNodeLike {
  id: string
  computedPosition: Point
  dimensions: { width: number; height: number }
  handleBounds?: { source?: readonly FlowHandleLike[] | null; target?: readonly FlowHandleLike[] | null }
}

export interface FlowEdgeLike {
  id: string
  source: string
  target: string
  sourceHandle?: string | null
  targetHandle?: string | null
}

/**
 * Точка и сторона, где ребро подключается к узлу, — по тем же правилам, что у Vue Flow (getEdgeHandle + getHandlePosition): хэндл по
 * id, а без id или без такого хэндла — середина нижней (источник) либо верхней (приёмник) стороны узла. Совпадать с Vue Flow нужно
 * до пикселя: DiagramConnectionEdge принимает маршрут, только если его концы лежат на тех же точках, что sourceX/targetX ребра.
 */
function endOf(node: FlowNodeLike, role: 'source' | 'target', handleId: string | null | undefined): RouteEnd {
  const bounds = node.handleBounds?.[role] ?? null
  const handle = (bounds ? (handleId ? bounds.find((h) => h.id === handleId) : bounds[0]) : undefined) ?? null
  const side = sideOfPosition(handle?.position ?? (role === 'source' ? 'bottom' : 'top'))
  const x = (handle?.x ?? 0) + node.computedPosition.x
  const y = (handle?.y ?? 0) + node.computedPosition.y
  const { width, height } = handle ?? node.dimensions
  switch (side) {
    case 'top':
      return { point: { x: x + width / 2, y }, side }
    case 'right':
      return { point: { x: x + width, y: y + height / 2 }, side }
    case 'left':
      return { point: { x, y: y + height / 2 }, side }
    default:
      return { point: { x: x + width / 2, y: y + height }, side }
  }
}

/** Узлы-препятствия и запросы на маршруты по состоянию канваса. Рёбра без измеренных узлов пропускаются: их нарисует прежняя кривая. */
export function routeInputsFromFlow(nodes: readonly FlowNodeLike[], edges: readonly FlowEdgeLike[]): { nodes: RouteNode[]; requests: RouteRequest[] } {
  const measured = nodes.filter((n) => n.dimensions.width > 0 && n.dimensions.height > 0)
  const byId = new Map(measured.map((n) => [n.id, n]))
  const requests: RouteRequest[] = []
  for (const edge of edges) {
    const source = byId.get(edge.source)
    const target = byId.get(edge.target)
    if (!source || !target) continue
    requests.push({ id: edge.id, source: endOf(source, 'source', edge.sourceHandle), target: endOf(target, 'target', edge.targetHandle) })
  }
  return {
    nodes: measured.map((n) => ({ id: n.id, x: n.computedPosition.x, y: n.computedPosition.y, width: n.dimensions.width, height: n.dimensions.height })),
    requests,
  }
}
