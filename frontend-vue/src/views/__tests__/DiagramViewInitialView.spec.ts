// UI-01 (ревью 2.158.0): граф вписывается в холст по событию nodesInitialized (когда у узлов уже есть размеры), а не в
// requestAnimationFrame сразу после установки узлов. Реальный <VueFlow> в jsdom не поднять (нет ResizeObserver и раскладки),
// поэтому useVueFlow подменён: тест перехватывает обработчик события и проверяет, что и когда он вызывает.
//
// R2-02 (ревью merge/review-f06-stage2-f05-executors): обработчик nodesInitialized ставит таймер пересчёта маршрутов рёбер (60 мс),
// а тот читает getNodes.value. Раньше в моке getNodes не было, а обёртки не размонтировались, поэтому таймер срабатывал уже после
// конца теста и бросал TypeError вне теста («Unhandled Errors», код возврата vitest 1 — только под нагрузкой). Теперь мок отдаёт
// getNodes, как настоящий useVueFlow, а каждая смонтированная обёртка снимается в afterEach: onBeforeUnmount делает clearTimeout.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

const flow = vi.hoisted(() => ({
  fitView: vi.fn(),
  setViewport: vi.fn(),
  handler: null as null | (() => void),
  // getNodes в настоящем useVueFlow — реактивная ссылка на массив измеренных узлов.
  nodes: { value: [] as unknown[] },
}))

vi.mock('@vue-flow/core', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@vue-flow/core')>()),
  useVueFlow: () => ({
    fitView: flow.fitView,
    setViewport: flow.setViewport,
    onNodesInitialized: (cb: () => void) => {
      flow.handler = cb
    },
    viewport: { value: { x: 0, y: 0, zoom: 1 } },
    getNodes: flow.nodes,
  }),
}))

import DiagramView from '../DiagramView.vue'
import type { DiagramViewport, SavedDiagramDetail } from '../../api/diagrams'

function diagramWith(viewport: DiagramViewport | null): SavedDiagramDetail {
  return {
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
    viewport,
  }
}

const mounted: VueWrapper[] = []

async function mountScreen(viewport: DiagramViewport | null) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(diagramWith(viewport)))),
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
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}

const nextFrame = () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  flow.fitView.mockReset()
  flow.setViewport.mockReset()
  flow.handler = null
  flow.nodes.value = []
})

afterEach(() => {
  // Размонтирование срабатывает onBeforeUnmount экрана → clearTimeout(routeTimer): таймер пересчёта маршрутов не переживает тест.
  mounted.splice(0).forEach((wrapper) => wrapper.unmount())
})

describe('UI-01: DiagramView — начальный вид холста', () => {
  it('загрузка сама граф не вписывает: fitView ждёт события nodesInitialized', async () => {
    await mountScreen(null)
    await nextFrame()
    expect(flow.fitView).not.toHaveBeenCalled()
    expect(flow.handler).toBeTypeOf('function')
  })

  it('без сохранённого вида по событию граф вписывается с полями 10 % и масштабом не больше 1', async () => {
    await mountScreen(null)
    flow.handler!()
    expect(flow.fitView).toHaveBeenCalledWith({ padding: 0.1, maxZoom: 1 })
    expect(flow.setViewport).not.toHaveBeenCalled()
  })

  it('сохранённый вид выигрывает: вписывания нет, вид восстанавливается', async () => {
    await mountScreen({ zoom: 0.5, pan_x: 120, pan_y: -40 })
    flow.handler!()
    expect(flow.setViewport).toHaveBeenCalledWith({ x: 120, y: -40, zoom: 0.5 })
    expect(flow.fitView).not.toHaveBeenCalled()
  })

  it('событие nodesInitialized приходит при каждой замене узлов, но вид применяется один раз за загрузку', async () => {
    await mountScreen(null)
    flow.handler!()
    flow.handler!() // например, после разворачивания группы: пользовательский масштаб не сбрасывается
    expect(flow.fitView).toHaveBeenCalledTimes(1)
  })
})
