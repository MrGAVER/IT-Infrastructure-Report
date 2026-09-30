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
