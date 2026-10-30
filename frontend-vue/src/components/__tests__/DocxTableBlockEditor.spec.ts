import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import DocxTableBlockEditor from '../DocxTableBlockEditor.vue'
import type { DocxTableBlock, ReportEntityMeta } from '../../api/types'

const entities: ReportEntityMeta[] = [
  {
    key: 'devices',
    label: 'Физические устройства',
    fields: [{ name: 'system_name', label: 'Системное имя', type: 'String', is_foreign_key: false }],
    to_one: [],
    to_many: [{ name: 'interfaces', target: 'interfaces' }],
  },
  { key: 'interfaces', label: 'Интерфейсы', fields: [{ name: 'name', label: 'Наименование', type: 'String', is_foreign_key: false }], to_one: [], to_many: [] },
]

function block(overrides: Partial<DocxTableBlock> = {}): DocxTableBlock {
  return { type: 'table', title: '', root_entity: '', expand: '', include_empty_expand: true, sort_by: '', filters: [], columns: [], ...overrides }
}

beforeEach(() => {
  vi.stubGlobal(
    'confirm',
    vi.fn(() => true),
  )
})

describe('DocxTableBlockEditor.vue — сущность', () => {
  it('выбор сущности без имеющегося содержимого не требует подтверждения', async () => {
    const wrapper = mount(DocxTableBlockEditor, { props: { block: block(), entities } })
    await wrapper.find('.row select').setValue('devices')
    expect(wrapper.emitted('update')?.[0][0]).toEqual({ root_entity: 'devices', expand: '' })
    expect(confirm).not.toHaveBeenCalled()
  })

  it('смена сущности при наличии содержимого запрашивает подтверждение и сбрасывает пути/фильтры/сортировку', async () => {
    const b = block({
      root_entity: 'devices',
      columns: [{ header: 'Имя', source: 'field', path: 'system_name' }],
      filters: [{ path: 'system_name', op: 'eq', value: 'x' }],
      sort_by: 'system_name',
    })
    const wrapper = mount(DocxTableBlockEditor, { props: { block: b, entities } })

    await wrapper.find('.row select').setValue('interfaces')

    expect(confirm).toHaveBeenCalled()
    expect(wrapper.emitted('update')?.[0][0]).toEqual({
      root_entity: 'interfaces',
      expand: '',
      columns: [{ header: 'Имя', source: 'field', path: '' }],
      filters: [],
      sort_by: '',
    })
  })

  it('отказ от подтверждения не эмитит update', async () => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    )
    const b = block({ root_entity: 'devices', sort_by: 'system_name' })
    const wrapper = mount(DocxTableBlockEditor, { props: { block: b, entities } })

    await wrapper.find('.row select').setValue('interfaces')

    expect(wrapper.emitted('update')).toBeFalsy()
  })
})

describe('DocxTableBlockEditor.vue — фильтры', () => {
  it('добавляет и удаляет фильтр', async () => {
    const wrapper = mount(DocxTableBlockEditor, { props: { block: block({ root_entity: 'devices' }), entities } })
    await wrapper.find('.sub-block .btn-mini').trigger('click')
    expect((wrapper.emitted('update')![0][0] as Partial<DocxTableBlock>).filters).toHaveLength(1)

    const withFilter = block({ root_entity: 'devices', filters: [{ path: 'system_name', op: 'eq', value: 'x' }] })
    const wrapper2 = mount(DocxTableBlockEditor, { props: { block: withFilter, entities } })
    await wrapper2.find('.filter-row .icon-btn').trigger('click')
    expect((wrapper2.emitted('update')![0][0] as Partial<DocxTableBlock>).filters).toEqual([])
  })

  it('оператор "не пусто" скрывает поле значения', () => {
    const withFilter = block({ root_entity: 'devices', filters: [{ path: 'system_name', op: 'not_empty', value: '' }] })
    const wrapper = mount(DocxTableBlockEditor, { props: { block: withFilter, entities } })
    expect(wrapper.find('.filter-row input[placeholder="значение"]').exists()).toBe(false)
  })
})

describe('DocxTableBlockEditor.vue — колонки', () => {
  it('добавляет колонку по умолчанию с source=field', async () => {
    const wrapper = mount(DocxTableBlockEditor, { props: { block: block({ root_entity: 'devices' }), entities } })
    await wrapper.find('.sub-block:last-of-type .btn-mini').trigger('click')
    const patch = wrapper.emitted('update')![0][0] as Partial<DocxTableBlock>
    expect(patch.columns).toEqual([{ header: '', source: 'field', path: '', separator: '; ' }])
  })

  it('смена источника колонки на "static" подставляет поле значения по умолчанию', async () => {
    const withCol = block({ root_entity: 'devices', columns: [{ header: 'X', source: 'field', path: 'system_name', separator: '; ' }] })
    const wrapper = mount(DocxTableBlockEditor, { props: { block: withCol, entities } })
    await wrapper.find('.column-row select').setValue('static')
    const patch = wrapper.emitted('update')![0][0] as Partial<DocxTableBlock>
    expect(patch.columns![0]).toMatchObject({ source: 'static', value: '' })
  })

  it('источник "index" — заглушка вместо полей ввода', () => {
    const withCol = block({ root_entity: 'devices', columns: [{ header: '№', source: 'index' }] })
    const wrapper = mount(DocxTableBlockEditor, { props: { block: withCol, entities } })
    expect(wrapper.find('.column-value.empty').exists()).toBe(true)
  })

  it('перемещение колонки меняет порядок, границы блокируют кнопки', async () => {
    const twoCols = block({
      root_entity: 'devices',
      columns: [
        { header: 'A', source: 'static', value: '' },
        { header: 'B', source: 'static', value: '' },
      ],
    })
    const wrapper = mount(DocxTableBlockEditor, { props: { block: twoCols, entities } })

    const firstRowButtons = wrapper.findAll('.column-row')[0].findAll('.column-actions button')
    expect((firstRowButtons[0].element as HTMLButtonElement).disabled).toBe(true) // "←" на первой колонке недоступна

    await firstRowButtons[1].trigger('click') // "→"
    const patch = wrapper.emitted('update')![0][0] as Partial<DocxTableBlock>
    expect(patch.columns!.map((c) => c.header)).toEqual(['B', 'A'])
  })

  it('удаляет колонку', async () => {
    const withCol = block({ root_entity: 'devices', columns: [{ header: 'X', source: 'static', value: '' }] })
    const wrapper = mount(DocxTableBlockEditor, { props: { block: withCol, entities } })
    await wrapper.find('.column-row .icon-btn').trigger('click')
    const patch = wrapper.emitted('update')![0][0] as Partial<DocxTableBlock>
    expect(patch.columns).toEqual([])
  })

  it('без сущности кнопки "+ фильтр"/"+ колонка" неактивны', () => {
    const wrapper = mount(DocxTableBlockEditor, { props: { block: block(), entities } })
    const btns = wrapper.findAll('.btn-mini')
    expect(btns.every((b) => (b.element as HTMLButtonElement).disabled)).toBe(true)
  })
})
