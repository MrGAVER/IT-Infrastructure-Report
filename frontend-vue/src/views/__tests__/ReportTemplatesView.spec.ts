import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ReportTemplatesView from '../ReportTemplatesView.vue'
import { useReportTemplatesStore } from '../../stores/reportTemplates'
import type { ReportTemplate } from '../../api/types'

const pushMock = vi.fn()
vi.mock('vue-router', () => ({ useRouter: () => ({ push: pushMock }) }))

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

const templatesFixture: ReportTemplate[] = [
  { id: 't-1', name: 'Реестр устройств', description: 'Инвентаризация', format: 'xlsx', config: {}, created_at: null, updated_at: '2026-02-01T10:00:00Z' },
  { id: 't-2', name: 'Акт передачи', description: null, format: 'docx', config: {}, created_at: null, updated_at: null },
]

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  vi.stubGlobal('confirm', vi.fn(() => true))
  pushMock.mockClear()
})

describe('ReportTemplatesView.vue', () => {
  it('грузит и показывает список шаблонов с форматом и описанием', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(templatesFixture)))
    const wrapper = mount(ReportTemplatesView)
    await flushPromises()

    expect(wrapper.text()).toContain('Реестр устройств')
    expect(wrapper.text()).toContain('Инвентаризация')
    expect(wrapper.text()).toContain('Акт передачи')
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
  })

  it('пустой список — строка-заглушка вместо таблицы данных', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse([])))
    const wrapper = mount(ReportTemplatesView)
    await flushPromises()
    expect(wrapper.text()).toContain('Шаблоны не найдены')
  })

  it('"Новый шаблон" открывает форму создания (не редактирования)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(templatesFixture)))
    const wrapper = mount(ReportTemplatesView)
    await flushPromises()

    await wrapper.find('.filter-bar button.btn-primary').trigger('click')
    expect(wrapper.text()).toContain('Новый шаблон отчёта')
  })

  it('"Переименовать" открывает форму с уже загруженным шаблоном', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(templatesFixture)))
    const wrapper = mount(ReportTemplatesView)
    await flushPromises()

    await wrapper.find('[aria-label="Переименовать"]').trigger('click')
    expect(wrapper.text()).toContain('Переименовать шаблон')
    // .modal — иначе find() подхватил бы строку поиска на самом экране (тоже input[type="text"]).
    expect(wrapper.find('.modal input[type="text"]').element).toHaveProperty('value', 'Реестр устройств')
  })

  it('после сохранения формы список перезагружается и модалка закрывается', async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'PUT') return jsonResponse({ ...templatesFixture[0], name: 'Обновлён' })
      return jsonResponse(templatesFixture)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ReportTemplatesView)
    await flushPromises()

    await wrapper.find('[aria-label="Переименовать"]').trigger('click')
    await wrapper.find('.modal-foot button.btn-primary').trigger('click')
    await flushPromises()

    expect(wrapper.find('.modal-head h2').exists()).toBe(false)
    // reload() после сохранения — список перечитан заново (изначальный + ещё раз).
    const templateGetCalls = fetchMock.mock.calls.filter(([url, init]) => url === '/api/v1/report-templates' && (init?.method ?? 'GET') === 'GET')
    expect(templateGetCalls.length).toBeGreaterThanOrEqual(2)
  })

  it('"История версий" открывает модалку версий для нужного шаблона', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/versions')) return jsonResponse([])
        return jsonResponse(templatesFixture)
      }),
    )
    const wrapper = mount(ReportTemplatesView)
    await flushPromises()

    await wrapper.findAll('[aria-label="История версий"]')[1].trigger('click') // второй шаблон ("Акт передачи")
    await flushPromises()
    expect(wrapper.text()).toContain('История версий «Акт передачи»')
  })

  it('"Дублировать" вызывает POST .../duplicate и перечитывает список', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'POST' && url.includes('/duplicate')) return jsonResponse({ ...templatesFixture[0], id: 't-3' }, 201)
      return jsonResponse(templatesFixture)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ReportTemplatesView)
    await flushPromises()

    await wrapper.find('[aria-label="Дублировать"]').trigger('click')
    await flushPromises()

    expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/report-templates/t-1/duplicate')).toBe(true)
  })

  it('"Сформировать" запрашивает генерацию и не падает на скачивании (jsdom href)', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'POST' && url.includes('/generate')) {
        return jsonResponse({ file_name: 'registry.xlsx', download_url: '/api/v1/reports/download/registry.xlsx' })
      }
      return jsonResponse(templatesFixture)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ReportTemplatesView)
    await flushPromises()

    await wrapper.find('[aria-label="Сформировать"]').trigger('click')
    await flushPromises()

    expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/report-templates/t-1/generate')).toBe(true)
  })

  it('"Удалить" запрашивает подтверждение и после DELETE перечитывает список', async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'DELETE') return jsonResponse({ status: 'ok' })
      return jsonResponse(templatesFixture)
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ReportTemplatesView)
    await flushPromises()

    await wrapper.find('[aria-label="Удалить"]').trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalled()
    expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/report-templates/t-1' && init?.method === 'DELETE')).toBe(true)
  })

  it('отказ от подтверждения удаления — DELETE не отправляется', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false))
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(templatesFixture))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ReportTemplatesView)
    await flushPromises()

    await wrapper.find('[aria-label="Удалить"]').trigger('click')
    await flushPromises()

    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
  })

  it('поиск фильтрует список по названию/описанию через store.search', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(templatesFixture)))
    const wrapper = mount(ReportTemplatesView)
    await flushPromises()

    const store = useReportTemplatesStore()
    store.search = 'акт'
    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(1)
    expect(rows[0].text()).toContain('Акт передачи')
  })

  it('"Открыть в конструкторе" для xlsx-шаблона переходит в редактор по id', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(templatesFixture)))
    const wrapper = mount(ReportTemplatesView)
    await flushPromises()

    await wrapper.findAll('[aria-label="Открыть в конструкторе"]')[0].trigger('click') // t-1, xlsx
    expect(pushMock).toHaveBeenCalledWith('/report-templates/t-1/editor')
  })

  it('"Открыть в конструкторе" для docx-шаблона переходит в docx-редактор по id', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(templatesFixture)))
    const wrapper = mount(ReportTemplatesView)
    await flushPromises()

    await wrapper.findAll('[aria-label="Открыть в конструкторе"]')[1].trigger('click') // t-2, docx
    expect(pushMock).toHaveBeenCalledWith('/report-templates/t-2/editor-docx')
  })
})
