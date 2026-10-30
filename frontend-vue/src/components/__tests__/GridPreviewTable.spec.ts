import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import GridPreviewTable from '../GridPreviewTable.vue'
import type { GridPreviewSection } from '../../api/types'

describe('GridPreviewTable.vue', () => {
  it('показывает ошибку секции вместо таблицы', () => {
    const section: GridPreviewSection = { title: 'Лист 1', error: 'У листа не задана исходная сущность' }
    const wrapper = mount(GridPreviewTable, { props: { section } })
    expect(wrapper.text()).toContain('У листа не задана исходная сущность')
    expect(wrapper.find('table').exists()).toBe(false)
  })

  it('рендерит строки и ячейки со значениями', () => {
    const section: GridPreviewSection = {
      title: 'Лист 1',
      n_cols: 2,
      rows: [
        {
          height: 20,
          cells: [
            { col: 0, colspan: 1, rowspan: 1, value: 'Имя', is_datetime: false, style: {} },
            { col: 1, colspan: 1, rowspan: 1, value: 'srv-01', is_datetime: false, style: {} },
          ],
        },
      ],
      total_records: 1,
    }
    const wrapper = mount(GridPreviewTable, { props: { section } })
    expect(wrapper.findAll('td').map((td) => td.text())).toEqual(['Имя', 'srv-01'])
    expect(wrapper.text()).toContain('показано записей: 1')
  })

  it('null/undefined значение ячейки отображается пустой строкой, а не "null"', () => {
    const section: GridPreviewSection = {
      title: 'Лист 1',
      n_cols: 1,
      rows: [{ height: 20, cells: [{ col: 0, colspan: 1, rowspan: 1, value: null, is_datetime: false, style: {} }] }],
    }
    const wrapper = mount(GridPreviewTable, { props: { section } })
    expect(wrapper.find('td').text()).toBe('')
  })

  it('объединённая ячейка получает colspan/rowspan в разметке, покрытые позиции не дублируются', () => {
    const section: GridPreviewSection = {
      title: 'Лист 1',
      n_cols: 2,
      rows: [
        { height: 20, cells: [{ col: 0, colspan: 2, rowspan: 1, value: 'Заголовок', is_datetime: false, style: {} }] },
        {
          height: 20,
          cells: [
            { col: 0, colspan: 1, rowspan: 1, value: 'a', is_datetime: false, style: {} },
            { col: 1, colspan: 1, rowspan: 1, value: 'b', is_datetime: false, style: {} },
          ],
        },
      ],
    }
    const wrapper = mount(GridPreviewTable, { props: { section } })
    const rows = wrapper.findAll('tr')
    expect(rows[0].findAll('td')).toHaveLength(1)
    expect(rows[0].find('td').attributes('colspan')).toBe('2')
    expect(rows[1].findAll('td')).toHaveLength(2)
  })

  it('без названия секции показывает заглушку', () => {
    const section: GridPreviewSection = { title: '', n_cols: 0, rows: [] }
    const wrapper = mount(GridPreviewTable, { props: { section } })
    expect(wrapper.find('.preview-head b').text()).toBe('(без названия)')
  })
})
