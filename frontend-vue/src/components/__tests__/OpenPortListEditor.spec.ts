import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import OpenPortListEditor from '../OpenPortListEditor.vue'
import type { OpenPortDraftRow, ProtocolPortCatalogEntry } from '../../api/types'

const catalog: ProtocolPortCatalogEntry[] = [
  { id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null },
  { id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null },
]

// QuickAddModal.vue телепортируется в document.body — см. QuickAddModal.spec.ts.
function teleportedContent(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
})

describe('OpenPortListEditor.vue', () => {
  it('readonly: поля выключены, добавления и удаления нет (значения задаёт группа портов)', () => {
    const rows: OpenPortDraftRow[] = [{ protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: 'админ' }]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: catalog, readonly: true } })

    expect(wrapper.find('.col-catalog input').attributes('disabled')).toBeDefined()
    expect(wrapper.find('select.col-transport').attributes('disabled')).toBeDefined()
    expect(wrapper.find('input.col-desc').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.add-btn').exists()).toBe(false)
    expect(wrapper.find('button[aria-label="Удалить открытый порт"]').exists()).toBe(false)
  })

  it('показывает подсказку, если открытые порты не добавлены', () => {
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: [], catalogEntries: catalog } })
    expect(wrapper.text()).toContain('Открытые порты не добавлены')
  })

  it('правка "убрать текстовые поля Порт/Протокол": инпутов для них больше нет', () => {
    const rows: OpenPortDraftRow[] = [{ protocol_catalog_id: '', transport_protocol: 'TCP', description: '' }]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    expect(wrapper.find('input.col-port').exists()).toBe(false)
    expect(wrapper.find('input.col-protocol').exists()).toBe(false)
    // Справочник теперь SearchableSelect (фикс п.2 — поиск вводом текста), не нативный <select>.
    expect(wrapper.find('.col-catalog select').exists()).toBe(false)
    expect(wrapper.find('.col-catalog .searchable-select').exists()).toBe(true)
  })

  it('подставляет protocol_catalog_id при выборе записи справочника (порт/протокол выводит сервер)', async () => {
    const rows: OpenPortDraftRow[] = [{ protocol_catalog_id: '', transport_protocol: 'TCP', description: '' }]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('.col-catalog .searchable-select input').trigger('focus')
    await wrapper.find('.col-catalog .ss-option').trigger('mousedown') // единственная опция первой в списке — "22 / SSH"

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }])
  })

  it('поиск вводом текста фильтрует записи справочника (фикс п.2, как и у других похожих полей)', async () => {
    const rows: OpenPortDraftRow[] = [{ protocol_catalog_id: '', transport_protocol: 'TCP', description: '' }]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    const input = wrapper.find('.col-catalog .searchable-select input')
    await input.trigger('focus')
    await input.setValue('HTTPS')

    const options = wrapper.findAll('.col-catalog .ss-option')
    expect(options).toHaveLength(1)
    expect(options[0].text()).toBe('443 / HTTPS')

    await options[0].trigger('mousedown')
    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ protocol_catalog_id: 'cat-https', transport_protocol: 'TCP', description: '' }])
  })

  it('снятие выбора (крестик очистки) сбрасывает protocol_catalog_id', async () => {
    const rows: OpenPortDraftRow[] = [{ protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('.col-catalog .ss-clear').trigger('mousedown')

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as OpenPortDraftRow[])[0].protocol_catalog_id).toBe('')
  })

  it('добавляет новую строку с транспортом TCP по умолчанию', async () => {
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: [], catalogEntries: catalog } })
    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ protocol_catalog_id: '', transport_protocol: 'TCP', description: '' }])
  })

  it('удаляет строку по клику на кнопку удаления', async () => {
    const rows: OpenPortDraftRow[] = [{ id: 'op-1', protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('.icon-btn.danger').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([])
  })

  it('быстрое добавление записи справочника подставляет id в protocol_catalog_id строки', async () => {
    const rows: OpenPortDraftRow[] = [{ protocol_catalog_id: '', transport_protocol: 'TCP', description: '' }]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/protocol-port-catalog')) {
          return jsonResponse({ id: 'cat-new', port: 3389, protocol_type: 'RDP', description: null }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    await wrapper.find('.col-catalog button').trigger('click')
    await teleportedContent().find('input[type="number"]').setValue('3389')
    await teleportedContent().find('input[type="text"]').setValue('RDP')
    await teleportedContent().find('form').trigger('submit')
    await flushPromises()

    const emitted = wrapper.emitted('update:modelValue')!
    const lastRows = emitted[emitted.length - 1][0] as OpenPortDraftRow[]
    expect(lastRows[0].protocol_catalog_id).toBe('cat-new')
  })
})

const wideCatalog: ProtocolPortCatalogEntry[] = [
  { id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null },
  { id: 'cat-http', port: 80, protocol_type: 'HTTP', description: null },
  { id: 'cat-http-alt', port: 80, protocol_type: 'HTTP-Proxy', description: null },
  { id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null },
]

function openRow(protocol_catalog_id: string): OpenPortDraftRow {
  return { protocol_catalog_id, transport_protocol: 'TCP', description: '' }
}

describe('OpenPortListEditor.vue — sorted-unique (форма ВМ)', () => {
  async function pick(wrapper: ReturnType<typeof mount>, rowIndex: number, label: string) {
    const input = wrapper.findAll('.col-catalog .searchable-select input')[rowIndex]
    await input.trigger('focus')
    const option = wrapper.findAll('.col-catalog .ss-option').find((o) => o.text() === label)!
    await option.trigger('mousedown')
  }

  it('выбор записи справочника не переставляет строки: только что заполняемая строка остаётся на месте', async () => {
    const rows = [openRow('cat-https'), openRow(''), openRow('')]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: wideCatalog, sortedUnique: true } })

    await pick(wrapper, 1, '22 / SSH')

    // 22 меньше 443, но строка не «уезжает» наверх: пользователю ещё заполнять транспорт и описание.
    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as OpenPortDraftRow[]).map((r) => r.protocol_catalog_id)).toEqual(['cat-https', 'cat-ssh', ''])
  })

  it('«+ Открытый порт» сортирует заполненные строки по номеру и добавляет пустую строку в конец', async () => {
    const rows = [openRow('cat-https'), openRow('cat-ssh')] // намеренно не по порядку
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: wideCatalog, sortedUnique: true } })

    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as OpenPortDraftRow[]).map((r) => r.protocol_catalog_id)).toEqual(['cat-ssh', 'cat-https', ''])
  })

  it('«+ Открытый порт»: строка, не заполненная к этому моменту, остаётся после заполненных', async () => {
    const rows = [openRow('cat-https'), openRow(''), openRow('cat-http')]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: wideCatalog, sortedUnique: true } })

    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as OpenPortDraftRow[]).map((r) => r.protocol_catalog_id)).toEqual(['cat-http', 'cat-https', '', ''])
  })

  it('без sortedUnique «+ Открытый порт» порядок существующих строк не меняет', async () => {
    const rows = [openRow('cat-https'), openRow('cat-ssh')]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: wideCatalog } })

    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as OpenPortDraftRow[]).map((r) => r.protocol_catalog_id)).toEqual(['cat-https', 'cat-ssh', ''])
  })

  it('подсвечивает строки с повторяющимся номером порта и показывает сообщение', () => {
    const rows = [openRow('cat-http'), openRow('cat-ssh'), openRow('cat-http-alt')]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: wideCatalog, sortedUnique: true } })

    const flagged = wrapper.findAll('.nested-row').map((r) => r.classes().includes('row-duplicate'))
    expect(flagged).toEqual([true, false, true])
    expect(wrapper.find('.dup-error').text()).toContain('Порт 80')
  })

  it('без sortedUnique поведение прежнее: порядок не меняется, повторы не подсвечиваются', async () => {
    const rows = [openRow('cat-https'), openRow('')]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: wideCatalog } })

    await pick(wrapper, 1, '22 / SSH')

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as OpenPortDraftRow[]).map((r) => r.protocol_catalog_id)).toEqual(['cat-https', 'cat-ssh'])

    const dup = mount(OpenPortListEditor, { props: { modelValue: [openRow('cat-http'), openRow('cat-http-alt')], catalogEntries: wideCatalog } })
    expect(dup.find('.dup-error').exists()).toBe(false)
    expect(dup.find('.row-duplicate').exists()).toBe(false)
  })

  it('правка описания не переупорядочивает строки', async () => {
    const rows = [openRow('cat-https'), openRow('cat-ssh')] // намеренно не по порядку
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: wideCatalog, sortedUnique: true } })

    await wrapper.findAll('input.col-desc')[0].setValue('веб')

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as OpenPortDraftRow[]).map((r) => r.protocol_catalog_id)).toEqual(['cat-https', 'cat-ssh'])
  })
})

describe('OpenPortListEditor.vue — сворачивание длинного списка по порогу', () => {
  const manyCatalog: ProtocolPortCatalogEntry[] = Array.from({ length: 30 }, (_, i) => ({
    id: `cat-${i + 1}`, port: 1000 + i, protocol_type: `PROTO${i + 1}`, description: null,
  }))
  const makeRows = (n: number): OpenPortDraftRow[] =>
    Array.from({ length: n }, (_, i) => ({ id: `op-${i}`, protocol_catalog_id: `cat-${i + 1}`, transport_protocol: 'TCP', description: '' }))
  const toggle = (w: ReturnType<typeof mount>) => w.find('[data-testid="ports-collapse-toggle"]')
  const rowsOf = (w: ReturnType<typeof mount>) => w.findAll('.nested-row')

  it('порог не передан — сворачивания нет, как и раньше (даже для очень длинного списка)', () => {
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: makeRows(25), catalogEntries: manyCatalog } })
    expect(rowsOf(wrapper)).toHaveLength(25)
    expect(toggle(wrapper).exists()).toBe(false)
    expect(wrapper.find('[data-testid="ports-collapsed"]').exists()).toBe(false)
  })

  it('на пороге (ровно 10 строк) список развёрнут и кнопки нет', () => {
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: makeRows(10), catalogEntries: manyCatalog, collapseAfter: 10 } })
    expect(rowsOf(wrapper)).toHaveLength(10)
    expect(toggle(wrapper).exists()).toBe(false)
  })

  it('при 11 строках список свёрнут: строк нет, есть счётчик, номера портов и кнопка «Развернуть»', () => {
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: makeRows(11), catalogEntries: manyCatalog, collapseAfter: 10 } })
    expect(rowsOf(wrapper)).toHaveLength(0)
    const summary = wrapper.find('[data-testid="ports-collapsed"]')
    expect(summary.text()).toContain('Открытых портов: 11')
    expect(summary.text()).toContain('1000, 1001, 1002')
    expect(toggle(wrapper).text()).toContain('Развернуть (11)')
    expect(toggle(wrapper).attributes('aria-expanded')).toBe('false')
  })

  it('сводка длинного списка обрезается многоточием', () => {
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: makeRows(25), catalogEntries: manyCatalog, collapseAfter: 10 } })
    expect(wrapper.find('.summary-numbers').text()).toBe('1000, 1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 1009, 1010, 1011, …')
  })

  it('кнопка разворачивает и снова сворачивает список', async () => {
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: makeRows(12), catalogEntries: manyCatalog, collapseAfter: 10 } })
    await toggle(wrapper).trigger('click')
    expect(rowsOf(wrapper)).toHaveLength(12)
    expect(toggle(wrapper).text()).toContain('Свернуть')

    await toggle(wrapper).trigger('click')
    expect(rowsOf(wrapper)).toHaveLength(0)
  })

  it('«+ порт» на свёрнутом списке разворачивает его, чтобы новая строка была видна', async () => {
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: makeRows(11), catalogEntries: manyCatalog, collapseAfter: 10 } })
    await wrapper.find('.add-btn').trigger('click')
    await wrapper.setProps({ modelValue: wrapper.emitted('update:modelValue')![0][0] as OpenPortDraftRow[] })
    expect(rowsOf(wrapper)).toHaveLength(12)
  })

  it('добавление 11-й строки в развёрнутом списке не сворачивает его под руками пользователя', async () => {
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: makeRows(10), catalogEntries: manyCatalog, collapseAfter: 10 } })
    await wrapper.find('.add-btn').trigger('click')
    await wrapper.setProps({ modelValue: wrapper.emitted('update:modelValue')![0][0] as OpenPortDraftRow[] })
    expect(rowsOf(wrapper)).toHaveLength(11)
    expect(wrapper.find('[data-testid="ports-collapsed"]').exists()).toBe(false)
  })

  it('список с повторяющимся портом не сворачивается: подсветка повторов должна быть видна', () => {
    const rows = makeRows(12)
    rows[5] = { ...rows[5], protocol_catalog_id: rows[0].protocol_catalog_id } // порт 1000 дважды
    // Повторы отслеживаются с sortedUnique — оно включено во всех реальных местах использования редактора.
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: manyCatalog, collapseAfter: 10, sortedUnique: true } })
    expect(rowsOf(wrapper)).toHaveLength(12)
    expect(wrapper.find('.row-duplicate').exists()).toBe(true)
  })

  it('в режиме readonly (порты задаёт группа) длинный список тоже сворачивается для просмотра', () => {
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: makeRows(11), catalogEntries: manyCatalog, collapseAfter: 10, readonly: true } })
    expect(wrapper.find('[data-testid="ports-collapsed"]').exists()).toBe(true)
  })
})
