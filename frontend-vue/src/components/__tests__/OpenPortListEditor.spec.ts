import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import OpenPortListEditor from '../OpenPortListEditor.vue'
import type { OpenPortDraftRow, ProtocolPortCatalogEntry } from '../../api/types'

const catalog: ProtocolPortCatalogEntry[] = [
  { id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null },
  { id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null },
]

describe('OpenPortListEditor.vue', () => {
  it('показывает подсказку, если открытые порты не добавлены', () => {
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: [], catalogEntries: catalog } })
    expect(wrapper.text()).toContain('Открытые порты не добавлены')
  })

  it('подставляет порт и протокол при выборе записи справочника', async () => {
    const rows: OpenPortDraftRow[] = [{ protocol_catalog_id: '', port: '', protocol: '', transport_protocol: 'TCP', description: '' }]
    const wrapper = mount(OpenPortListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('select.col-catalog').setValue('cat-https')

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
})
