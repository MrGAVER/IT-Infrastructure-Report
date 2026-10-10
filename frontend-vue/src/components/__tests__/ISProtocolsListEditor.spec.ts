import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ISProtocolsListEditor from '../ISProtocolsListEditor.vue'
import type { ISProtocolDraftRow, ProtocolPortCatalogEntry } from '../../api/types'

const catalog: ProtocolPortCatalogEntry[] = [
  { id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null },
  { id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null },
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

describe('ISProtocolsListEditor.vue', () => {
  it('показывает подсказку, если протоколы не добавлены', () => {
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: [], catalogEntries: catalog } })
    expect(wrapper.text()).toContain('Не добавлено')
  })

  it('добавляет пустую строку по клику на "+ Протокол"', async () => {
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: [], catalogEntries: catalog } })
    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ protocol_catalog_id: '', description: '' }])
  })

  it('справочник теперь SearchableSelect (фикс п.3 — поиск вводом текста), не нативный select', () => {
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: [{ protocol_catalog_id: '', description: '' }], catalogEntries: catalog } })
    expect(wrapper.find('.col-catalog select').exists()).toBe(false)
    expect(wrapper.find('.col-catalog .searchable-select').exists()).toBe(true)
  })

  it('при выборе записи справочника сохраняет только protocol_catalog_id — port/protocol больше не колонки записи', async () => {
    const rows: ISProtocolDraftRow[] = [{ protocol_catalog_id: '', description: '' }]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('.col-catalog .searchable-select input').trigger('focus')
    await wrapper.find('.col-catalog .ss-option').trigger('mousedown') // первая в списке — "443 / HTTPS"

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ protocol_catalog_id: 'cat-https', description: '' }])
  })

  it('поиск вводом текста фильтрует записи справочника (фикс п.3, как и у других похожих полей)', async () => {
    const rows: ISProtocolDraftRow[] = [{ protocol_catalog_id: '', description: '' }]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    const input = wrapper.find('.col-catalog .searchable-select input')
    await input.trigger('focus')
    await input.setValue('SSH')

    const options = wrapper.findAll('.col-catalog .ss-option')
    expect(options).toHaveLength(1)
    expect(options[0].text()).toBe('22 / SSH')

    await options[0].trigger('mousedown')
    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ protocol_catalog_id: 'cat-ssh', description: '' }])
  })

  it('снятие выбора (крестик очистки) сбрасывает protocol_catalog_id', async () => {
    const rows: ISProtocolDraftRow[] = [{ id: 'p1', protocol_catalog_id: 'cat-ssh', description: '' }]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('.col-catalog .ss-clear').trigger('mousedown')

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as ISProtocolDraftRow[])[0].protocol_catalog_id).toBe('')
  })

  it('обновляет описание независимо от выбора справочника', async () => {
    const rows: ISProtocolDraftRow[] = [{ id: 'p1', protocol_catalog_id: 'cat-ssh', description: '' }]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('input.col-desc').setValue('внешний доступ')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ id: 'p1', protocol_catalog_id: 'cat-ssh', description: 'внешний доступ' }])
  })

  it('удаляет строку по клику на кнопку удаления', async () => {
    const rows: ISProtocolDraftRow[] = [{ id: 'p1', protocol_catalog_id: 'cat-ssh', description: '' }]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('.icon-btn.danger').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([])
  })

  it('быстрое добавление записи справочника подставляет id строки, без protocol/port', async () => {
    const rows: ISProtocolDraftRow[] = [{ protocol_catalog_id: '', description: '' }]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

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
    const lastRows = emitted[emitted.length - 1][0] as ISProtocolDraftRow[]
    expect(lastRows[0]).toMatchObject({ protocol_catalog_id: 'cat-new' })
  })
})

// Протоколы ИС — те же открытые порты, что у ВМ: сортировка только при добавлении следующей строки,
// подсветка повторов номера порта (сохранение с повтором блокирует форма ИС).
describe('ISProtocolsListEditor.vue — как открытые порты ВМ', () => {
  const wide: ProtocolPortCatalogEntry[] = [
    { id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null },
    { id: 'cat-http', port: 80, protocol_type: 'HTTP', description: null },
    { id: 'cat-http-alt', port: 80, protocol_type: 'HTTP-Proxy', description: null },
    { id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null },
  ]
  const proto = (protocol_catalog_id: string, description = ''): ISProtocolDraftRow => ({ protocol_catalog_id, description })

  it('«+ Протокол» упорядочивает заполненные строки по номеру порта и добавляет пустую в конец', async () => {
    const rows = [proto('cat-https', 'b'), proto('cat-ssh', 'a'), proto('')]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: wide } })

    await wrapper.find('button.add-btn').trigger('click')

    const next = wrapper.emitted('update:modelValue')![0][0] as ISProtocolDraftRow[]
    expect(next.map((r) => r.protocol_catalog_id)).toEqual(['cat-ssh', 'cat-https', '', ''])
  })

  it('выбор записи справочника и правка описания не переставляют строки', async () => {
    const rows = [proto('cat-https'), proto('')]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: wide } })

    await wrapper.findAll('.col-catalog .searchable-select input')[1].trigger('focus')
    await wrapper.findAll('.col-catalog')[1].find('.ss-option').trigger('mousedown') // первая в списке — 22 / SSH
    await wrapper.findAll('input.col-desc')[0].setValue('внешний')

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as ISProtocolDraftRow[]).map((r) => r.protocol_catalog_id)).toEqual(['cat-https', 'cat-ssh'])
    expect((emitted[1][0] as ISProtocolDraftRow[]).map((r) => r.protocol_catalog_id)).toEqual(['cat-https', ''])
  })

  it('подсвечивает строки с повторяющимся номером порта (80/HTTP и 80/HTTP-Proxy) и показывает сообщение', () => {
    const rows = [proto('cat-http'), proto('cat-ssh'), proto('cat-http-alt')]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: wide } })

    const marked = wrapper.findAll('.nested-row').map((r) => r.classes('row-duplicate'))
    expect(marked).toEqual([true, false, true])
    expect(wrapper.find('.dup-error').text()).toContain('Порт 80')
  })

  it('без повторов сообщения и подсветки нет; пустые строки повтором не считаются', () => {
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: [proto('cat-ssh'), proto(''), proto('')], catalogEntries: wide } })
    expect(wrapper.find('.dup-error').exists()).toBe(false)
    expect(wrapper.find('.row-duplicate').exists()).toBe(false)
  })
})
