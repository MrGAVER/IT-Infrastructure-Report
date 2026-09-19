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
    expect(emitted[0][0]).toEqual([{ protocol_catalog_id: '', protocol: '', port: null, description: '' }])
  })

  it('справочник теперь SearchableSelect (фикс п.3 — поиск вводом текста), не нативный select', () => {
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: [{ protocol_catalog_id: '', protocol: '', port: null, description: '' }], catalogEntries: catalog } })
    expect(wrapper.find('.col-catalog select').exists()).toBe(false)
    expect(wrapper.find('.col-catalog .searchable-select').exists()).toBe(true)
  })

  it('при выборе записи справочника подставляет protocol и port', async () => {
    const rows: ISProtocolDraftRow[] = [{ protocol_catalog_id: '', protocol: '', port: null, description: '' }]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('.col-catalog .searchable-select input').trigger('focus')
    await wrapper.find('.col-catalog .ss-option').trigger('mousedown') // первая в списке — "443 / HTTPS"

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ protocol_catalog_id: 'cat-https', protocol: 'HTTPS', port: 443, description: '' }])
  })

  it('поиск вводом текста фильтрует записи справочника (фикс п.3, как и у других похожих полей)', async () => {
    const rows: ISProtocolDraftRow[] = [{ protocol_catalog_id: '', protocol: '', port: null, description: '' }]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    const input = wrapper.find('.col-catalog .searchable-select input')
    await input.trigger('focus')
    await input.setValue('SSH')

    const options = wrapper.findAll('.col-catalog .ss-option')
    expect(options).toHaveLength(1)
    expect(options[0].text()).toBe('22 / SSH')

    await options[0].trigger('mousedown')
    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ protocol_catalog_id: 'cat-ssh', protocol: 'SSH', port: 22, description: '' }])
  })

  it('снятие выбора (крестик очистки) сбрасывает protocol_catalog_id', async () => {
    const rows: ISProtocolDraftRow[] = [{ id: 'p1', protocol_catalog_id: 'cat-ssh', protocol: 'SSH', port: 22, description: '' }]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('.col-catalog .ss-clear').trigger('mousedown')

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as ISProtocolDraftRow[])[0].protocol_catalog_id).toBe('')
  })

  it('обновляет описание независимо от выбора справочника', async () => {
    const rows: ISProtocolDraftRow[] = [{ id: 'p1', protocol_catalog_id: 'cat-ssh', protocol: 'SSH', port: 22, description: '' }]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('input.col-desc').setValue('внешний доступ')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ id: 'p1', protocol_catalog_id: 'cat-ssh', protocol: 'SSH', port: 22, description: 'внешний доступ' }])
  })

  it('удаляет строку по клику на кнопку удаления', async () => {
    const rows: ISProtocolDraftRow[] = [{ id: 'p1', protocol_catalog_id: 'cat-ssh', protocol: 'SSH', port: 22, description: '' }]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('.icon-btn.danger').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([])
  })

  it('быстрое добавление записи справочника подставляет id/protocol/port строки', async () => {
    const rows: ISProtocolDraftRow[] = [{ protocol_catalog_id: '', protocol: '', port: null, description: '' }]
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
    expect(lastRows[0]).toMatchObject({ protocol_catalog_id: 'cat-new', protocol: 'RDP', port: 3389 })
  })
})
