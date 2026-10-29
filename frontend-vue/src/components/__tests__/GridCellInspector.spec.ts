import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import GridCellInspector from '../GridCellInspector.vue'
import type { GridCell, GridRow, ReportEntityMeta } from '../../api/types'

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

function staticRow(): GridRow {
  return { height: 20, repeat: false, data_source: null, cells: [] }
}
function repeatingRow(): GridRow {
  return { height: 18, repeat: true, data_source: { root_entity: 'devices', expand: '', include_empty_expand: true, filters: [], sort_by: '' }, cells: [] }
}
function cell(overrides: Partial<GridCell> = {}): GridCell {
  return { col: 0, kind: 'static', text: '', style: {}, ...overrides }
}

describe('GridCellInspector.vue — режим строки', () => {
  it('меняет высоту строки', async () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'row', row: staticRow(), cell: cell(), entities } })
    await wrapper.find('input[type="number"]').setValue('30')
    expect(wrapper.emitted('update-row')?.[0][0]).toEqual({ height: 30 })
  })

  it('высота не может быть меньше 10', async () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'row', row: staticRow(), cell: cell(), entities } })
    await wrapper.find('input[type="number"]').setValue('2')
    expect(wrapper.emitted('update-row')?.[0][0]).toEqual({ height: 10 })
  })

  it('без включённого повторения панель источника данных не показывается', () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'row', row: staticRow(), cell: cell(), entities } })
    expect(wrapper.find('.filters-block').exists()).toBe(false)
  })

  it('включение "повторяющаяся строка" эмитит repeat=true', async () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'row', row: staticRow(), cell: cell(), entities } })
    await wrapper.find('.checkbox-field input[type="checkbox"]').setValue(true)
    expect(wrapper.emitted('update-row')?.[0][0]).toEqual({ repeat: true })
  })

  it('для повторяющейся строки показывает выбор сущности и связи для разворачивания', () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'row', row: repeatingRow(), cell: cell(), entities } })
    const entitySelect = wrapper.findAll('select')[0]
    expect(entitySelect.findAll('option').map((o) => o.text())).toContain('Физические устройства')
  })

  it('смена сущности сбрасывает expand', async () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'row', row: repeatingRow(), cell: cell(), entities } })
    await wrapper.findAll('select')[0].setValue('devices')
    expect(wrapper.emitted('update-row')?.[0][0]).toEqual({ data_source: { root_entity: 'devices', expand: '', include_empty_expand: true, filters: [], sort_by: '' } })
  })

  it('добавляет и удаляет фильтр источника данных', async () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'row', row: repeatingRow(), cell: cell(), entities } })
    await wrapper.find('.btn-mini').trigger('click')
    let patch = wrapper.emitted('update-row')![0][0] as { data_source: { filters: unknown[] } }
    expect(patch.data_source.filters).toHaveLength(1)

    const rowWithFilter = repeatingRow()
    rowWithFilter.data_source!.filters = [{ path: 'name', op: 'eq', value: 'ИС-1' }]
    const wrapper2 = mount(GridCellInspector, { props: { mode: 'row', row: rowWithFilter, cell: cell(), entities } })
    await wrapper2.find('.filter-row .icon-btn').trigger('click')
    patch = wrapper2.emitted('update-row')![0][0] as { data_source: { filters: unknown[] } }
    expect(patch.data_source.filters).toEqual([])
  })

  it('оператор "не пусто" скрывает поле значения фильтра', () => {
    const rowWithFilter = repeatingRow()
    rowWithFilter.data_source!.filters = [{ path: 'name', op: 'not_empty', value: '' }]
    const wrapper = mount(GridCellInspector, { props: { mode: 'row', row: rowWithFilter, cell: cell(), entities } })
    expect(wrapper.find('.filter-row input[placeholder="значение"]').exists()).toBe(false)
  })
})

describe('GridCellInspector.vue — режим ячейки', () => {
  it('меняет тип ячейки', async () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'cell', row: repeatingRow(), cell: cell(), entities } })
    await wrapper.find('.field select').setValue('field')
    expect(wrapper.emitted('update-cell')?.[0][0]).toEqual({ kind: 'field' })
  })

  it('опции "Поле из БД" и "№ записи" недоступны для неповторяющейся строки', () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'cell', row: staticRow(), cell: cell(), entities } })
    const options = wrapper.find('.field select').findAll('option')
    expect((options.find((o) => o.element.value === 'field')!.element as HTMLOptionElement).disabled).toBe(true)
    expect((options.find((o) => o.element.value === 'index')!.element as HTMLOptionElement).disabled).toBe(true)
  })

  it('static — текстовое поле меняет text', async () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'cell', row: staticRow(), cell: cell({ kind: 'static', text: '' }), entities } })
    await wrapper.find('textarea').setValue('Отчёт по ИС')
    expect(wrapper.emitted('update-cell')?.[0][0]).toEqual({ text: 'Отчёт по ИС' })
  })

  it('field — путь можно ввести вручную или выбрать из списка полей сущности строки', async () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'cell', row: repeatingRow(), cell: cell({ kind: 'field', path: '' }), entities } })
    await wrapper.find('input[type="text"]').setValue('system_name')
    expect(wrapper.emitted('update-cell')?.[0][0]).toEqual({ path: 'system_name' })

    const pickerSelect = wrapper.findAll('select').find((s) => s.findAll('option').some((o) => o.text().includes('Системное имя')))
    await pickerSelect!.setValue('system_name')
    const cellEmits = wrapper.emitted('update-cell')!
    expect(cellEmits[cellEmits.length - 1][0]).toEqual({ path: 'system_name' })
  })

  it('formula — поле формулы меняет text', async () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'cell', row: staticRow(), cell: cell({ kind: 'formula', text: '=' }), entities } })
    await wrapper.find('input[type="text"]').setValue('=SUM(A1:A5)')
    expect(wrapper.emitted('update-cell')?.[0][0]).toEqual({ text: '=SUM(A1:A5)' })
  })

  it('index — показывает пояснение, без дополнительных полей ввода', () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'cell', row: repeatingRow(), cell: cell({ kind: 'index' }), entities } })
    expect(wrapper.text()).toContain('Порядковый номер записи')
    expect(wrapper.find('textarea').exists()).toBe(false)
  })

  it('стиль: жирный/курсив/подчёркнутый — чекбоксы переключают style', async () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'cell', row: staticRow(), cell: cell(), entities } })
    const boldCheckbox = wrapper.findAll('.style-checks input')[0]
    await boldCheckbox.setValue(true)
    expect(wrapper.emitted('update-cell')?.[0][0]).toEqual({ style: { bold: true } })
  })

  it('стиль: выравнивание и цвет фона', async () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'cell', row: staticRow(), cell: cell(), entities } })
    const alignSelect = wrapper.findAll('.style-block select')[0]
    await alignSelect.setValue('center')
    expect(wrapper.emitted('update-cell')?.[0][0]).toEqual({ style: { align: 'center' } })

    const bgInput = wrapper.find('.style-block input[placeholder="#EEF2FF"]')
    await bgInput.setValue('#FF0000')
    const emits = wrapper.emitted('update-cell')!
    expect(emits[emits.length - 1][0]).toEqual({ style: { bg: '#FF0000' } })
  })

  it('"Очистить ячейку" эмитит delete-cell', async () => {
    const wrapper = mount(GridCellInspector, { props: { mode: 'cell', row: staticRow(), cell: cell(), entities } })
    await wrapper.find('.inspector > button.btn-secondary').trigger('click')
    expect(wrapper.emitted('delete-cell')).toBeTruthy()
  })
})
