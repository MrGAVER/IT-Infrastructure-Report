// F-07 (код-ревью main): рёбра диаграммы не проходят сквозь узлы и не ложатся друг на друга.
// Раньше ребро было кривой Безье между засечками у нижнего края узлов: внутри одного ряда сетки кривая вырождалась в горизонталь
// вдоль нижней границы, а связи между рядами шли по диагонали через чужие узлы. На схеме из 18 узлов 16 из 22 рёбер проходили сквозь узлы.
import { describe, expect, it, vi } from 'vitest'
import {
  MAX_GRID_VERTICES,
  MAX_ROUTED_EDGES,
  ROUTE_CLEARANCE,
  ROUTING_BUDGET_MS,
  roundedPolylinePath,
  routeEdges,
  routeInputsFromFlow,
  routeLabelAnchor,
  routeMatchesEnds,
  sideOfPosition,
  simplifyPolyline,
  stubPoint,
  type EdgeRoute,
  type FlowEdgeLike,
  type FlowNodeLike,
  type Point,
  type RouteNode,
  type RouteRequest,
} from '../diagramEdgeRouting'

// Геометрия автораскладки backend (services/diagram_graph.py: GRID_COLUMNS = 6, шаг 220 × 160) и узла-устройства (160 × 84, засечки портов
// вдоль нижнего края с шагом width / (ticks + 1), см. DiagramDeviceNode.vue).
const NODE_W = 160
const NODE_H = 84
const TICKS = 8

function gridNodes(count: number, columns = 6): RouteNode[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `n${index}`,
    x: (index % columns) * 220,
    y: Math.floor(index / columns) * 160,
    width: NODE_W,
    height: NODE_H,
  }))
}

/** Хэндл порта `port` на нижнем краю узла; point.y — нижний край плюс 3 px: так хэндл Vue Flow торчит из узла. */
function portEnd(node: RouteNode, port: number) {
  return { point: { x: node.x + (NODE_W / (TICKS + 1)) * (port + 1), y: node.y + node.height + 3 }, side: 'bottom' as const }
}

function link(id: string, nodes: RouteNode[], from: number, fromPort: number, to: number, toPort: number): RouteRequest {
  return { id, source: portEnd(nodes[from], fromPort), target: portEnd(nodes[to], toPort) }
}

/**
 * Связи схемы из репродукции F-07: «хребет» узла 0 ко всем, соседние пары и несколько связей «через ряд». У каждой связи свой порт на каждом
 * конце, портов у узла TICKS — как у устройства с восемью интерфейсами; связь, для которой на конце не осталось порта, не создаётся
 * (так в репродукции вышло 22 связи на 18 узлах).
 */
function reproScene(count = 18): { nodes: RouteNode[]; requests: RouteRequest[] } {
  const nodes = gridNodes(count)
  const pairs: Array<[number, number]> = []
  for (let i = 1; i < count; i++) pairs.push([0, i])
  for (let i = 1; i < count - 1; i += 2) pairs.push([i, i + 1])
  pairs.push([2, 8], [3, 9], [4, 13], [5, 12], [6, 15], [7, 16])
  const used = new Map<number, number>()
  const requests: RouteRequest[] = []
  for (const [a, b] of pairs) {
    if (a === b || b >= count || (used.get(a) ?? 0) >= TICKS || (used.get(b) ?? 0) >= TICKS) continue
    const portA = used.get(a) ?? 0
    used.set(a, portA + 1)
    const portB = used.get(b) ?? 0
    used.set(b, portB + 1)
    requests.push(link(`e${requests.length}`, nodes, a, portA, b, portB))
  }
  return { nodes, requests }
}

function segments(route: EdgeRoute): Array<[Point, Point]> {
  return route.slice(0, -1).map((point, i) => [point, route[i + 1]])
}

/** Звено лежит строго внутри прямоугольника узла (касание границы допустимо). */
function segmentEntersNode(a: Point, b: Point, node: RouteNode): boolean {
  const left = node.x
  const right = node.x + node.width
  const top = node.y
  const bottom = node.y + node.height
  if (a.x === b.x) return a.x > left && a.x < right && Math.max(a.y, b.y) > top && Math.min(a.y, b.y) < bottom
  return a.y > top && a.y < bottom && Math.max(a.x, b.x) > left && Math.min(a.x, b.x) < right
}

function routesEnteringNodes(routes: Map<string, EdgeRoute>, nodes: RouteNode[]): string[] {
  return [...routes].filter(([, route]) => segments(route).some(([a, b]) => nodes.some((node) => segmentEntersNode(a, b, node)))).map(([id]) => id)
}

function isOrthogonal(route: EdgeRoute): boolean {
  return segments(route).every(([a, b]) => a.x === b.x || a.y === b.y)
}

/** Длина, на которой два звена лежат на одной прямой одно поверх другого. */
function overlapLength(a: [Point, Point], b: [Point, Point]): number {
  const vertical = a[0].x === a[1].x && b[0].x === b[1].x && a[0].x === b[0].x
  const horizontal = a[0].y === a[1].y && b[0].y === b[1].y && a[0].y === b[0].y
  if (!vertical && !horizontal) return 0
  const axis = vertical ? 'y' : 'x'
  const lo = Math.max(Math.min(a[0][axis], a[1][axis]), Math.min(b[0][axis], b[1][axis]))
  const hi = Math.min(Math.max(a[0][axis], a[1][axis]), Math.max(b[0][axis], b[1][axis]))
  return Math.max(0, hi - lo)
}

function overlappingPairs(routes: Map<string, EdgeRoute>, minLength = 2): Array<[string, string]> {
  const entries = [...routes]
  const result: Array<[string, string]> = []
  for (let i = 0; i < entries.length; i++) {
    for (let j = i + 1; j < entries.length; j++) {
      const overlap = segments(entries[i][1]).some((sa) => segments(entries[j][1]).some((sb) => overlapLength(sa, sb) >= minLength))
      if (overlap) result.push([entries[i][0], entries[j][0]])
    }
  }
  return result
}

describe('routeEdges: обход узлов', () => {
  it('связь между соседями одного ряда не ложится на нижнюю границу узлов', () => {
    const nodes = gridNodes(2)
    const routes = routeEdges(nodes, [link('a', nodes, 0, 3, 1, 3)])
    const route = routes.get('a')!
    expect(route).toBeDefined()
    expect(isOrthogonal(route)).toBe(true)
    expect(route[0]).toEqual(portEnd(nodes[0], 3).point)
    expect(route[route.length - 1]).toEqual(portEnd(nodes[1], 3).point)
    // Раньше обе засечки на одной высоте давали прямую ровно по нижнему краю (y = bottom + 3): теперь линия уходит ниже зазора.
    const lowest = Math.max(...route.map((p) => p.y))
    expect(lowest).toBeGreaterThanOrEqual(NODE_H + ROUTE_CLEARANCE)
  })

  it('связь через ряд обходит узел посередине', () => {
    const nodes = gridNodes(3)
    const routes = routeEdges(nodes, [link('a', nodes, 0, 0, 2, 0)])
    expect(routesEnteringNodes(routes, nodes)).toEqual([])
    expect(routes.get('a')).toBeDefined()
  })

  it('связь между рядами не идёт по диагонали и не заходит в узлы промежуточного ряда', () => {
    const nodes = gridNodes(18)
    // Из верхнего ряда в нижний, ровно под ним лежит узел среднего ряда.
    const routes = routeEdges(nodes, [link('a', nodes, 2, 4, 14, 4)])
    const route = routes.get('a')!
    expect(isOrthogonal(route)).toBe(true)
    expect(routesEnteringNodes(routes, nodes)).toEqual([])
  })

  it('на схеме из репродукции F-07 (18 узлов, 22 связи) ни одно ребро не проходит сквозь узел', () => {
    const { nodes, requests } = reproScene()
    expect(requests.length).toBeGreaterThanOrEqual(20)
    const routes = routeEdges(nodes, requests)
    expect(routes.size).toBe(requests.length)
    expect(routesEnteringNodes(routes, nodes)).toEqual([])
    for (const route of routes.values()) expect(isOrthogonal(route)).toBe(true)
  })

  it('концы маршрута лежат ровно на хэндлах, а выход из хэндла прямой: первое и последнее звено перпендикулярны стороне узла', () => {
    const { nodes, requests } = reproScene()
    const routes = routeEdges(nodes, requests)
    for (const request of requests) {
      const route = routes.get(request.id)!
      expect(route[0]).toEqual(request.source.point)
      expect(route[route.length - 1]).toEqual(request.target.point)
      // Хэндлы снизу: первое и последнее звено вертикальны.
      expect(route[0].x).toBe(route[1].x)
      expect(route[route.length - 1].x).toBe(route[route.length - 2].x)
    }
  })

  it('маршруты не огибают узел ближе зазора: линия не лежит на самом узле даже в касании его границы', () => {
    const { nodes, requests } = reproScene()
    const routes = routeEdges(nodes, requests)
    for (const [id, route] of routes) {
      // Кроме выхода из собственного хэндла (первое и последнее звено), линия держится на ROUTE_CLEARANCE от любого узла.
      for (const [a, b] of segments(route).slice(1, -1)) {
        for (const node of nodes) {
          const inflated: RouteNode = {
            id: node.id,
            x: node.x - ROUTE_CLEARANCE + 0.5,
            y: node.y - ROUTE_CLEARANCE + 0.5,
            width: node.width + 2 * ROUTE_CLEARANCE - 1,
            height: node.height + 2 * ROUTE_CLEARANCE - 1,
          }
          expect(segmentEntersNode(a, b, inflated), `${id} подходит к ${node.id} ближе зазора`).toBe(false)
        }
      }
    }
  })
})

describe('routeEdges: разведение рёбер', () => {
  it('рёбра схемы из репродукции F-07 не ложатся друг на друга', () => {
    const { nodes, requests } = reproScene()
    const routes = routeEdges(nodes, requests)
    expect(overlappingPairs(routes)).toEqual([])
  })

  it('две связи между одной парой узлов (разные порты) идут разными дорожками', () => {
    const nodes = gridNodes(2)
    const routes = routeEdges(nodes, [link('a', nodes, 0, 0, 1, 0), link('b', nodes, 0, 1, 1, 1), link('c', nodes, 0, 2, 1, 2)])
    expect(routes.size).toBe(3)
    expect(overlappingPairs(routes)).toEqual([])
  })

  it('связи с одинаковыми концами (параллельные линки между свёрнутыми группами) идут одним маршрутом', () => {
    const nodes = gridNodes(2)
    const end = { source: portEnd(nodes[0], 0), target: portEnd(nodes[1], 0) }
    const routes = routeEdges(nodes, [
      { id: 'a', ...end },
      { id: 'b', ...end },
      { id: 'c', ...end },
    ])
    expect(routes.get('a')).toEqual(routes.get('b'))
    expect(routes.get('b')).toEqual(routes.get('c'))
    expect(routes.size).toBe(3)
  })

  it('результат не зависит от порядка запросов', () => {
    const { nodes, requests } = reproScene()
    const forward = routeEdges(nodes, requests)
    const backward = routeEdges(nodes, [...requests].reverse())
    for (const request of requests) expect(backward.get(request.id)).toEqual(forward.get(request.id))
  })
})

describe('routeEdges: особые случаи', () => {
  it('без запросов и без узлов — пустой результат', () => {
    expect(routeEdges([], []).size).toBe(0)
    expect(routeEdges(gridNodes(3), []).size).toBe(0)
  })

  it('хэндлы без засечек (свёрнутая группа): источник снизу, приёмник сверху — маршрут находится и не заходит в узлы', () => {
    const nodes = gridNodes(2)
    const request: RouteRequest = {
      id: 'g',
      source: { point: { x: nodes[0].x + NODE_W / 2, y: nodes[0].y + NODE_H + 3 }, side: 'bottom' },
      target: { point: { x: nodes[1].x + NODE_W / 2, y: nodes[1].y - 3 }, side: 'top' },
    }
    const routes = routeEdges(nodes, [request])
    expect(routes.get('g')).toBeDefined()
    expect(isOrthogonal(routes.get('g')!)).toBe(true)
    expect(routesEnteringNodes(routes, nodes)).toEqual([])
  })

  it('ребро узла к самому себе получает маршрут вокруг узла', () => {
    const nodes = gridNodes(1)
    const routes = routeEdges(nodes, [
      {
        id: 'loop',
        source: portEnd(nodes[0], 1),
        target: { point: { x: nodes[0].x + NODE_W / 2, y: nodes[0].y - 3 }, side: 'top' },
      },
    ])
    expect(routes.get('loop')).toBeDefined()
    expect(routesEnteringNodes(routes, nodes)).toEqual([])
  })

  it('хэндл, выход из которого упирается в соседний узел, маршрута не получает — вызывающий код нарисует кривую', () => {
    const a: RouteNode = { id: 'a', x: 0, y: 0, width: 100, height: 50 }
    const b: RouteNode = { id: 'b', x: 0, y: 52, width: 100, height: 50 } // стоит прямо под хэндлом a, внутри зазора
    const routes = routeEdges([a, b], [{ id: 'x', source: { point: { x: 50, y: 53 }, side: 'bottom' }, target: { point: { x: 50, y: 49 }, side: 'top' } }])
    expect(routes.has('x')).toBe(false)
  })

  it('слишком большая сетка: трассировка отключена, результат пуст (рёбра остаются кривыми)', () => {
    const nodes = Array.from({ length: 300 }, (_, i) => ({ id: `n${i}`, x: i * 190 + (i % 7) * 3, y: i * 130 + (i % 5) * 4, width: NODE_W, height: NODE_H }))
    const requests = [link('a', nodes, 0, 0, 299, 0)]
    // Проверка предположения теста: сетка действительно не помещается в предел.
    expect(nodes.length * 4 * nodes.length * 4).toBeGreaterThan(MAX_GRID_VERTICES)
    expect(routeEdges(nodes, requests).size).toBe(0)
  })

  it('схема из 60 узлов и 80 связей прокладывается целиком и без прохода сквозь узлы', () => {
    const nodes = gridNodes(60)
    const used = new Map<number, number>()
    const nextPort = (node: number) => {
      const port = (used.get(node) ?? 0) % TICKS
      used.set(node, (used.get(node) ?? 0) + 1)
      return port
    }
    const requests: RouteRequest[] = []
    for (let i = 0; i < 80; i++) {
      const from = (i * 7) % 60
      const to = (i * 13 + 5) % 60
      if (from !== to) requests.push(link(`e${i}`, nodes, from, nextPort(from), to, nextPort(to)))
    }
    // Проверяется геометрия, а не скорость: бюджет времени отключён, чтобы медленная машина CI не превратила тест в нестабильный.
    const routes = routeEdges(nodes, requests, { budgetMs: Number.POSITIVE_INFINITY })
    expect(routes.size).toBe(requests.length)
    expect(routesEnteringNodes(routes, nodes)).toEqual([])
  })
})

describe('routeEdges: бюджет времени и предел числа рёбер (FE-01 ревью)', () => {
  /** Схема, на которой все связи прокладываются: нужна, чтобы отличить «не успели» от «пути нет». */
  function scene(edges: number): { nodes: RouteNode[]; requests: RouteRequest[] } {
    const nodes = gridNodes(30)
    const used = new Map<number, number>()
    const nextPort = (node: number) => {
      const port = (used.get(node) ?? 0) % TICKS
      used.set(node, (used.get(node) ?? 0) + 1)
      return port
    }
    const requests: RouteRequest[] = []
    for (let i = 0; i < edges; i++) {
      const from = (i * 7) % 30
      const to = (i * 11 + 3) % 30
      if (from !== to) requests.push(link(`e${i}`, nodes, from, nextPort(from), to, nextPort(to)))
    }
    return { nodes, requests }
  }

  /** Порядок прокладки: от коротких к длинным, при равенстве — по id (так же, как в routeEdges). */
  function expectedOrder(requests: RouteRequest[]): string[] {
    const length = (r: RouteRequest) => Math.abs(r.source.point.x - r.target.point.x) + Math.abs(r.source.point.y - r.target.point.y)
    return [...requests].sort((a, b) => length(a) - length(b) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)).map((r) => r.id)
  }

  it('когда бюджет исчерпан, прокладываются только первые (самые короткие) рёбра, остальные остаются кривыми', () => {
    const { nodes, requests } = scene(40)
    const full = routeEdges(nodes, requests, { budgetMs: Number.POSITIVE_INFINITY })
    expect(full.size).toBe(requests.length) // без ограничения времени проложены все — иначе тест ничего не доказывает

    // «Часы» тикают на 1 при каждом чтении; бюджет 6 — расчёт останавливается после нескольких рёбер.
    let tick = 0
    const limited = routeEdges(nodes, requests, { budgetMs: 6, now: () => tick++ })
    expect(limited.size).toBeGreaterThan(0)
    expect(limited.size).toBeLessThan(requests.length)
    const order = expectedOrder(requests)
    const routedIds = new Set(limited.keys())
    // Проложенные рёбра — непрерывное начало списка «от коротких к длинным»: длинное не обгоняет короткое.
    expect(order.slice(0, routedIds.size).every((id) => routedIds.has(id))).toBe(true)
    // То, что успели, не отличается от полного расчёта.
    for (const [id, route] of limited) expect(route).toEqual(full.get(id))
  })

  it('бюджет, исчерпанный до первого ребра, даёт пустой результат, а не исключение', () => {
    const { nodes, requests } = scene(10)
    // Часы тикают на 1 при каждом чтении: срок = 0 + бюджет, а первая проверка перед ребром уже видит время больше срока.
    let tick = 0
    expect(routeEdges(nodes, requests, { budgetMs: 0, now: () => tick++ }).size).toBe(0)
    tick = 0
    expect(routeEdges(nodes, requests, { budgetMs: -1, now: () => tick++ }).size).toBe(0)
  })

  it('бюджет не вмешивается, пока время не вышло: результат малой схемы тот же, что без ограничения', () => {
    const { nodes, requests } = reproScene()
    const unlimited = routeEdges(nodes, requests, { budgetMs: Number.POSITIVE_INFINITY })
    const budgeted = routeEdges(nodes, requests, { now: () => 0 })
    expect(budgeted.size).toBe(requests.length)
    for (const request of requests) expect(budgeted.get(request.id)).toEqual(unlimited.get(request.id))
  })

  it('время проверяется и внутри поиска одного ребра: часы, «ушедшие вперёд» посреди A*, прерывают расчёт', () => {
    // Цель — узел внутри замкнутого кольца из четырёх узлов: пути нет, и A* перебирает всю доступную сетку поля из 60 узлов, то есть
    // делает несколько тысяч раскрытий. Часы читаются: раз при задании срока, раз перед ребром, далее — раз на каждые 4096 раскрытий.
    const ring: RouteNode[] = [
      { id: 'top', x: 80, y: 60, width: 240, height: 40 },
      { id: 'bottom', x: 80, y: 300, width: 240, height: 40 },
      { id: 'left', x: 80, y: 60, width: 40, height: 280 },
      { id: 'right', x: 280, y: 60, width: 40, height: 280 },
    ]
    const inner: RouteNode = { id: 'inner', x: 160, y: 150, width: 80, height: 60 }
    const field: RouteNode[] = Array.from({ length: 60 }, (_, i) => ({
      id: `f${i}`,
      x: 600 + (i % 6) * 220,
      y: Math.floor(i / 6) * 160,
      width: NODE_W,
      height: NODE_H,
    }))
    const nodes = [...ring, inner, ...field]
    const sealed: RouteRequest = {
      id: 'sealed',
      source: { point: { x: field[0].x + NODE_W / 2, y: field[0].y + NODE_H + 3 }, side: 'bottom' },
      target: { point: { x: inner.x + inner.width / 2, y: inner.y + inner.height + 3 }, side: 'bottom' },
    }

    let readsWhenRunning = 0
    expect(routeEdges(nodes, [sealed], { budgetMs: 10, now: () => (++readsWhenRunning, 0) }).size).toBe(0)
    expect(readsWhenRunning).toBeGreaterThan(3) // поиск идёт до конца: сверок с часами несколько

    let readsWhenExpired = 0
    const expired = () => (++readsWhenExpired <= 2 ? 0 : 1_000_000)
    expect(routeEdges(nodes, [sealed], { budgetMs: 10, now: expired }).size).toBe(0)
    expect(readsWhenExpired).toBe(3) // первая же сверка внутри поиска увидела «время вышло» и прервала его
  })

  it(`схема с числом рёбер больше MAX_ROUTED_EDGES (${MAX_ROUTED_EDGES}) не трассируется: результат пуст`, () => {
    const nodes = gridNodes(2)
    const request = link('a', nodes, 0, 0, 1, 0)
    const many = Array.from({ length: MAX_ROUTED_EDGES + 1 }, (_, i) => ({ ...request, id: `e${i}` }))
    expect(routeEdges(nodes, many).size).toBe(0)
    // Ровно на пределе трассировка ещё работает.
    expect(routeEdges(nodes, many.slice(0, MAX_ROUTED_EDGES)).size).toBe(MAX_ROUTED_EDGES)
  })

  it('бюджет по умолчанию — ROUTING_BUDGET_MS, предел рёбер — MAX_ROUTED_EDGES', () => {
    expect(ROUTING_BUDGET_MS).toBe(250)
    expect(MAX_ROUTED_EDGES).toBe(400)
  })

  it('порядок прокладки не зависит от локали браузера: localeCompare не используется', () => {
    const spy = vi.spyOn(String.prototype, 'localeCompare')
    try {
      const { nodes, requests } = reproScene()
      routeEdges(nodes, requests)
      expect(spy).not.toHaveBeenCalled()
    } finally {
      spy.mockRestore()
    }
  })
})

// Раздел 5 ревью (frontend, п. 1): регрессионный замер времени. Тесты выше проверяют геометрию и бюджет на подменённых часах; настоящую
// скорость не проверял никто, а она зависит от весов штрафов (BEND_PENALTY, CONGESTION_FACTOR, OVERLAP_PENALTY) — правка веса может
// незаметно умножить время расчёта. Замер идёт без бюджета времени (budgetMs: Infinity): иначе расчёт обрывался бы на 250 мс и тест был
// бы зелёным при любой деградации. Тег `slow` — как маркер `slow` у отчётов в backend: по умолчанию тест выполняется, исключить его
// можно ключом `vitest run --tags-filter '!slow'` (npm run test:fast).
const BENCH_NODES = 60
const BENCH_EDGES = 150
/** Потолок на самом медленном ожидаемом CI. Замер ревью: ≈ 310 мс на одном ядре параллельно с другой нагрузкой — запас втрое. */
const BENCH_CEILING_MS = 1000
const BENCH_RUNS = 3

/** Детерминированный генератор (LCG): та же схема при каждом запуске и на любой машине. */
function seededRandom(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    return state / 0x100000000
  }
}

/** Схема из «случайных» пар узлов (как замеры FE-01): у узла не больше TICKS связей, у каждой связи свой порт на каждом конце. */
function benchScene(): { nodes: RouteNode[]; requests: RouteRequest[] } {
  const nodes = gridNodes(BENCH_NODES)
  const random = seededRandom(20260508)
  const used = new Array<number>(BENCH_NODES).fill(0)
  const requests: RouteRequest[] = []
  while (requests.length < BENCH_EDGES) {
    const a = Math.floor(random() * BENCH_NODES)
    const b = Math.floor(random() * BENCH_NODES)
    if (a === b || used[a] >= TICKS || used[b] >= TICKS) continue
    requests.push(link(`e${requests.length}`, nodes, a, used[a]++, b, used[b]++))
  }
  return { nodes, requests }
}

describe('routeEdges: регрессионный замер времени (раздел 5 ревью, frontend п. 1)', () => {
  it(`${BENCH_NODES} узлов и ${BENCH_EDGES} рёбер: полный расчёт без бюджета — не дольше ${BENCH_CEILING_MS} мс`, { tags: ['slow'] }, () => {
    const { nodes, requests } = benchScene()
    // Лучшее из нескольких прогонов: разовый скачок (сборка мусора, соседний процесс на общем CI-раннере) не должен давать красный тест,
    // а настоящая деградация замедляет и лучший прогон.
    const timings: number[] = []
    let routed = 0
    for (let run = 0; run < BENCH_RUNS; run++) {
      const started = performance.now()
      routed = routeEdges(nodes, requests, { budgetMs: Number.POSITIVE_INFINITY }).size
      timings.push(performance.now() - started)
    }
    // Замер полезной работы: ребро без маршрута (отказ поиска) делало бы расчёт «быстрым» за счёт результата.
    expect(routed).toBe(BENCH_EDGES)
    const best = Math.min(...timings)
    expect(best, `прогоны, мс: ${timings.map((t) => t.toFixed(0)).join(', ')}`).toBeLessThanOrEqual(BENCH_CEILING_MS)
  })

  it('схема замера детерминирована и укладывается в ограничения размера', () => {
    const first = benchScene()
    const second = benchScene()
    expect(second.requests).toEqual(first.requests)
    expect(first.requests).toHaveLength(BENCH_EDGES)
    expect(BENCH_EDGES).toBeLessThanOrEqual(MAX_ROUTED_EDGES)
  })
})

describe('stubPoint', () => {
  it('отступает наружу на ROUTE_CLEARANCE в сторону выхода', () => {
    const point = { x: 10, y: 20 }
    expect(stubPoint({ point, side: 'bottom' })).toEqual({ x: 10, y: 20 + ROUTE_CLEARANCE })
    expect(stubPoint({ point, side: 'top' })).toEqual({ x: 10, y: 20 - ROUTE_CLEARANCE })
    expect(stubPoint({ point, side: 'left' })).toEqual({ x: 10 - ROUTE_CLEARANCE, y: 20 })
    expect(stubPoint({ point, side: 'right' })).toEqual({ x: 10 + ROUTE_CLEARANCE, y: 20 })
  })
})

describe('simplifyPolyline', () => {
  it('убирает повторяющиеся точки и точки на прямой', () => {
    const points = [
      { x: 0, y: 0 },
      { x: 0, y: 0 },
      { x: 0, y: 10 },
      { x: 0, y: 20 },
      { x: 30, y: 20 },
      { x: 60, y: 20 },
      { x: 60, y: 0 },
    ]
    expect(simplifyPolyline(points)).toEqual([
      { x: 0, y: 0 },
      { x: 0, y: 20 },
      { x: 60, y: 20 },
      { x: 60, y: 0 },
    ])
  })

  it('оставляет концы ломаной из двух точек', () => {
    expect(
      simplifyPolyline([
        { x: 1, y: 1 },
        { x: 5, y: 1 },
      ]),
    ).toEqual([
      { x: 1, y: 1 },
      { x: 5, y: 1 },
    ])
  })
})

describe('roundedPolylinePath', () => {
  it('прямая: только M и L', () => {
    expect(
      roundedPolylinePath([
        { x: 0, y: 0 },
        { x: 0, y: 40 },
      ]),
    ).toBe('M 0 0 L 0 40')
  })

  it('угол скругляется дугой радиуса, не больше половины звена', () => {
    const d = roundedPolylinePath(
      [
        { x: 0, y: 0 },
        { x: 0, y: 40 },
        { x: 40, y: 40 },
      ],
      8,
    )
    expect(d).toBe('M 0 0 L 0 32 Q 0 40 8 40 L 40 40')
    // Короткие звенья (10 px) дают радиус 5, чтобы дуги соседних углов не налезали.
    const tight = roundedPolylinePath(
      [
        { x: 0, y: 0 },
        { x: 0, y: 10 },
        { x: 10, y: 10 },
      ],
      8,
    )
    expect(tight).toBe('M 0 0 L 0 5 Q 0 10 5 10 L 10 10')
  })

  it('пустая ломаная — пустой путь', () => {
    expect(roundedPolylinePath([])).toBe('')
  })
})

describe('routeMatchesEnds', () => {
  const route: EdgeRoute = [
    { x: 10, y: 10 },
    { x: 10, y: 50 },
    { x: 70, y: 50 },
    { x: 70, y: 10 },
  ]

  it('маршрут годен, пока его концы на текущих хэндлах', () => {
    expect(routeMatchesEnds(route, { x: 10, y: 10 }, { x: 70, y: 10 })).toBe(true)
    expect(routeMatchesEnds(route, { x: 10.3, y: 10 }, { x: 70, y: 9.8 })).toBe(true)
  })

  it('после сдвига узла (перетаскивание) маршрут недействителен', () => {
    expect(routeMatchesEnds(route, { x: 30, y: 10 }, { x: 70, y: 10 })).toBe(false)
    expect(routeMatchesEnds(route, { x: 10, y: 10 }, { x: 70, y: 40 })).toBe(false)
  })

  it('вырожденный маршрут недействителен', () => {
    expect(routeMatchesEnds([{ x: 0, y: 0 }], { x: 0, y: 0 }, { x: 0, y: 0 })).toBe(false)
  })
})

describe('routeLabelAnchor', () => {
  it('центральная подпись — в середине самого длинного звена', () => {
    const anchor = routeLabelAnchor([
      { x: 0, y: 0 },
      { x: 0, y: 20 },
      { x: 100, y: 20 },
      { x: 100, y: 0 },
    ])
    expect(anchor).toEqual({ x: 50, y: 20 })
  })
})

describe('sideOfPosition', () => {
  it('значения Position Vue Flow превращаются в сторону узла; неизвестное — низ', () => {
    expect(sideOfPosition('top')).toBe('top')
    expect(sideOfPosition('left')).toBe('left')
    expect(sideOfPosition('right')).toBe('right')
    expect(sideOfPosition('bottom')).toBe('bottom')
    expect(sideOfPosition('???')).toBe('bottom')
  })
})

describe('routeInputsFromFlow: те же точки, что у Vue Flow', () => {
  function flowNode(id: string, x: number, y: number, extra: Partial<FlowNodeLike> = {}): FlowNodeLike {
    return { id, computedPosition: { x, y }, dimensions: { width: NODE_W, height: NODE_H }, ...extra }
  }

  it('хэндл по id: центр нижней кромки хэндла (x + width / 2, y + height), смещённый на позицию узла', () => {
    const source = flowNode('a', 100, 200, {
      handleBounds: { source: [{ id: 'port-1-source', position: 'bottom', x: 40, y: 81, width: 5, height: 5 }] },
    })
    const target = flowNode('b', 400, 200, {
      handleBounds: { target: [{ id: 'port-2-target', position: 'bottom', x: 60, y: 81, width: 5, height: 5 }] },
    })
    const edge: FlowEdgeLike = { id: 'e', source: 'a', target: 'b', sourceHandle: 'port-1-source', targetHandle: 'port-2-target' }
    const { nodes, requests } = routeInputsFromFlow([source, target], [edge])
    expect(nodes).toEqual([
      { id: 'a', x: 100, y: 200, width: NODE_W, height: NODE_H },
      { id: 'b', x: 400, y: 200, width: NODE_W, height: NODE_H },
    ])
    expect(requests).toEqual([{ id: 'e', source: { point: { x: 142.5, y: 286 }, side: 'bottom' }, target: { point: { x: 462.5, y: 286 }, side: 'bottom' } }])
  })

  it('без id берётся первый хэндл; у приёмника без хэндлов — середина верхней стороны узла, у источника — нижней', () => {
    const source = flowNode('a', 0, 0, { handleBounds: { source: [{ id: 'x', position: 'bottom', x: 10, y: 80, width: 6, height: 6 }] } })
    const target = flowNode('b', 300, 0)
    const { requests } = routeInputsFromFlow([source, target], [{ id: 'e', source: 'a', target: 'b' }])
    expect(requests[0].source.point).toEqual({ x: 13, y: 86 })
    expect(requests[0].target).toEqual({ point: { x: 380, y: 0 }, side: 'top' })
    const bare = routeInputsFromFlow([flowNode('a', 0, 0), flowNode('b', 300, 0)], [{ id: 'e', source: 'a', target: 'b' }])
    expect(bare.requests[0].source).toEqual({ point: { x: 80, y: NODE_H }, side: 'bottom' })
  })

  it('неизвестный id хэндла даёт тот же запасной вариант, что у Vue Flow', () => {
    const source = flowNode('a', 0, 0, { handleBounds: { source: [{ id: 'port-0-source', position: 'bottom', x: 10, y: 80, width: 6, height: 6 }] } })
    const { requests } = routeInputsFromFlow([source, flowNode('b', 300, 0)], [{ id: 'e', source: 'a', target: 'b', sourceHandle: 'port-31-source' }])
    expect(requests[0].source).toEqual({ point: { x: 80, y: NODE_H }, side: 'bottom' })
  })

  it('неизмеренные узлы (нулевой размер) и рёбра к отсутствующим узлам пропускаются', () => {
    const measured = flowNode('a', 0, 0)
    const unmeasured = flowNode('b', 300, 0, { dimensions: { width: 0, height: 0 } })
    const { nodes, requests } = routeInputsFromFlow(
      [measured, unmeasured],
      [
        { id: 'to-unmeasured', source: 'a', target: 'b' },
        { id: 'to-missing', source: 'a', target: 'zzz' },
      ],
    )
    expect(nodes.map((n) => n.id)).toEqual(['a'])
    expect(requests).toEqual([])
  })

  it('end-to-end: данные Vue Flow → маршруты, концы маршрута совпадают с хэндлами', () => {
    const route = (x: number) =>
      flowNode(`n${x}`, x, 0, {
        handleBounds: {
          source: [{ id: 's', position: 'bottom', x: 20, y: 81, width: 5, height: 5 }],
          target: [{ id: 't', position: 'bottom', x: 40, y: 81, width: 5, height: 5 }],
        },
      })
    const flowNodes = [route(0), route(220), route(440)]
    const { nodes, requests } = routeInputsFromFlow(flowNodes, [{ id: 'e', source: 'n0', target: 'n440', sourceHandle: 's', targetHandle: 't' }])
    const routes = routeEdges(nodes, requests)
    const found = routes.get('e')!
    expect(routeMatchesEnds(found, requests[0].source.point, requests[0].target.point)).toBe(true)
    expect(routesEnteringNodes(routes, nodes)).toEqual([])
  })
})
