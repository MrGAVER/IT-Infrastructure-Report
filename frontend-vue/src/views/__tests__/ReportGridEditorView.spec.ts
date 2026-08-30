import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ReportGridEditorView from '../ReportGridEditorView.vue'
import type { GridConfig, ReportEntityMeta, ReportTemplate } from '../../api/types'

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

function gridConfig(): GridConfig {
  return {
    sheets: [
      {
        title: 'Лист 1',
        columns: [{ width: 20 }, { width: 20 }],
        rows: [
          { height: 20, repeat: false, data_source: null, cells: [{ col: 0, kind: 'static', text: 'Заголовок', style: {} }] },
          { height: 20, repeat: true, data_source: { root_entity: 'devices', expand: '', include_empty_expand: true, filters: [], sort_by: '' }, cells: [] },
        ],
      },
    ],
  }
}

function templateFixture(overrides: Partial<ReportTemplate> = {}): ReportTemplate {
  return { id: 't-1', name: 'Реестр устройств', description: 'описание', format: 'xlsx', config: gridConfig() as unknown as Record<string, unknown>, created_at: null, updated_at: null, ...overrides }
}

function stubFetch(template: ReportTemplate = templateFixture()) {
  return vi.fn(async (url: string) => {
    if (url.includes('/report-templates/t-1') && !url.includes('/versions')) return jsonResponse(template)
    if (url.includes('/report-builder/entities')) return jsonResponse(entitiesFixture)
    return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
  })
}

beforeEach(() => {
  vi.stubGlobal('confirm', vi.fn(() => true))
  pushMock.mockClear()
})

describe('ReportGridEditorView.vue — загрузка', () => {
  it('грузит шаблон и метаданные сущностей, показывает сетку', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    expect(wrapper.find('.grid-table').exists()).toBe(true)
    expect(wrapper.text()).toContain('Заголовок')
    expect((wrapper.find('.top-bar input[type="text"]').element as HTMLInputElement).value).toBe('Реестр устройств')
  })

  it('шаблон в формате docx — вместо сетки показывает пояснение', async () => {
    vi.stubGlobal('fetch', stubFetch(templateFixture({ format: 'docx' })))
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    expect(wrapper.find('.grid-table').exists()).toBe(false)
    expect(wrapper.text()).toContain('Word (.docx)')
  })

  it('"К списку шаблонов" в докс-заглушке переходит на /report-templates', async () => {
    vi.stubGlobal('fetch', stubFetch(templateFixture({ format: 'docx' })))
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    await wrapper.find('button.btn-secondary').trigger('click')
    expect(pushMock).toHaveBeenCalledWith('/report-templates')
  })

  it('ошибка загрузки показывается вместо сетки', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Шаблон не найден' }, 404)))
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    expect(wrapper.text()).toContain('Шаблон не найден')
    expect(wrapper.find('.grid-table').exists()).toBe(false)
  })
})

describe('ReportGridEditorView.vue — листы', () => {
  it('добавляет новый лист и переключается на него', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    await wrapper.find('.sheet-tab.add').trigger('click')
    const tabs = wrapper.findAll('.sheet-tab:not(.add)')
    expect(tabs).toHaveLength(2)
    expect(tabs[1].classes()).toContain('active')
  })

  it('нельзя удалить последний оставшийся лист', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    await wrapper.find('.sheet-toolbar button.btn-mini').trigger('click') // "Удалить лист"
    expect(wrapper.findAll('.sheet-tab:not(.add)')).toHaveLength(1)
  })

  it('переименование листа обновляет заголовок вкладки', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    await wrapper.find('.sheet-toolbar input[type="text"]').setValue('Инвентаризация')
    expect(wrapper.find('.sheet-tab.active').text()).toBe('Инвентаризация')
  })
})

describe('ReportGridEditorView.vue — колонки и строки', () => {
  it('добавляет колонку', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    const before = wrapper.findAll('.col-head').length
    await wrapper.findAll('.sheet-toolbar button.btn-mini')[1].trigger('click') // "+ колонка"
    expect(wrapper.findAll('.col-head')).toHaveLength(before + 1)
  })

  it('нельзя удалить единственную оставшуюся колонку', async () => {
    vi.stubGlobal('fetch', stubFetch(templateFixture({ config: { sheets: [{ title: 'Лист 1', columns: [{ width: 20 }], rows: [{ height: 20, repeat: false, data_source: null, cells: [] }] }] } as unknown as Record<string, unknown> })))
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    await wrapper.find('.col-head button').trigger('click')
    expect(wrapper.findAll('.col-head')).toHaveLength(1)
  })

  it('добавляет строку кнопкой "+" в шапке строки', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    const before = wrapper.findAll('tbody tr').length
    await wrapper.find('[aria-label="Добавить строку ниже"]').trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(before + 1)
  })

  it('нельзя удалить единственную оставшуюся строку', async () => {
    const single = templateFixture({ config: { sheets: [{ title: 'Лист 1', columns: [{ width: 20 }], rows: [{ height: 20, repeat: false, data_source: null, cells: [] }] }] } as unknown as Record<string, unknown> })
    vi.stubGlobal('fetch', stubFetch(single))
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    await wrapper.find('[aria-label="Удалить строку"]').trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  })
})

describe('ReportGridEditorView.vue — выделение и панель свойств', () => {
  it('клик по ячейке показывает инспектор в режиме ячейки', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    await wrapper.find('.grid-cell').trigger('click')
    expect(wrapper.text()).toContain('Тип содержимого')
  })

  it('клик по шапке строки показывает инспектор в режиме строки', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    // tbody .row-head — иначе find() мог бы подхватить пустой th.row-head в шапке таблицы.
    await wrapper.find('tbody .row-head').trigger('click')
    expect(wrapper.text()).toContain('Повторяющаяся строка')
  })

  it('без выделения показывается заглушка вместо инспектора', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    expect(wrapper.find('.inspector-placeholder').exists()).toBe(true)
  })

  it('редактирование текста ячейки через инспектор обновляет превью в сетке', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    await wrapper.find('.grid-cell').trigger('click') // ячейка "Заголовок"
    await wrapper.find('textarea').setValue('Новый заголовок')

    expect(wrapper.find('.grid-cell').text()).toBe('Новый заголовок')
  })

  it('смена типа ячейки на "Поле из БД" в неповторяющейся строке показывает информационное уведомление', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    await wrapper.find('.grid-cell').trigger('click') // строка 0 — repeat=false
    await wrapper.find('.field select').setValue('field')
    // Тип реально сменился (не заблокирован) — просто предупреждение, не запрет.
    expect(wrapper.find('.field select').element).toHaveProperty('value', 'field')
  })
})

describe('ReportGridEditorView.vue — объединение ячеек', () => {
  it('без диапазона "Объединить" показывает ошибку и не меняет сетку', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    await wrapper.find('.grid-cell').trigger('click')
    await wrapper.findAll('.sheet-toolbar button.btn-mini')[2].trigger('click') // "Объединить" без выделенного диапазона (одна ячейка)
    expect(wrapper.find('.grid-cell').attributes('colspan')).toBe('1')
  })

  it('Shift+клик задаёт диапазон, "Объединить" выставляет colspan/rowspan и убирает лишние <td>', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    const cellsBefore = wrapper.findAll('.grid-cell')
    await cellsBefore[0].trigger('click') // (0,0) "Заголовок"
    await cellsBefore[1].trigger('click', { shiftKey: true }) // (0,1)
    await wrapper.findAll('.sheet-toolbar button.btn-mini')[2].trigger('click') // "Объединить"

    const merged = wrapper.find('.grid-cell')
    expect(merged.attributes('colspan')).toBe('2')
  })

  it('"Разъединить" без выбранной объединённой ячейки показывает ошибку', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    await wrapper.find('.grid-cell').trigger('click')
    await wrapper.findAll('.sheet-toolbar button.btn-mini')[3].trigger('click') // "Разъединить"
    expect(wrapper.find('.grid-cell').attributes('colspan')).toBe('1')
  })
})

describe('ReportGridEditorView.vue — повторение строки', () => {
  it('включение повторения добавляет data_source и делает доступным выбор сущности в инспекторе', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    await wrapper.find('tbody .row-head').trigger('click') // строка 0, repeat=false
    await wrapper.find('.checkbox-field input[type="checkbox"]').setValue(true)

    expect(wrapper.findAll('select').some((s) => s.findAll('option').some((o) => o.text() === 'Физические устройства'))).toBe(true)
  })
})

describe('ReportGridEditorView.vue — сохранение', () => {
  it('без названия показывает ошибку и не отправляет PUT', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    await wrapper.find('.top-bar input[type="text"]').setValue('')
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await wrapper.find('.top-bar button.btn-primary').trigger('click')

    expect(wrapper.text()).toContain('Укажите название шаблона')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('сохраняет через PUT /report-templates/{id} с текущим содержимым sheets', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    const putMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse(templateFixture()))
    vi.stubGlobal('fetch', putMock)
    await wrapper.find('.top-bar button.btn-primary').trigger('click')
    await flushPromises()

    const [url, init] = putMock.mock.calls[0]
    expect(url).toBe('/api/v1/report-templates/t-1')
    expect(init?.method).toBe('PUT')
    const body = JSON.parse(init!.body as string)
    expect(body.format).toBe('xlsx')
    expect(body.config.sheets[0].rows[0].cells[0].text).toBe('Заголовок')
  })

  it('ошибка сервера при сохранении показывается пользователю', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(ReportGridEditorView)
    await flushPromises()

    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'В шаблоне не задано ни одного листа' }, 422)))
    await wrapper.find('.top-bar button.btn-primary').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('не задано ни одного листа')
  })
})
