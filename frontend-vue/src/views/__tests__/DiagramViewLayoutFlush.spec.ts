// B-09: сдвиг узла уходит на сервер с задержкой 600 мс (debounce в сторе диаграммы); при уходе с экрана
// диаграммы он должен быть отправлен сразу, а не потеряться вместе с размонтированным компонентом.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import DiagramView from '../DiagramView.vue'
import { useDiagramStore } from '../../stores/diagram'
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
  nodes: [
    { id: 'dev-1', type: 'device', label: 'sw-01', serial_number: 'SN-1', system_name: 'sw-01', category_id: null, manufacturer: null, model: null, ip_addresses: [], icon: { mode: 'generated', shape: 'switch', color: '#4f7cff', glyph: 'M1 4h3v4H1z', manufacturer_label: '', model_label: '' }, x: 0, y: 0 },
  ],
  edges: [],
  viewport: { zoom: 1, pan_x: 0, pan_y: 0 },
}

let calls: Array<{ method: string; url: string; body: unknown }>

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ method: init?.method ?? 'GET', url, body: init?.body ? JSON.parse(init.body as string) : undefined })
      return new Response(JSON.stringify(init?.method === 'PUT' ? { status: 'ok' } : diagram))
    }),
  )
})

afterEach(() => {
  vi.useRealTimers()
})

async function mountScreen() {
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

const putCalls = () => calls.filter((c) => c.method === 'PUT')

describe('B-09: DiagramView — уход с экрана сохраняет раскладку', () => {
  it('размонтирование сразу отправляет несохранённый сдвиг узла, а таймер потом не шлёт дубль', async () => {
    const wrapper = await mountScreen()
    const store = useDiagramStore()
    expect(store.diagram?.id).toBe('d1')

    vi.useFakeTimers()
    store.moveNode('dev-1', 50, 60)
    expect(putCalls()).toHaveLength(0) // окно debounce открыто

    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(0)
    expect(putCalls()).toEqual([
      { method: 'PUT', url: '/api/v1/diagrams/d1/layout', body: { node_positions: { 'dev-1': { x: 50, y: 60 } } } },
    ])

    await vi.advanceTimersByTimeAsync(2000)
    expect(putCalls()).toHaveLength(1)
  })

  it('размонтирование без перемещений запросов не шлёт', async () => {
    const wrapper = await mountScreen()
    calls.length = 0

    wrapper.unmount()
    await flushPromises()

    expect(calls).toEqual([])
  })
})
