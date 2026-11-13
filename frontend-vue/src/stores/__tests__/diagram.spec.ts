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
      {
        id: 'dev-1',
        type: 'device',
        label: 'sw-01',
        serial_number: 'SN-1',
        system_name: 'sw-01',
        category_id: null,
        manufacturer: null,
        model: null,
        ip_addresses: [],
        icon: { mode: 'generated', shape: 'switch', color: '#4f7cff', glyph: 'M1 4h3v4H1z', manufacturer_label: '', model_label: '' },
        x: 0,
        y: 0,
      },
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
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(sampleDiagram())),
    )
    const store = useDiagramStore()
    await store.load('d1')
    expect(store.diagram?.id).toBe('d1')
    expect(store.nodes).toHaveLength(1)
    expect(store.error).toBeNull()
  })

  it('load() при ошибке сети выставляет error и оставляет diagram пустым', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'Диаграмма не найдена' }, 404)),
    )
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
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ ...sampleDiagram(), viewport: null })),
    )
    const store = useDiagramStore()
    store.diagram = sampleDiagram({ viewport: { zoom: 2.5, pan_x: 40, pan_y: -10 } })

    await store.regenerate()
    expect(store.diagram?.viewport).toEqual({ zoom: 2.5, pan_x: 40, pan_y: -10 })
  })

  it('exportAs скачивает blob с именем файла из Content-Disposition', async () => {
    // saveBlob освобождает blob-ссылку по таймеру (ИБ-02): реальный таймер на 30 с пережил бы тест.
    vi.useFakeTimers()
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:mock'), revokeObjectURL: vi.fn() })
    const clickSpy = vi.fn()
    const anchors: HTMLAnchorElement[] = []
    const originalCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = originalCreateElement(tag)
      if (tag === 'a') {
        el.click = clickSpy
        anchors.push(el as HTMLAnchorElement)
      }
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

    try {
      await store.exportAs('svg')
    } finally {
      vi.useRealTimers()
    }
    expect(clickSpy).toHaveBeenCalled()
    // ИБ-01: имя файла — настоящее (из filename*), а не ASCII-запасное «______.svg».
    expect(anchors[0].download).toBe('Д.svg')
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
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'Диаграмма с таким названием уже существует' }, 409)),
    )
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    await expect(store.rename('Занятое имя')).rejects.toThrow('Диаграмма с таким названием уже существует')
    expect(store.diagram?.name).toBe('Диаграмма 1') // не изменилось
  })

  it('remove() очищает текущую диаграмму', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ status: 'ok' })),
    )
    const store = useDiagramStore()
    store.diagram = sampleDiagram()
    await store.remove()
    expect(store.diagram).toBeNull()
  })
})

describe('useDiagramStore — отложенное сохранение раскладки не теряется (B-09)', () => {
  type Call = { method: string; url: string; body: unknown }

  /** fetch-заглушка: пишет все запросы по порядку; d2 отдаёт как другую диаграмму. */
  function setupFetch(options: { failDelete?: boolean } = {}) {
    const calls: Call[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ method, url, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'DELETE') return options.failDelete ? jsonResponse({ detail: 'Сбой удаления' }, 500) : jsonResponse({ status: 'ok' })
        if (method === 'PUT') return jsonResponse({ status: 'ok' })
        if (url.endsWith('/regenerate')) return jsonResponse(sampleDiagram())
        if (url.endsWith('/diagrams/d2')) return jsonResponse(sampleDiagram({ id: 'd2', name: 'Диаграмма 2' }))
        return jsonResponse(sampleDiagram())
      }),
    )
    return {
      calls,
      puts: () => calls.filter((c) => c.method === 'PUT'),
    }
  }

  it('moveNode → load(другой id) до истечения 600 мс: PUT уходит один раз, на id исходной диаграммы, с её позициями', async () => {
    vi.useFakeTimers()
    const net = setupFetch()
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    store.moveNode('dev-1', 111, 222)
    await vi.advanceTimersByTimeAsync(200) // окно debounce ещё открыто
    expect(net.puts()).toHaveLength(0)

    await store.load('d2')
    await vi.advanceTimersByTimeAsync(2000) // таймер не должен «выстрелить» повторно уже по новой диаграмме

    expect(net.puts()).toEqual([{ method: 'PUT', url: '/api/v1/diagrams/d1/layout', body: { node_positions: { 'dev-1': { x: 111, y: 222 } } } }])
    expect(store.diagram?.id).toBe('d2')
    // порядок: сохранение исходной диаграммы ушло раньше, чем загрузилась новая
    expect(net.calls.map((c) => `${c.method} ${c.url}`)).toEqual(['PUT /api/v1/diagrams/d1/layout', 'GET /api/v1/diagrams/d2'])
  })

  it('flushLayoutSave без изменений запроса не шлёт; повторный flush после отправки — тоже', async () => {
    vi.useFakeTimers()
    const net = setupFetch()
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    await store.flushLayoutSave() // ничего не планировалось
    expect(net.calls).toHaveLength(0)

    store.moveNode('dev-1', 5, 6)
    await store.flushLayoutSave()
    expect(net.puts()).toHaveLength(1)

    await store.flushLayoutSave() // повторно, без новых перемещений
    await vi.advanceTimersByTimeAsync(2000) // и таймер был снят — сам тоже не отправит
    expect(net.puts()).toHaveLength(1)
  })

  it('после срабатывания таймера flushLayoutSave ничего не дублирует', async () => {
    vi.useFakeTimers()
    const net = setupFetch()
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    store.moveNode('dev-1', 7, 8)
    await vi.advanceTimersByTimeAsync(600)
    expect(net.puts()).toHaveLength(1)

    await store.flushLayoutSave()
    expect(net.puts()).toHaveLength(1)
  })

  it('persistLayout не отправляет раскладку, если диаграмма в сторе уже другая (чужие позиции на чужой id)', async () => {
    vi.useFakeTimers()
    const net = setupFetch()
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    store.moveNode('dev-1', 1, 2)
    store.diagram = sampleDiagram({ id: 'd2' }) // подмена в обход load() — защита должна сработать и здесь
    await vi.advanceTimersByTimeAsync(600)

    expect(net.puts()).toHaveLength(0)
  })

  it('регенерация диаграммы сначала отправляет несохранённые перемещения, а не затирает их данными сервера', async () => {
    vi.useFakeTimers()
    const net = setupFetch()
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    store.moveNode('dev-1', 30, 40)
    await store.regenerate()

    expect(net.calls.map((c) => `${c.method} ${c.url}`)).toEqual(['PUT /api/v1/diagrams/d1/layout', 'POST /api/v1/diagrams/d1/regenerate'])
    expect(net.puts()[0].body).toEqual({ node_positions: { 'dev-1': { x: 30, y: 40 } } })
  })

  it('remove() снимает отложенное сохранение: после удаления диаграммы раскладка не отправляется', async () => {
    vi.useFakeTimers()
    const net = setupFetch()
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    store.moveNode('dev-1', 9, 9)
    await store.remove()
    await vi.advanceTimersByTimeAsync(2000)

    expect(net.puts()).toHaveLength(0)
    expect(store.error).toBeNull()
  })

  it('remove(): если удалить не удалось, перемещения возвращаются в очередь и всё же сохраняются', async () => {
    vi.useFakeTimers()
    const net = setupFetch({ failDelete: true })
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    store.moveNode('dev-1', 9, 9)
    await expect(store.remove()).rejects.toThrow('Сбой удаления')
    expect(store.diagram?.id).toBe('d1') // диаграмма осталась открытой

    await vi.advanceTimersByTimeAsync(600)
    expect(net.puts()).toHaveLength(1)
  })

  it('ошибка отправки при flush попадает в store.error и не выбрасывается из load()', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'PUT') return jsonResponse({ detail: 'Нет связи с сервером' }, 500)
        return jsonResponse(sampleDiagram({ id: 'd2' }))
      }),
    )
    const store = useDiagramStore()
    store.diagram = sampleDiagram()

    store.moveNode('dev-1', 1, 1)
    await expect(store.load('d2')).resolves.toBeUndefined()
    expect(store.diagram?.id).toBe('d2') // переход на новую диаграмму не заблокирован сбоем сохранения старой
  })
})

afterEach(() => {
  vi.useRealTimers()
})
