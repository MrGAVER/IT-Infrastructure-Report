import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import CatalogPickerListEditor from '../CatalogPickerListEditor.vue'
import type { CatalogItem, CatalogPickerDraftRow } from '../../api/types'

const catalog: CatalogItem[] = [
  { id: 'dep-1', name: 'Отдел ИБ' },
  { id: 'dep-2', name: 'Отдел эксплуатации' },
]

const props = { title: 'Подразделения', placeholder: '— выберите —', addLabel: 'Подразделение', catalogEntries: catalog }

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

    await wrapper.find('.searchable-select input').trigger('focus')
    const option = wrapper.findAll('.ss-option').find((o) => o.text() === 'Отдел эксплуатации')
    await option!.trigger('mousedown')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ id: 'r1', catalogId: 'dep-2' }])
    expect(rows[0].catalogId).toBe('')
  })

  it('запись справочника выбирается через SearchableSelect (поиск вводом текста), а не нативный select', async () => {
    const wrapper = mount(CatalogPickerListEditor, { props: { ...props, modelValue: [{ catalogId: '' }] } })

    expect(wrapper.find('select').exists()).toBe(false)
    const input = wrapper.find('.searchable-select input')
    expect(input.attributes('placeholder')).toBe('— выберите —')

    await input.trigger('focus')
    await input.setValue('эксплуат')
    expect(wrapper.findAll('.ss-option').map((o) => o.text())).toEqual(['Отдел эксплуатации'])
  })

  it('очистка выбранной записи (крестик) сбрасывает catalogId', async () => {
    const wrapper = mount(CatalogPickerListEditor, { props: { ...props, modelValue: [{ id: 'r1', catalogId: 'dep-1' }] } })

    await wrapper.find('.ss-clear').trigger('mousedown')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ id: 'r1', catalogId: '' }])
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

  it('без quickAddResource кнопка быстрого добавления не показывается', () => {
    const wrapper = mount(CatalogPickerListEditor, { props: { ...props, modelValue: [{ catalogId: '' }] } })
    expect(wrapper.find('.nested-row button:not(.icon-btn)').exists()).toBe(false)
  })

  it('быстрое добавление записи справочника подставляет её id в строку', async () => {
    const wrapper = mount(CatalogPickerListEditor, {
      props: { ...props, modelValue: [{ catalogId: '' }], quickAddResource: 'departments' },
    })

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/departments')) {
          return jsonResponse({ id: 'dep-new', name: 'Отдел разработки' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    await wrapper.find('.nested-row button:not(.icon-btn)').trigger('click')
    await teleportedContent().find('input[type="text"]').setValue('Отдел разработки')
    await teleportedContent().find('form').trigger('submit')
    await flushPromises()

    const emitted = wrapper.emitted('update:modelValue')!
    const lastRows = emitted[emitted.length - 1][0] as CatalogPickerDraftRow[]
    expect(lastRows[0].catalogId).toBe('dep-new')
  })
})
