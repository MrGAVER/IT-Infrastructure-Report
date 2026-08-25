import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SoftwareAssetListEditor from '../SoftwareAssetListEditor.vue'
import type { CatalogItem, SoftwareAssetDraftRow } from '../../api/types'

const catalog: CatalogItem[] = [
  { id: 'sa-1c', name: '1С:Предприятие' },
  { id: 'sa-ad', name: 'Active Directory' },
]

describe('SoftwareAssetListEditor.vue', () => {
  it('показывает подсказку, если программные активы не добавлены', () => {
    const wrapper = mount(SoftwareAssetListEditor, { props: { modelValue: [], catalogEntries: catalog } })
    expect(wrapper.text()).toContain('Программные активы не добавлены')
  })

  it('добавляет пустую строку по клику на "+ Программный актив"', async () => {
    const wrapper = mount(SoftwareAssetListEditor, { props: { modelValue: [], catalogEntries: catalog } })
    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ software_asset_id: '', version: '' }])
  })

  it('обновляет выбранный актив из справочника', async () => {
    const rows: SoftwareAssetDraftRow[] = [{ software_asset_id: '', version: '' }]
    const wrapper = mount(SoftwareAssetListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('select.col-asset').setValue('sa-ad')

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as SoftwareAssetDraftRow[])[0].software_asset_id).toBe('sa-ad')
  })

  it('обновляет версию, не мутируя исходный проп', async () => {
    const rows: SoftwareAssetDraftRow[] = [{ id: 'sw-1', software_asset_id: 'sa-1c', version: '' }]
    const wrapper = mount(SoftwareAssetListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.find('input.col-version').setValue('8.3')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ id: 'sw-1', software_asset_id: 'sa-1c', version: '8.3' }])
    expect(rows[0].version).toBe('')
  })

  it('удаляет строку по клику на кнопку удаления', async () => {
    const rows: SoftwareAssetDraftRow[] = [
      { id: 'sw-1', software_asset_id: 'sa-1c', version: '8.3' },
      { id: 'sw-2', software_asset_id: 'sa-ad', version: '' },
    ]
    const wrapper = mount(SoftwareAssetListEditor, { props: { modelValue: rows, catalogEntries: catalog } })

    await wrapper.findAll('.icon-btn.danger')[0].trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([rows[1]])
  })
})
