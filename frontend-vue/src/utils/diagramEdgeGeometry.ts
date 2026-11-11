// Геометрия ломаных рёбер диаграммы (B-08: выделена из diagramEdgeRouting.ts, где она была перемешана с поиском пути).
//
// Здесь всё, что работает с готовыми точками и не знает ни про сетку трассировки, ни про A*: типы маршрута, точка выхода из хэндла,
// упрощение ломаной, проверка соответствия маршрута положению хэндлов, SVG-путь со скруглёнными углами и якорь подписи. Чистые функции
// без DOM, Vue и состояния. Выбор маршрута (сетка, A*, порядок рёбер) — в diagramEdgeRouting.ts, подключение к Vue Flow — в
// diagramEdgeFlow.ts.
import type { Position } from '@vue-flow/core'

export interface Point {
  x: number
  y: number
}

export interface RouteNode {
  id: string
  x: number
  y: number
  width: number
  height: number
}

/** Сторона узла, из которой ребро выходит: совпадает со значениями Position из Vue Flow. */
export type Side = 'top' | 'right' | 'bottom' | 'left'

export interface RouteEnd {
  /** Точка хэндла — там, где ребро касается узла. */
  point: Point
  side: Side
}

export interface RouteRequest {
  id: string
  source: RouteEnd
  target: RouteEnd
}

/** Ломаная от точки хэндла источника до точки хэндла приёмника; соседние звенья перпендикулярны. */
export type EdgeRoute = readonly Point[]
export type EdgeRouteMap = ReadonlyMap<string, EdgeRoute>

/** Зазор между узлом и линиями, которые его огибают, px канваса. Он же длина прямого выхода из хэндла. */
export const ROUTE_CLEARANCE = 12

/** Допуск сравнения координат: значения ближе друг к другу считаются одним и тем же. */
export const EPS = 1e-6

const OUTWARD: Record<Side, Point> = {
  top: { x: 0, y: -1 },
  right: { x: 1, y: 0 },
  bottom: { x: 0, y: 1 },
  left: { x: -1, y: 0 },
}

/** Ось, по которой идёт прямой выход из хэндла: 0 — горизонталь (слева/справа), 1 — вертикаль (сверху/снизу). */
export function sideAxis(side: Side): 0 | 1 {
  return side === 'left' || side === 'right' ? 0 : 1
}

/** Точка в `ROUTE_CLEARANCE` от хэндла наружу: отсюда начинается поиск пути. */
export function stubPoint(end: RouteEnd): Point {
  const out = OUTWARD[end.side]
  return { x: end.point.x + out.x * ROUTE_CLEARANCE, y: end.point.y + out.y * ROUTE_CLEARANCE }
}

/** Убирает промежуточные точки на прямой и повторы: у ломаной остаются только настоящие углы. */
export function simplifyPolyline(points: readonly Point[]): Point[] {
  const result: Point[] = []
  for (const point of points) {
    const last = result[result.length - 1]
    if (last && Math.abs(last.x - point.x) < EPS && Math.abs(last.y - point.y) < EPS) continue
    result.push({ x: point.x, y: point.y })
  }
  for (let i = result.length - 2; i > 0; i--) {
    const a = result[i - 1]
    const b = result[i]
    const c = result[i + 1]
    const sameX = Math.abs(a.x - b.x) < EPS && Math.abs(b.x - c.x) < EPS
    const sameY = Math.abs(a.y - b.y) < EPS && Math.abs(b.y - c.y) < EPS
    if (sameX || sameY) result.splice(i, 1)
  }
  return result
}

/** Совпадает ли маршрут с текущим положением хэндлов (допуск `tolerance` px): после сдвига узла старый маршрут недействителен. */
export function routeMatchesEnds(route: EdgeRoute, source: Point, target: Point, tolerance = 0.5): boolean {
  if (route.length < 2) return false
  const first = route[0]
  const last = route[route.length - 1]
  return (
    Math.abs(first.x - source.x) <= tolerance &&
    Math.abs(first.y - source.y) <= tolerance &&
    Math.abs(last.x - target.x) <= tolerance &&
    Math.abs(last.y - target.y) <= tolerance
  )
}

/**
 * SVG-путь по ломаной со скруглёнными углами. Радиус не больше половины каждого из соседних звеньев, иначе дуги соседних углов
 * налезали бы друг на друга; у совсем коротких звеньев угол остаётся острым.
 */
export function roundedPolylinePath(points: readonly Point[], radius = 8): string {
  if (points.length === 0) return ''
  const fmt = (n: number): string => String(Math.round(n * 100) / 100)
  let d = `M ${fmt(points[0].x)} ${fmt(points[0].y)}`
  for (let i = 1; i < points.length - 1; i++) {
    const prev = points[i - 1]
    const corner = points[i]
    const next = points[i + 1]
    const lenIn = Math.hypot(corner.x - prev.x, corner.y - prev.y)
    const lenOut = Math.hypot(next.x - corner.x, next.y - corner.y)
    const r = Math.min(radius, lenIn / 2, lenOut / 2)
    if (r < EPS) {
      d += ` L ${fmt(corner.x)} ${fmt(corner.y)}`
      continue
    }
    const inX = (corner.x - prev.x) / lenIn
    const inY = (corner.y - prev.y) / lenIn
    const outX = (next.x - corner.x) / lenOut
    const outY = (next.y - corner.y) / lenOut
    d += ` L ${fmt(corner.x - inX * r)} ${fmt(corner.y - inY * r)} Q ${fmt(corner.x)} ${fmt(corner.y)} ${fmt(corner.x + outX * r)} ${fmt(corner.y + outY * r)}`
  }
  const last = points[points.length - 1]
  if (points.length > 1) d += ` L ${fmt(last.x)} ${fmt(last.y)}`
  return d
}

/** Середина самого длинного звена: туда кладётся центральная подпись ребра. Самое длинное звено — чтобы подпись не села в излом. */
export function routeLabelAnchor(points: readonly Point[]): Point {
  let best: Point = points[0] ?? { x: 0, y: 0 }
  let bestLength = -1
  for (let i = 0; i + 1 < points.length; i++) {
    const a = points[i]
    const b = points[i + 1]
    const length = Math.hypot(b.x - a.x, b.y - a.y)
    if (length > bestLength + EPS) {
      bestLength = length
      best = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
    }
  }
  return best
}

/** Сторона узла из Position Vue Flow (значения enum — те же строки). */
export function sideOfPosition(position: Position | string): Side {
  switch (position) {
    case 'top':
    case 'right':
    case 'left':
      return position
    default:
      return 'bottom'
  }
}
