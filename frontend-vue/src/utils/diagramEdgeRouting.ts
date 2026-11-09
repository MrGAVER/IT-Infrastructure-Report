// Трассировка рёбер диаграммы топологии (код-ревью main, F-07).
//
// Раньше ребро рисовалось кривой Безье между двумя засечками портов у НИЖНЕГО края узлов. У связей внутри одного ряда сетки обе
// засечки на одной высоте, кривая вырождалась в горизонталь вдоль нижней границы узлов, и несколько таких связей ложились друг
// на друга; связи между рядами шли по диагонали через чужие узлы. На схеме из 18 узлов 16 из 22 рёбер проходили сквозь узлы,
// и понять, что куда подключено, было нельзя.
//
// Теперь ребро — ортогональная ломаная, которая обходит ВСЕ узлы и не ложится на уже проложенные рёбра:
//  1. вокруг каждого узла строится запретная область с зазором ROUTE_CLEARANCE;
//  2. линии сетки трассировки проходят по границам запретных областей, по выходам из хэндлов и по «дорожкам» — равномерно
//     распределённым линиям внутри свободных промежутков между узлами. Между линиями ничего не лежит поперёк, поэтому участок
//     сетки либо целиком свободен, либо целиком внутри узла, и проверка препятствий сводится к двум булевым массивам;
//  3. по этой сетке A* ищет самый короткий путь с штрафом за повороты (меньше изломов — читаемее) и за участки, уже занятые
//     другими рёбрами: так параллельные связи расходятся по соседним дорожкам, а не сливаются в одну линию;
//  4. рёбра прокладываются от коротких к длинным: короткая связь получает ближайшую дорожку, длинной приходится обходить.
//
// Всё это геометрия без DOM и без Vue, поэтому проверяется юнит-тестами (utils/__tests__/diagramEdgeRouting.spec.ts). Сложность
// ограничена тремя защитами: у слишком большой схемы (MAX_GRID_VERTICES) и у схемы с чрезмерным числом рёбер (MAX_ROUTED_EDGES)
// трассировка отключается, а общий расчёт укладывается в бюджет времени ROUTING_BUDGET_MS: что не успело, рисуется прежней кривой
// Безье — лучше прежний вид, чем зависший интерфейс (код-ревью, FE-01). Узел, который пользователь тащит мышью, не пересчитывается на каждом кадре: маршруты
// считает DiagramView после остановки, а пока маршрут не совпадает с положением хэндлов, ребро рисуется кривой Безье.
import type { Position } from '@vue-flow/core'
import type { InjectionKey, Ref } from 'vue'

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
/** Желаемое расстояние между соседними дорожками в свободном промежутке, px. */
export const ROUTE_LANE_STEP = 8
/** Сколько дорожек максимум добавляется в один промежуток: широкий промежуток не должен раздувать сетку. */
const MAX_LANES_PER_GAP = 8
/** Штраф за поворот в пересчёте на px пути: два лишних излома стоят около 50 px обхода. */
const BEND_PENALTY = 25
/** Множитель длины участка за каждое уже проложенное по нему ребро: наложение дороже обходной дорожки. */
const CONGESTION_FACTOR = 6
/** Сколько дорожек добавляется снаружи крайних линий: за пределами схемы места сколько угодно, и обходящим её рёбрам нужно где-то расходиться. */
const OUTER_LANES = 6
/** Фиксированный штраф за каждый занятый участок независимо от длины: иначе наложение на три пикселя стоило бы дешевле одного излома. */
const OVERLAP_PENALTY = 40
/** Небольшой штраф за движение вплотную к узлу: линии по центру промежутка читаются лучше, чем прижатые к границе. */
const HUG_FACTOR = 0.15
/** Предел размера сетки (линий по X × линий по Y). Выше — трассировка отключена. Для 20 узлов сетка ≈ 100 × 100. */
export const MAX_GRID_VERTICES = 160_000
/** Предел числа вершин, которые A* может раскрыть для одного ребра: защита от патологически запутанной схемы. */
const MAX_EXPANSIONS = 400_000
/** Бюджет времени на расчёт всех маршрутов, мс: что не успело — рисуется прежней кривой Безье. */
export const ROUTING_BUDGET_MS = 250
/** Выше этого числа рёбер трассировка не включается: время расчёта растёт быстрее числа рёбер (на 1500 рёбрах — десятки секунд). */
export const MAX_ROUTED_EDGES = 400
/** Как часто A* сверяется с часами, в раскрытиях вершин (степень двойки минус один — маска): чтение времени на каждом шаге дороже самого шага. */
const CLOCK_CHECK_MASK = 0xfff

const EPS = 1e-6

interface Rect {
  left: number
  top: number
  right: number
  bottom: number
}

const OUTWARD: Record<Side, Point> = {
  top: { x: 0, y: -1 },
  right: { x: 1, y: 0 },
  bottom: { x: 0, y: 1 },
  left: { x: -1, y: 0 },
}

/** Ось, по которой идёт прямой выход из хэндла: 0 — горизонталь (слева/справа), 1 — вертикаль (сверху/снизу). */
function sideAxis(side: Side): 0 | 1 {
  return side === 'left' || side === 'right' ? 0 : 1
}

/** Точка в `ROUTE_CLEARANCE` от хэндла наружу: отсюда начинается поиск пути. */
export function stubPoint(end: RouteEnd): Point {
  const out = OUTWARD[end.side]
  return { x: end.point.x + out.x * ROUTE_CLEARANCE, y: end.point.y + out.y * ROUTE_CLEARANCE }
}

function sortedUnique(values: number[]): number[] {
  const sorted = [...values].sort((a, b) => a - b)
  const result: number[] = []
  for (const value of sorted) {
    if (result.length === 0 || value - result[result.length - 1] > EPS) result.push(value)
  }
  return result
}

/**
 * Линии сетки по одной оси: обязательные значения (границы запретных областей, выходы хэндлов) плюс дорожки внутри свободных
 * промежутков между ними. `blockedRanges` — открытые интервалы (от, до) запретных областей по этой оси: промежуток, лежащий
 * целиком внутри узла, дорожек не получает.
 */
function buildLines(required: number[], blockedRanges: ReadonlyArray<readonly [number, number]>): number[] {
  const base = sortedUnique(required)
  const lines: number[] = [...base]
  for (let i = 0; i + 1 < base.length; i++) {
    const from = base[i]
    const to = base[i + 1]
    const middle = (from + to) / 2
    if (blockedRanges.some(([lo, hi]) => middle > lo + EPS && middle < hi - EPS)) continue
    const lanes = Math.min(MAX_LANES_PER_GAP, Math.floor((to - from) / ROUTE_LANE_STEP) - 1)
    for (let lane = 1; lane <= lanes; lane++) lines.push(from + ((to - from) * lane) / (lanes + 1))
  }
  if (base.length > 0) {
    for (let lane = 1; lane <= OUTER_LANES; lane++) {
      lines.push(base[0] - lane * ROUTE_LANE_STEP, base[base.length - 1] + lane * ROUTE_LANE_STEP)
    }
  }
  return sortedUnique(lines)
}

function indexOfValue(lines: readonly number[], value: number): number {
  let lo = 0
  let hi = lines.length - 1
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (lines[mid] < value - EPS) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** Двоичная куча по ключу: A* держит в ней тысячи состояний, а сортировка массива на каждом шаге была бы квадратичной. */
class MinHeap {
  private keys: number[] = []
  private values: number[] = []

  get size(): number {
    return this.keys.length
  }

  push(key: number, value: number): void {
    const keys = this.keys
    const values = this.values
    let i = keys.length
    keys.push(key)
    values.push(value)
    while (i > 0) {
      const parent = (i - 1) >> 1
      if (keys[parent] <= key) break
      keys[i] = keys[parent]
      values[i] = values[parent]
      i = parent
    }
    keys[i] = key
    values[i] = value
  }

  pop(): number {
    const keys = this.keys
    const values = this.values
    const top = values[0]
    const lastKey = keys.pop() as number
    const lastValue = values.pop() as number
    const n = keys.length
    if (n > 0) {
      let i = 0
      for (;;) {
        let child = 2 * i + 1
        if (child >= n) break
        if (child + 1 < n && keys[child + 1] < keys[child]) child++
        if (keys[child] >= lastKey) break
        keys[i] = keys[child]
        values[i] = values[child]
        i = child
      }
      keys[i] = lastKey
      values[i] = lastValue
    }
    return top
  }
}

interface Grid {
  xs: number[]
  ys: number[]
  width: number
  height: number
  /** Ячейка между линиями (i, j)–(i+1, j+1) целиком внутри запретной области узла. */
  cellBlocked: Uint8Array
  /** Занятость горизонтальных (hUse) и вертикальных (vUse) участков: сколько рёбер уже проложено по участку. */
  hUse: Uint16Array
  vUse: Uint16Array
}

function cellAt(grid: Grid, i: number, j: number): boolean {
  if (i < 0 || j < 0 || i >= grid.width - 1 || j >= grid.height - 1) return false
  return grid.cellBlocked[j * (grid.width - 1) + i] === 1
}

/** Горизонтальный участок (i, j)→(i + 1, j): непроходим, если ячейки по обе стороны заняты узлом (линия внутри него). */
function hBlocked(grid: Grid, i: number, j: number): boolean {
  return cellAt(grid, i, j - 1) && cellAt(grid, i, j)
}

function vBlocked(grid: Grid, i: number, j: number): boolean {
  return cellAt(grid, i - 1, j) && cellAt(grid, i, j)
}

/** Участок прижат к узлу: с одной стороны запретная область, с другой свободно. */
function hHugs(grid: Grid, i: number, j: number): boolean {
  return cellAt(grid, i, j - 1) !== cellAt(grid, i, j)
}

function vHugs(grid: Grid, i: number, j: number): boolean {
  return cellAt(grid, i - 1, j) !== cellAt(grid, i, j)
}

function buildGrid(nodes: readonly RouteNode[], stubs: readonly Point[]): Grid | null {
  const rects: Rect[] = nodes.map((node) => ({
    left: node.x - ROUTE_CLEARANCE,
    top: node.y - ROUTE_CLEARANCE,
    right: node.x + node.width + ROUTE_CLEARANCE,
    bottom: node.y + node.height + ROUTE_CLEARANCE,
  }))
  const xs = buildLines(
    [...rects.flatMap((r) => [r.left, r.right]), ...stubs.map((p) => p.x)],
    rects.map((r) => [r.left, r.right] as const),
  )
  const ys = buildLines(
    [...rects.flatMap((r) => [r.top, r.bottom]), ...stubs.map((p) => p.y)],
    rects.map((r) => [r.top, r.bottom] as const),
  )
  if (xs.length * ys.length > MAX_GRID_VERTICES) return null

  const width = xs.length
  const height = ys.length
  const cellBlocked = new Uint8Array(Math.max(0, (width - 1) * (height - 1)))
  for (const rect of rects) {
    const i1 = indexOfValue(xs, rect.left)
    const i2 = indexOfValue(xs, rect.right)
    const j1 = indexOfValue(ys, rect.top)
    const j2 = indexOfValue(ys, rect.bottom)
    for (let j = j1; j < j2; j++) for (let i = i1; i < i2; i++) cellBlocked[j * (width - 1) + i] = 1
  }
  return { xs, ys, width, height, cellBlocked, hUse: new Uint16Array(width * height), vUse: new Uint16Array(width * height) }
}

/**
 * Рабочие массивы A*, общие для всех рёбер схемы. Размер — по числу состояний сетки (до 320 000 элементов), и раньше они создавались
 * и заполнялись заново на каждое ребро. Теперь создаются один раз, а «чистка» — это новый номер поиска `run`: значение
 * `best`/`cameFrom` состояния действительно, только если `seen[состояние] === run`.
 */
interface Scratch {
  best: Float64Array
  cameFrom: Int32Array
  seen: Uint32Array
  run: number
}

function createScratch(grid: Grid): Scratch {
  const total = grid.width * grid.height * 2
  return { best: new Float64Array(total), cameFrom: new Int32Array(total), seen: new Uint32Array(total), run: 0 }
}

/** Часы расчёта: `now` подменяется в тестах, `deadline` — момент, после которого новые рёбра не начинаются, а начатый поиск прерывается. */
interface Clock {
  now: () => number
  deadline: number
}

/** Состояние поиска: вершина сетки и ось последнего звена (0 — горизонталь, 1 — вертикаль). Поворот — отдельный переход со штрафом. */
function stateOf(grid: Grid, i: number, j: number, axis: 0 | 1): number {
  return (j * grid.width + i) * 2 + axis
}

/** Найденный путь как последовательность вершин сетки (i, j); None, если пути нет. */
function findPath(
  grid: Grid,
  scratch: Scratch,
  start: { i: number; j: number; axis: 0 | 1 },
  goal: { i: number; j: number; axis: 0 | 1 },
  clock: Clock,
): Array<[number, number]> | null {
  const { xs, ys, width, height } = grid
  const { best, cameFrom, seen } = scratch
  // Массивы общие для всех рёбер схемы и не очищаются: состояние принадлежит этому поиску, только если seen[s] === run (метка поколения).
  const run = ++scratch.run
  const heap = new MinHeap()
  const goalState = stateOf(grid, goal.i, goal.j, goal.axis)
  const heuristic = (i: number, j: number): number => Math.abs(xs[i] - xs[goal.i]) + Math.abs(ys[j] - ys[goal.j])

  const startState = stateOf(grid, start.i, start.j, start.axis)
  seen[startState] = run
  best[startState] = 0
  cameFrom[startState] = -1
  heap.push(heuristic(start.i, start.j), startState)
  let expansions = 0

  const relax = (from: number, to: number, cost: number, i: number, j: number): void => {
    const next = best[from] + cost
    if (seen[to] !== run || next + EPS < best[to]) {
      seen[to] = run
      best[to] = next
      cameFrom[to] = from
      heap.push(next + heuristic(i, j), to)
    }
  }

  while (heap.size > 0) {
    const state = heap.pop()
    if (state === goalState) break
    if (++expansions > MAX_EXPANSIONS) return null
    // Время сверяется не на каждом шаге: поиск, не уложившийся в срок, отдаёт ребро кривой Безье, а не держит интерфейс.
    if ((expansions & CLOCK_CHECK_MASK) === 0 && clock.now() > clock.deadline) return null
    const axis = (state & 1) as 0 | 1
    const vertex = state >> 1
    const i = vertex % width
    const j = (vertex - i) / width
    // Поворот на месте.
    relax(state, stateOf(grid, i, j, (1 - axis) as 0 | 1), BEND_PENALTY, i, j)

    if (axis === 0) {
      if (i + 1 < width && !hBlocked(grid, i, j)) {
        relax(state, stateOf(grid, i + 1, j, 0), segmentCost(grid, 0, i, j, xs[i + 1] - xs[i]), i + 1, j)
      }
      if (i > 0 && !hBlocked(grid, i - 1, j)) {
        relax(state, stateOf(grid, i - 1, j, 0), segmentCost(grid, 0, i - 1, j, xs[i] - xs[i - 1]), i - 1, j)
      }
    } else {
      if (j + 1 < height && !vBlocked(grid, i, j)) {
        relax(state, stateOf(grid, i, j + 1, 1), segmentCost(grid, 1, i, j, ys[j + 1] - ys[j]), i, j + 1)
      }
      if (j > 0 && !vBlocked(grid, i, j - 1)) {
        relax(state, stateOf(grid, i, j - 1, 1), segmentCost(grid, 1, i, j - 1, ys[j] - ys[j - 1]), i, j - 1)
      }
    }
  }

  if (seen[goalState] !== run) return null
  const vertices: Array<[number, number]> = []
  for (let state = goalState; state !== -1; state = cameFrom[state]) {
    const vertex = state >> 1
    const i = vertex % width
    vertices.push([i, (vertex - i) / width])
    if (state === startState) break
  }
  vertices.reverse()
  return vertices
}

/** Цена участка: длина, умноженная на (1 + загруженность + прижатость к узлу), плюс фиксированный штраф за каждое занявшее его ребро. `kind` 0 — горизонтальный, 1 — вертикальный. */
function segmentCost(grid: Grid, kind: 0 | 1, i: number, j: number, length: number): number {
  const use = kind === 0 ? grid.hUse[j * grid.width + i] : grid.vUse[j * grid.width + i]
  const hugs = kind === 0 ? hHugs(grid, i, j) : vHugs(grid, i, j)
  return length * (1 + CONGESTION_FACTOR * use + (hugs ? HUG_FACTOR : 0)) + OVERLAP_PENALTY * use
}

/** Отмечает участки пути занятыми, чтобы следующие рёбра обходили их по соседним дорожкам. */
function markUsed(grid: Grid, vertices: ReadonlyArray<readonly [number, number]>): void {
  for (let k = 0; k + 1 < vertices.length; k++) {
    const [i1, j1] = vertices[k]
    const [i2, j2] = vertices[k + 1]
    if (i1 === i2 && j1 === j2) continue // поворот на месте: звена нет
    if (j1 === j2) grid.hUse[j1 * grid.width + Math.min(i1, i2)]++
    else grid.vUse[Math.min(j1, j2) * grid.width + i1]++
  }
}

/**
 * Прямой выход из хэндла (от точки хэндла до начала поиска) в сетку не входит, но линия, проложенная вдоль него, выглядела бы как
 * продолжение чужого ребра. Поэтому участки сетки на выходе каждого хэндла заранее отмечаются занятыми, и другие рёбра идут мимо.
 * Собственному ребру это не мешает: его путь начинается в конце выхода и назад по нему не возвращается.
 */
function reserveCorridor(grid: Grid, end: RouteEnd, stub: Point): void {
  const i = nearestLine(grid.xs, stub.x)
  const j = nearestLine(grid.ys, stub.y)
  if (sideAxis(end.side) === 1) {
    const lo = Math.min(end.point.y, stub.y)
    const hi = Math.max(end.point.y, stub.y)
    for (let jj = 0; jj + 1 < grid.height; jj++) {
      if (grid.ys[jj + 1] > lo + EPS && grid.ys[jj] < hi - EPS) grid.vUse[jj * grid.width + i]++
    }
  } else {
    const lo = Math.min(end.point.x, stub.x)
    const hi = Math.max(end.point.x, stub.x)
    for (let ii = 0; ii + 1 < grid.width; ii++) {
      if (grid.xs[ii + 1] > lo + EPS && grid.xs[ii] < hi - EPS) grid.hUse[j * grid.width + ii]++
    }
  }
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

function nearestLine(lines: readonly number[], value: number): number {
  return indexOfValue(lines, value)
}

export interface RouteOptions {
  /** Бюджет времени на весь расчёт, мс (по умолчанию ROUTING_BUDGET_MS). */
  budgetMs?: number
  /** Источник времени в мс; подменяется в тестах, по умолчанию `performance.now()`. */
  now?: () => number
}

/** Порядок без учёта локали: `localeCompare` зависит от языка браузера, и раскладка одной схемы у разных пользователей различалась бы. */
function compareIds(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0
}

/**
 * Прокладывает маршруты для всех запросов. Ребро, для которого путь не нашёлся (хэндл зажат между узлами, исчерпан предел поиска),
 * в результат не попадает — вызывающий код рисует его прежней кривой. Если сетка слишком велика (MAX_GRID_VERTICES) или рёбер больше
 * MAX_ROUTED_EDGES, пуст весь результат. Рёбра идут от коротких к длинным, и когда бюджет времени вышел, остальные (длинные) тоже
 * остаются без маршрута: короткие связи важнее для читаемости, а длинным кривая и так привычна.
 */
export function routeEdges(nodes: readonly RouteNode[], requests: readonly RouteRequest[], options: RouteOptions = {}): Map<string, EdgeRoute> {
  const { budgetMs = ROUTING_BUDGET_MS, now = () => performance.now() } = options
  const routes = new Map<string, EdgeRoute>()
  if (requests.length === 0 || requests.length > MAX_ROUTED_EDGES) return routes
  const clock: Clock = { now, deadline: now() + budgetMs }
  const stubs = requests.flatMap((request) => [stubPoint(request.source), stubPoint(request.target)])
  const grid = buildGrid(nodes, stubs)
  if (!grid) return routes
  const scratch = createScratch(grid)
  for (const request of requests) {
    reserveCorridor(grid, request.source, stubPoint(request.source))
    reserveCorridor(grid, request.target, stubPoint(request.target))
  }

  // Короткие связи первыми: они занимают ближайшие дорожки, а длинным обходить всё равно.
  const ordered = [...requests].sort((a, b) => manhattan(a) - manhattan(b) || compareIds(a.id, b.id))
  // Связи с одинаковыми концами (параллельные линки между двумя свёрнутыми группами подключаются к одному хэндлу на каждой стороне)
  // идут одним маршрутом: у них нет повода расходиться, а разводить по дорожкам значило бы гнать копии длинными обходами. Число
  // таких связей показывает подпись «×N» (diagramEdgeLabels.ts).
  const byEnds = new Map<string, EdgeRoute | null>()
  let outOfTime = false
  for (const request of ordered) {
    const endsKey = routeEndsKey(request)
    const shared = byEnds.get(endsKey)
    if (shared !== undefined) {
      if (shared) routes.set(request.id, shared)
      continue
    }
    // Копии уже проложенного маршрута ничего не стоят и берутся даже после срока; новый поиск после срока не начинается.
    if (!outOfTime && now() > clock.deadline) outOfTime = true
    if (outOfTime) continue
    const sourceStub = stubPoint(request.source)
    const targetStub = stubPoint(request.target)
    const start = { i: nearestLine(grid.xs, sourceStub.x), j: nearestLine(grid.ys, sourceStub.y), axis: sideAxis(request.source.side) }
    // В цель путь входит вдоль оси выхода приёмника: тогда у хэндла нет лишнего излома.
    const goal = { i: nearestLine(grid.xs, targetStub.x), j: nearestLine(grid.ys, targetStub.y), axis: sideAxis(request.target.side) }
    const vertices = findPath(grid, scratch, start, goal, clock)
    if (!vertices) {
      byEnds.set(endsKey, null)
      continue
    }
    markUsed(grid, vertices)
    const points: Point[] = [
      request.source.point,
      sourceStub,
      ...vertices.map(([i, j]) => ({ x: grid.xs[i], y: grid.ys[j] })),
      targetStub,
      request.target.point,
    ]
    const route = simplifyPolyline(points)
    byEnds.set(endsKey, route)
    routes.set(request.id, route)
  }
  return routes
}

function routeEndsKey(request: RouteRequest): string {
  const { source, target } = request
  return [source.point.x, source.point.y, source.side, target.point.x, target.point.y, target.side]
    .map((v) => (typeof v === 'number' ? v.toFixed(2) : v))
    .join('|')
}

function manhattan(request: RouteRequest): number {
  return Math.abs(request.source.point.x - request.target.point.x) + Math.abs(request.source.point.y - request.target.point.y)
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
