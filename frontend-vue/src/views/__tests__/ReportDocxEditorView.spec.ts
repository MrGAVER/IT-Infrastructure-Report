import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ReportDocxEditorView from '../ReportDocxEditorView.vue'
import type { DocxConfig, ReportEntityMeta, ReportTemplate } from '../../api/types'

const pushMock = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: 't-1' } }),
  useRouter: () => ({ push: pushMock }),
}))

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

const entitiesFixture: ReportEntityMeta[] = [
  {
    key: 'devices',
    label: 'Физические устройства',
    fields: [{ name: 'system_name', label: 'Системное имя', type: 'String', is_foreign_key: false }],
    to_one: [],
    to_many: [],
  },
]

function docxConfig(): DocxConfig {
  return {
    blocks: [
      { type: 'heading', text: 'Отчёт по устройствам', level: 1 },
      { type: 'paragraph', text: 'Вводный абзац', align: 'left' },
    ],
  }
}

function templateFixture(overrides: Partial<ReportTemplate> = {}): ReportTemplate {
  return {
    id: 't-1',
    name: 'Акт передачи',
    description: 'описание',
    format: 'docx',
    config: docxConfig() as unknown as Record<string, unknown>,
    created_at: null,
    updated_at: null,
    ...overrides,
  }
}

function stubFetch(template: ReportTemplate = templateFixture()) {
  return vi.fn(async (url: string) => {
    if (url.includes('/report-templates/t-1') && !url.includes('/versions')) return jsonResponse(template)
    if (url.includes('/report-builder/entities')) return jsonResponse(entitiesFixture)
    return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
  })
}

beforeEach(() => {
  vi.stubGlobal(
    'confirm',
    vi.fn(() => true),
  )
  pushMock.mockClear()
})

describe('ReportDocxEditorView.vue — загрузка', () => {
  it('грузит шаблон и метаданные сущностей, показывает блоки', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    expect(wrapper.findAll('.block-card')).toHaveLength(2)
    expect((wrapper.find('.top-bar input[type="text"]').element as HTMLInputElement).value).toBe('Акт передачи')
  })

  it('шаблон в формате xlsx — вместо блоков показывает пояснение', async () => {
    vi.stubGlobal('fetch', stubFetch(templateFixture({ format: 'xlsx' })))
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    expect(wrapper.find('.block-card').exists()).toBe(false)
    expect(wrapper.text()).toContain('Excel (.xlsx)')
  })

  it('пустой config.blocks — заводит один блок-заголовок по умолчанию', async () => {
    vi.stubGlobal('fetch', stubFetch(templateFixture({ config: { blocks: [] } as unknown as Record<string, unknown> })))
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    expect(wrapper.findAll('.block-card')).toHaveLength(1)
    expect(wrapper.text()).toContain('Заголовок')
  })

  it('ошибка загрузки показывается вместо редактора', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'Шаблон не найден' }, 404)),
    )
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    expect(wrapper.text()).toContain('Шаблон не найден')
    expect(wrapper.find('.block-card').exists()).toBe(false)
  })
})

describe('ReportDocxEditorView.vue — блоки', () => {
  it('добавляет блок каждого типа', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    await wrapper.findAll('.add-block-bar button')[2].trigger('click') // "+ Таблица"
    expect(wrapper.findAll('.block-card')).toHaveLength(3)
    expect(wrapper.text()).toContain('Заголовок таблицы')
  })

  it('нельзя удалить единственный оставшийся блок', async () => {
    vi.stubGlobal('fetch', stubFetch(templateFixture({ config: { blocks: [{ type: 'page_break' }] } as unknown as Record<string, unknown> })))
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    await wrapper.find('.icon-btn.danger').trigger('click')
    expect(wrapper.findAll('.block-card')).toHaveLength(1)
  })

  it('удаление блока запрашивает подтверждение', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    await wrapper.find('.icon-btn.danger').trigger('click')
    expect(confirm).toHaveBeenCalled()
    expect(wrapper.findAll('.block-card')).toHaveLength(1)
  })

  it('перемещение блока вниз меняет порядок, границы блокируют кнопки', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    const firstCardButtons = wrapper.findAll('.block-card')[0].findAll('.block-actions button')
    expect((firstCardButtons[0].element as HTMLButtonElement).disabled).toBe(true) // "↑" на первом блоке недоступна

    await firstCardButtons[1].trigger('click') // "↓"
    const cards = wrapper.findAll('.block-card')
    expect(cards[0].text()).toContain('Абзац')
    expect(cards[1].text()).toContain('Заголовок')
  })

  it('редактирование текста заголовка обновляет данные блока', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    const headingInput = wrapper.find('.block-card input[type="text"]')
    await headingInput.setValue('Новый заголовок')
    expect((headingInput.element as HTMLInputElement).value).toBe('Новый заголовок')
  })

  it('уровень заголовка меняется через select', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    const levelSelect = wrapper.find('.block-card select')
    await levelSelect.setValue('3')
    expect((levelSelect.element as HTMLSelectElement).value).toBe('3')
  })

  it('блок "Таблица" рендерит DocxTableBlockEditor и пробрасывает обновления', async () => {
    vi.stubGlobal(
      'fetch',
      stubFetch(
        templateFixture({
          config: { blocks: [{ type: 'table', title: '', root_entity: '', filters: [], columns: [] }] } as unknown as Record<string, unknown>,
        }),
      ),
    )
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    const entitySelect = wrapper.find('.block-card .row select')
    await entitySelect.setValue('devices')
    expect((entitySelect.element as HTMLSelectElement).value).toBe('devices')
  })
})

describe('ReportDocxEditorView.vue — сохранение', () => {
  it('без названия показывает ошибку и не отправляет PUT', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    await wrapper.find('.top-bar input[type="text"]').setValue('')
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await wrapper.find('.top-bar button.btn-primary').trigger('click')

    expect(wrapper.text()).toContain('Укажите название шаблона')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('сохраняет через PUT /report-templates/{id} с текущим содержимым blocks', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    const putMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(templateFixture()))
    vi.stubGlobal('fetch', putMock)
    await wrapper.find('.top-bar button.btn-primary').trigger('click')
    await flushPromises()

    const [url, init] = putMock.mock.calls[0]
    expect(url).toBe('/api/v1/report-templates/t-1')
    expect(init?.method).toBe('PUT')
    const body = JSON.parse(init!.body as string)
    expect(body.format).toBe('docx')
    expect(body.config.blocks[0].text).toBe('Отчёт по устройствам')
  })

  it('ошибка сервера при сохранении показывается пользователю', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'В шаблоне не задано ни одного блока' }, 422)),
    )
    await wrapper.find('.top-bar button.btn-primary').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('не задано ни одного блока')
  })
})

describe('ReportDocxEditorView.vue — предпросмотр', () => {
  it('кнопка "Предпросмотр таблиц" запрашивает POST /report-builder/preview с format=docx и показывает секции', async () => {
    const calls: Array<{ url: string; body: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/report-builder/preview')) {
          calls.push({ url, body: init?.body ? JSON.parse(init.body as string) : undefined })
          return jsonResponse({ sections: [{ title: 'Устройства', headers: ['Имя'], rows: [['srv-01']], total: 1 }] })
        }
        return stubFetch()(url)
      }),
    )
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    await wrapper.find('.preview-trigger').trigger('click')
    await flushPromises()

    expect(calls[0].body).toMatchObject({ format: 'docx' })
    expect(wrapper.text()).toContain('srv-01')
    expect(wrapper.text()).toContain('показано записей: 1')
  })

  it('без блоков-таблиц показывает пояснение вместо пустого списка секций', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/report-builder/preview')) return jsonResponse({ sections: [] })
        return stubFetch()(url)
      }),
    )
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    await wrapper.find('.preview-trigger').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('нет блоков-таблиц для предпросмотра')
  })

  it('ошибка секции показывается внутри неё, а не как общая ошибка запроса', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/report-builder/preview')) return jsonResponse({ sections: [{ title: 'Устройства', error: 'не задана исходная сущность' }] })
        return stubFetch()(url)
      }),
    )
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    await wrapper.find('.preview-trigger').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('не задана исходная сущность')
  })

  it('ошибка сервера при построении предпросмотра показывается', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/report-builder/preview')) return jsonResponse({ detail: 'В шаблоне не задано ни одного блока' }, 422)
        return stubFetch()(url)
      }),
    )
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    await wrapper.find('.preview-trigger').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('не задано ни одного блока')
  })

  it('закрытие панели предпросмотра скрывает её', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/report-builder/preview')) return jsonResponse({ sections: [] })
        return stubFetch()(url)
      }),
    )
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    await wrapper.find('.preview-trigger').trigger('click')
    await flushPromises()
    expect(wrapper.find('.preview-panel').exists()).toBe(true)

    await wrapper.find('.preview-panel-head .icon-btn').trigger('click')
    expect(wrapper.find('.preview-panel').exists()).toBe(false)
  })
})

describe('ReportDocxEditorView.vue — навигация', () => {
  it('"К списку шаблонов" переходит на /report-templates', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportDocxEditorView)
    await flushPromises()

    await wrapper.find('.top-bar button.btn-secondary').trigger('click')
    expect(pushMock).toHaveBeenCalledWith('/report-templates')
  })
})
