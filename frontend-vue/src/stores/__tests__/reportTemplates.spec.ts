import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useReportTemplatesStore } from '../reportTemplates'
import type { ReportTemplate } from '../../api/types'

function template(overrides: Partial<ReportTemplate>): ReportTemplate {
  return { id: 't-x', name: 'template', description: null, format: 'xlsx', config: {}, created_at: null, updated_at: null, ...overrides }
}

const fixtureItems: ReportTemplate[] = [
  template({ id: 't-1', name: 'Реестр устройств', description: 'Инвентаризация физических устройств' }),
  template({ id: 't-2', name: 'Акт передачи', description: null, format: 'docx' }),
]

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('useReportTemplatesStore', () => {
  it('загружает шаблоны через GET /report-templates (голый массив, без items/total)', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(fixtureItems)))
    vi.stubGlobal('fetch', fetchMock)

    const store = useReportTemplatesStore()
    await store.ensureLoaded()

    expect(store.all).toHaveLength(2)
    expect(store.loaded).toBe(true)
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/report-templates', expect.anything())
  })

  it('ensureLoaded не перезапрашивает данные повторно', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(fixtureItems)))
    vi.stubGlobal('fetch', fetchMock)

    const store = useReportTemplatesStore()
    await store.ensureLoaded()
    await store.ensureLoaded()

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('фильтрует по названию и описанию, пустой поиск возвращает все', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(fixtureItems))),
    )
    const store = useReportTemplatesStore()
    await store.ensureLoaded()

    store.search = 'реестр'
    expect(store.filtered.map((t) => t.id)).toEqual(['t-1'])

    store.search = 'инвентаризация'
    expect(store.filtered.map((t) => t.id)).toEqual(['t-1'])

    store.search = 'акт'
    expect(store.filtered.map((t) => t.id)).toEqual(['t-2'])

    store.search = ''
    expect(store.filtered).toHaveLength(2)
  })

  it('при ошибке сети выставляет error и не считается loaded', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('Internal Server Error', { status: 500 })),
    )
    const store = useReportTemplatesStore()
    await store.ensureLoaded()

    expect(store.error).toBeTruthy()
    expect(store.loaded).toBe(false)
    expect(store.all).toEqual([])
  })
})
