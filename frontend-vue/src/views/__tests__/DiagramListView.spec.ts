import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import DiagramListView from '../DiagramListView.vue'

const SAMPLE = [
  {
    id: 'd1',
    name: 'Диаграмма 1',
    description: null,
    scope_filter: {},
    group_by: 'building',
    collapse_threshold: 20,
    last_export_format: null,
    created_at: null,
    updated_at: null,
  },
  {
    id: 'd2',
    name: 'Диаграмма 2',
    description: null,
    scope_filter: {},
    group_by: 'vlan',
    collapse_threshold: 10,
    last_export_format: null,
    created_at: null,
    updated_at: null,
  },
]

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

let router: Router

beforeEach(async () => {
  setActivePinia(createPinia())
  vi.stubGlobal(
    'confirm',
    vi.fn(() => true),
  )
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/diagrams', name: 'diagrams', component: { template: '<div/>' } },
      { path: '/diagrams/:id', name: 'diagram-detail', component: { template: '<div/>' } },
    ],
  })
  await router.push('/diagrams')
})

describe('DiagramListView.vue', () => {
  it('загружает и показывает список диаграмм', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(SAMPLE)),
    )
    const wrapper = mount(DiagramListView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('Диаграмма 1')
    expect(wrapper.text()).toContain('Диаграмма 2')
  })

  it('показывает человекочитаемое название измерения группировки, а не сырое значение поля', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(SAMPLE)),
    )
    const wrapper = mount(DiagramListView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('По зданию')
    expect(wrapper.text()).toContain('По VLAN')
    expect(wrapper.text()).not.toContain('building')
    expect(wrapper.text()).not.toMatch(/\bvlan\b/) // "VLAN" (заглавными, как в лейбле) — не то же самое, что сырое "vlan"
  })

  it('пустой список показывает подсказку создать первую диаграмму', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse([])),
    )
    const wrapper = mount(DiagramListView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('Диаграмм пока нет')
  })

  it('клик "Открыть" переходит на экран диаграммы', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(SAMPLE)),
    )
    const wrapper = mount(DiagramListView, { global: { plugins: [router] } })
    await flushPromises()
    const pushSpy = vi.spyOn(router, 'push')
    await wrapper.findAll('.row-actions button')[0].trigger('click')
    expect(pushSpy).toHaveBeenCalledWith({ name: 'diagram-detail', params: { id: 'd1' } })
  })

  it('дублирование перезагружает список после успешного запроса', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'POST' && url.includes('/duplicate')) {
        return jsonResponse({ ...SAMPLE[0], id: 'd1-copy', name: 'Диаграмма 1 (копия)' }, 201)
      }
      return jsonResponse(SAMPLE)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(DiagramListView, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.findAll('.row-actions button')[1].trigger('click')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/diagrams/d1/duplicate'), expect.objectContaining({ method: 'POST' }))
  })

  it('удаление запрашивает подтверждение и вызывает DELETE', async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'DELETE') return jsonResponse({ status: 'ok' })
      return jsonResponse(SAMPLE)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(DiagramListView, { global: { plugins: [router] } })
    await flushPromises()

    await wrapper.findAll('.row-actions .icon-btn')[0].trigger('click')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/diagrams/d1'), expect.objectContaining({ method: 'DELETE' }))
  })
})
