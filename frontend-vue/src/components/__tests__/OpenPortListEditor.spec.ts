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
  it('показывает подсказку, если открытые порты не добавлены', () => {
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: [], catalogEntries: catalog } })
    expect(wrapper.text()).toContain('Открытые порты не добавлены')
  })

  it('подставляет порт и протокол при выборе записи справочника', async () => {
    const rows: OpenPortDraftRow[] = [{ protocol_catalog_id: '', port: '', protocol: '', transport_protocol: 'TCP', description: '' }]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('.col-catalog select').setValue('cat-https')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([
      { protocol_catalog_id: 'cat-https', port: '443', protocol: 'HTTPS', transport_protocol: 'TCP', description: '' },
    ])
  })

  it('позволяет заполнить порт вручную без справочника', async () => {
    const rows: OpenPortDraftRow[] = [{ protocol_catalog_id: '', port: '', protocol: '', transport_protocol: 'TCP', description: '' }]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('input.col-port').setValue('8080')

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as OpenPortDraftRow[])[0].port).toBe('8080')
  })

  it('добавляет новую строку с транспортом TCP по умолчанию', async () => {
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: [], catalogEntries: catalog } })
    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([
      { protocol_catalog_id: '', port: '', protocol: '', transport_protocol: 'TCP', description: '' },
    ])
  })

  it('удаляет строку по клику на кнопку удаления', async () => {
    const rows: OpenPortDraftRow[] = [
      { id: 'op-1', protocol_catalog_id: '', port: '22', protocol: 'SSH', transport_protocol: 'TCP', description: '' },
    ]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('.icon-btn.danger').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([])
  })

  it('быстрое добавление записи справочника подставляет id в protocol_catalog_id строки', async () => {
    // Порт/протокол автозаполняются только если catalogEntries уже отражает созданную запись —
    // в реальном приложении так и есть (VMFormModal.vue/DeviceFormModal.vue передают проп как
    // catalogs.protocolPortCatalog напрямую из стора, реактивно), но в изолированном юнит-тесте
    // с статичным массивом это не воспроизвести — см. интеграционный тест в
    // DeviceFormModal.spec.ts на полное автозаполнение после квик-добавления.
    const rows: OpenPortDraftRow[] = [{ protocol_catalog_id: '', port: '', protocol: '', transport_protocol: 'TCP', description: '' }]
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
