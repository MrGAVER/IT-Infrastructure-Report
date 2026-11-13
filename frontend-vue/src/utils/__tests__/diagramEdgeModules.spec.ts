// B-08: diagramEdgeRouting.ts разделён на «геометрию» (diagramEdgeGeometry.ts), подключение к Vue Flow (diagramEdgeFlow.ts), кучу
// (minHeap.ts) и собственно выбор маршрута. Наружу всё осталось доступно из diagramEdgeRouting.ts — это публичный вход, которым
// пользуются DiagramView, DiagramConnectionEdge и тесты. Здесь закреплены две вещи: состав публичного входа и направление зависимостей.
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import * as facade from '../diagramEdgeRouting'
import * as flow from '../diagramEdgeFlow'
import * as geometry from '../diagramEdgeGeometry'

const here = dirname(fileURLToPath(import.meta.url))
const sourceOf = (name: string): string => readFileSync(resolve(here, '..', name), 'utf-8')

describe('B-08: публичный вход diagramEdgeRouting.ts', () => {
  it('значения, которые экспортировал единый файл до разделения, на месте (ничего не потеряно и не добавлено лишнего)', () => {
    expect(Object.keys(facade).sort()).toEqual(
      [
        'EDGE_ROUTES_KEY',
        'MAX_GRID_VERTICES',
        'MAX_ROUTED_EDGES',
        'ROUTE_CLEARANCE',
        'ROUTE_LANE_STEP',
        'ROUTING_BUDGET_MS',
        'roundedPolylinePath',
        'routeEdges',
        'routeEdgesWithStatus',
        'routeInputsFromFlow',
        'routeLabelAnchor',
        'routeMatchesEnds',
        'sideOfPosition',
        'simplifyPolyline',
        'stubPoint',
      ].sort(),
    )
  })

  it('реэкспорты — те же самые объекты, что в модулях (а не копии): один ключ provide/inject, одна функция на всех', () => {
    expect(facade.EDGE_ROUTES_KEY).toBe(flow.EDGE_ROUTES_KEY)
    expect(facade.routeInputsFromFlow).toBe(flow.routeInputsFromFlow)
    expect(facade.stubPoint).toBe(geometry.stubPoint)
    expect(facade.simplifyPolyline).toBe(geometry.simplifyPolyline)
    expect(facade.roundedPolylinePath).toBe(geometry.roundedPolylinePath)
    expect(facade.routeLabelAnchor).toBe(geometry.routeLabelAnchor)
    expect(facade.routeMatchesEnds).toBe(geometry.routeMatchesEnds)
    expect(facade.sideOfPosition).toBe(geometry.sideOfPosition)
    expect(facade.ROUTE_CLEARANCE).toBe(geometry.ROUTE_CLEARANCE)
  })
})

describe('B-08: слои не зависят друг от друга по кругу', () => {
  const importsOf = (name: string): string[] => [...sourceOf(name).matchAll(/from '(\.\/[^']+)'/g)].map((m) => m[1])

  it('геометрия не знает ни про выбор маршрута, ни про Vue Flow-адаптер, ни про кучу', () => {
    expect(importsOf('diagramEdgeGeometry.ts')).toEqual([])
  })

  it('адаптер Vue Flow зависит только от геометрии', () => {
    expect(importsOf('diagramEdgeFlow.ts')).toEqual(['./diagramEdgeGeometry'])
  })

  it('куча не зависит ни от чего', () => {
    expect(importsOf('minHeap.ts')).toEqual([])
  })

  it('выбор маршрута зависит от геометрии, адаптера (реэкспорт) и кучи — и не наоборот', () => {
    expect([...new Set(importsOf('diagramEdgeRouting.ts'))].sort()).toEqual(['./diagramEdgeFlow', './diagramEdgeGeometry', './minHeap'])
  })
})
