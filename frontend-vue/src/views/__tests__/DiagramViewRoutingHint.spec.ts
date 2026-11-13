// ИБ-04 (ревью merge/review-r3-executors): расчёт маршрутов рёбер ограничен по времени, и когда бюджет вышел, часть связей рисуется прежней
// кривой. Раньше экран об этом молчал; теперь рядом с названием диаграммы появляется подсказка «часть связей проложена упрощённо».
// Реальный <VueFlow> в jsdom не поднять, поэтому useVueFlow подменён (как в DiagramViewInitialView.spec.ts), а расчёт маршрутов — моком:
// тест проверяет связку «результат расчёта → подсказка», а не геометрию (её проверяет diagramEdgeRouting.spec.ts).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

const flow = vi.hoisted(() => ({
  handler: null as null | (() => void),
  nodes: { value: [] as unknown[] },
  routeEdgesWithStatus: vi.fn(),
}))

vi.mock('@vue-flow/core', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@vue-flow/core')>()),
  useVueFlow: () => ({
    fitView: vi.fn(),
    setViewport: vi.fn(),
    onNodesInitialized: (cb: () => void) => {
      flow.handler = cb
    },
    viewport: { value: { x: 0, y: 0, zoom: 1 } },
    getNodes: flow.nodes,
  }),
}))

vi.mock('../../utils/diagramEdgeRouting', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../utils/diagramEdgeRouting')>()),
  routeEdgesWithStatus: flow.routeEdgesWithStatus,
}))

import DiagramView from '../DiagramView.vue'
import type { SavedDiagramDetail } from '../../api/diagrams'

const diagram: SavedDiagramDetail = {
  id: 'd1',
  name: 'Диаграмма 1',
  description: null,
  scope_filter: {},
  group_by: 'structural_unit',
  collapse_threshold: 20,
  last_export_format: null,
  created_at: null,
  updated_at: null,
  nodes: [],
  edges: [],
  viewport: null,
}

async function mountScreen() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(diagram))),
  )
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/diagrams', name: 'diagrams', component: { template: '<div/>' } },
      { path: '/diagrams/:id', name: 'diagram-detail', component: { template: '<div/>' } },
    ],
  })
  await router.push('/diagrams/d1')
  const wrapper = mount(DiagramView, { global: { plugins: [router], stubs: { VueFlow: true, DiagramDetailPanel: true, DiagramExportPanel: true } } })
  await flushPromises()
  return wrapper
}

/** Событие nodesInitialized ставит таймер пересчёта маршрутов (60 мс): прокручиваем его и даём Vue перерисоваться. */
async function recalcRoutes() {
  flow.handler!()
  await vi.advanceTimersByTimeAsync(100)
  await flushPromises()
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  flow.handler = null
  flow.nodes.value = []
  flow.routeEdgesWithStatus.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('ИБ-04: DiagramView — подсказка об упрощённой прокладке связей', () => {
  it('по умолчанию подсказки нет', async () => {
    const wrapper = await mountScreen()
    expect(wrapper.find('.routing-hint').exists()).toBe(false)
  })

  it('расчёт уложился в бюджет (degraded = false): подсказки нет', async () => {
    const wrapper = await mountScreen()
    vi.useFakeTimers()
    flow.routeEdgesWithStatus.mockReturnValue({ routes: new Map(), degraded: false })
    await recalcRoutes()
    expect(flow.routeEdgesWithStatus).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.routing-hint').exists()).toBe(false)
  })

  it('бюджет вышел (degraded = true): появляется подсказка с role="status", а следующий полный расчёт её убирает', async () => {
    const wrapper = await mountScreen()
    vi.useFakeTimers()
    flow.routeEdgesWithStatus.mockReturnValue({ routes: new Map(), degraded: true })
    await recalcRoutes()
    const hint = wrapper.find('.routing-hint')
    expect(hint.exists()).toBe(true)
    expect(hint.attributes('role')).toBe('status')
    expect(hint.text()).toBe('часть связей проложена упрощённо')

    flow.routeEdgesWithStatus.mockReturnValue({ routes: new Map(), degraded: false })
    await recalcRoutes()
    expect(wrapper.find('.routing-hint').exists()).toBe(false)
  })
})
