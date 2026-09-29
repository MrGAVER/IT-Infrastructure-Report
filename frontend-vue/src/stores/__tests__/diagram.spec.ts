import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useDiagramStore } from '../diagram'
import type { SavedDiagramDetail } from '../../api/diagrams'

function sampleDiagram(overrides: Partial<SavedDiagramDetail> = {}): SavedDiagramDetail {
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
    nodes: [
      { id: 'dev-1', type: 'device', label: 'sw-01', serial_number: 'SN-1', system_name: 'sw-01', category_id: null, manufacturer: null, model: null, ip_addresses: [], icon: { mode: 'generated', shape: 'switch', color: '#4f7cff', glyph: 'M1 4h3v4H1z', manufacturer_label: '', model_label: '' }, x: 0, y: 0 },
    ],
    edges: [],
    viewport: { zoom: 1, pan_x: 0, pan_y: 0 },
    ...overrides,
  }
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('useDiagramStore', () => {
  it('load() успешно подгружает диаграмму', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(sampleDiagram())))
    const store = useDiagramStore()
    await store.load('d1')
    expect(store.diagram?.id).toBe('d1')
    expect(store.nodes).toHaveLength(1)
    expect(store.error).toBeNull()
  })

  it('load() при ошибке сети выставляет error и оставляет diagram пустым', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Диаграмма не найдена' }, 404)))
    const store = useDiagramStore()
    await store.load('missing')
    expect(store.diagram).toBeNull()
    expect(store.error).toBe('Диаграмма не найдена')
  })

  it('moveNode обновляет позицию локально сразу и откладывает сохранение (debounce)', async () => {
    vi.useFakeTimers()
    const putCalls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'PUT') putCalls.push(url)
        return jsonResponse({ status: 'ok' })
      }),
    )
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    store.moveNode('dev-1', 111, 222)
    expect(store.diagram!.nodes[0].x).toBe(111) // локальный отклик — мгновенно, без ожидания
    expect(putCalls).toHaveLength(0) // но сеть ещё не дёрнута

    await vi.advanceTimersByTimeAsync(600)
    expect(putCalls).toEqual(['/api/v1/diagrams/d1/layout'])
    vi.useRealTimers()
  })

  it('moveNode вызванный дважды подряд шлёт запрос один раз (debounce схлопывает повторы)', async () => {
    vi.useFakeTimers()
    const putCalls: unknown[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'PUT') putCalls.push(JSON.parse(init!.body as string))
        return jsonResponse({ status: 'ok' })
      }),
    )
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    store.moveNode('dev-1', 10, 10)
    await vi.advanceTimersByTimeAsync(200)
    store.moveNode('dev-1', 20, 20)
    await vi.advanceTimersByTimeAsync(600)

    expect(putCalls).toHaveLength(1)
    expect((putCalls[0] as { node_positions: Record<string, { x: number; y: number }> }).node_positions['dev-1']).toEqual({ x: 20, y: 20 })
    vi.useRealTimers()
  })

  it('toggleGroup сохраняет состояние группы и пересобирает граф', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        calls.push(url)
        if (url.includes('/groups/')) return jsonResponse({ group_key: 'building:x', is_collapsed: false, device_count: 3, custom_threshold: null })
        if (url.includes('/regenerate')) return jsonResponse(sampleDiagram({ nodes: [] }))
        return jsonResponse(sampleDiagram())
      }),
    )
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    await store.toggleGroup('building:x', false)
    expect(calls[0]).toBe('/api/v1/diagrams/d1/groups/building%3Ax')
    expect(calls[1]).toBe('/api/v1/diagrams/d1/regenerate')
    expect(store.nodes).toHaveLength(0) // локальное состояние заменено пересобранным графом
  })

  it('regenerate сохраняет текущий viewport, даже если бэкенд его не возвращает', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ ...sampleDiagram(), viewport: null })))
    const store = useDiagramStore()
    store.diagram = sampleDiagram({ viewport: { zoom: 2.5, pan_x: 40, pan_y: -10 } })

    await store.regenerate()
    expect(store.diagram?.viewport).toEqual({ zoom: 2.5, pan_x: 40, pan_y: -10 })
  })

  it('exportAs скачивает blob с именем файла из Content-Disposition', async () => {
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:mock'), revokeObjectURL: vi.fn() })
    const clickSpy = vi.fn()
    const originalCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = originalCreateElement(tag)
      if (tag === 'a') el.click = clickSpy
      return el
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response('<svg/>', {
            status: 200,
            headers: { 'Content-Disposition': 'attachment; filename="______.svg"; filename*=UTF-8\'\'%D0%94.svg' },
          }),
      ),
    )
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    await store.exportAs('svg')
    expect(clickSpy).toHaveBeenCalled()
    expect(store.exporting).toBeNull() // сброшено в finally
    // Сервер уже сохранил last_export_format — сплит-кнопка экспорта должна отразить это сразу,
    // без отдельного перезапроса диаграммы (см. DiagramExportPanel.vue).
    expect(store.diagram?.last_export_format).toBe('svg')
  })

  it('rename() обновляет имя диаграммы в сторе', async () => {
    const calls: { url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'PUT') calls.push({ url, body: JSON.parse(init!.body as string) })
        return jsonResponse({ id: 'd1', name: 'Новое имя', description: null, group_by: 'structural_unit', collapse_threshold: 20 })
      }),
    )
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    await store.rename('Новое имя')
    expect(calls).toEqual([{ url: '/api/v1/diagrams/d1/rename', body: { name: 'Новое имя' } }])
    expect(store.diagram?.name).toBe('Новое имя')
  })

  it('rename() при ошибке (напр. занятое имя) выбрасывает исключение и не трогает имя в сторе', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Диаграмма с таким названием уже существует' }, 409)))
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    await expect(store.rename('Занятое имя')).rejects.toThrow('Диаграмма с таким названием уже существует')
    expect(store.diagram?.name).toBe('Диаграмма 1') // не изменилось
  })

  it('remove() очищает текущую диаграмму', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ status: 'ok' })))
    const store = useDiagramStore()
    store.diagram = sampleDiagram()
    await store.remove()
    expect(store.diagram).toBeNull()
  })
})

afterEach(() => {
  vi.useRealTimers()
})
