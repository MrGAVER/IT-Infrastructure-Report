import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import CatalogPickerListEditor from '../CatalogPickerListEditor.vue'
import type { CatalogItem, CatalogPickerDraftRow } from '../../api/types'

const catalog: CatalogItem[] = [
  { id: 'dep-1', name: 'Отдел ИБ' },
  { id: 'dep-2', name: 'Отдел эксплуатации' },
]

const props = { title: 'Подразделения', placeholder: '— выберите —', addLabel: 'Подразделение', catalogEntries: catalog }

describe('CatalogPickerListEditor.vue', () => {
  it('показывает подсказку, если ничего не добавлено', () => {
    const wrapper = mount(CatalogPickerListEditor, { props: { ...props, modelValue: [] } })
    expect(wrapper.text()).toContain('Не добавлено')
  })

  it('добавляет пустую строку по клику на кнопку добавления', async () => {
    const wrapper = mount(CatalogPickerListEditor, { props: { ...props, modelValue: [] } })
    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ catalogId: '' }])
  })

  it('обновляет выбранную запись, не мутируя исходный проп', async () => {
    const rows: CatalogPickerDraftRow[] = [{ id: 'r1', catalogId: '' }]
    const wrapper = mount(CatalogPickerListEditor, { props: { ...props, modelValue: rows } })

    await wrapper.find('select').setValue('dep-2')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ id: 'r1', catalogId: 'dep-2' }])
    expect(rows[0].catalogId).toBe('')
  })

  it('удаляет строку по клику на кнопку удаления', async () => {
    const rows: CatalogPickerDraftRow[] = [
      { id: 'r1', catalogId: 'dep-1' },
      { id: 'r2', catalogId: 'dep-2' },
    ]
    const wrapper = mount(CatalogPickerListEditor, { props: { ...props, modelValue: rows } })

    await wrapper.findAll('.icon-btn.danger')[0].trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([rows[1]])
  })
})
