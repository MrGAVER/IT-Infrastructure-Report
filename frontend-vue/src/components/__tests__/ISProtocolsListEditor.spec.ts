import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ISProtocolsListEditor from '../ISProtocolsListEditor.vue'
import type { ISProtocolDraftRow, ProtocolPortCatalogEntry } from '../../api/types'

const catalog: ProtocolPortCatalogEntry[] = [
  { id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null },
  { id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null },
]

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

  it('при выборе записи справочника подставляет protocol и port', async () => {
    const rows: ISProtocolDraftRow[] = [{ protocol_catalog_id: '', protocol: '', port: null, description: '' }]
    const wrapper = mount(ISProtocolsListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('select.col-catalog').setValue('cat-https')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ protocol_catalog_id: 'cat-https', protocol: 'HTTPS', port: 443, description: '' }])
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
})
