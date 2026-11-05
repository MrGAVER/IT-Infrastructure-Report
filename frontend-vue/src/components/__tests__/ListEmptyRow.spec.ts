import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ListEmptyRow from '../ListEmptyRow.vue'

// F-04 (код-ревью main): «пока нет» и «не найдено по фильтрам» — разные состояния списка.

function mountRow(props: Record<string, unknown>) {
  // Корень компонента — <tr>: без таблицы вокруг браузер (и jsdom) разобрал бы разметку иначе.
  return mount(ListEmptyRow, {
    props: { colspan: 5, emptyText: 'Записей пока нет.', registryEmpty: true, ...props },
    attachTo: document.createElement('tbody'),
  })
}

describe('ListEmptyRow.vue', () => {
  it('пустой реестр: текст «пока нет» и кнопка создания; кнопки сброса нет', () => {
    const wrapper = mountRow({ actionLabel: 'Добавить запись' })

    expect(wrapper.get('[data-empty="registry"]').text()).toBe('Записей пока нет.')
    expect(wrapper.get('[data-action="create"]').text()).toBe('Добавить запись')
    expect(wrapper.find('[data-action="reset-filters"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Ничего не найдено')
  })

  it('пустой реестр без actionLabel (нет права записи): кнопки создания нет', () => {
    const wrapper = mountRow({})

    expect(wrapper.text()).toContain('Записей пока нет.')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('записи есть, фильтр ничего не оставил: «не найдено по заданным фильтрам» и «Сбросить фильтры»', () => {
    const wrapper = mountRow({ registryEmpty: false, actionLabel: 'Добавить запись' })

    expect(wrapper.get('[data-empty="filtered"]').text()).toBe('Ничего не найдено по заданным фильтрам.')
    expect(wrapper.get('[data-action="reset-filters"]').text()).toBe('Сбросить фильтры')
    expect(wrapper.text()).not.toContain('пока нет')
  })

  it('при отфильтрованном списке кнопки создания нет, даже если actionLabel передан', () => {
    const wrapper = mountRow({ registryEmpty: false, actionLabel: 'Добавить запись' })

    expect(wrapper.find('[data-action="create"]').exists()).toBe(false)
  })

  it('клики отдают события action и reset', async () => {
    const empty = mountRow({ actionLabel: 'Добавить запись' })
    await empty.get('[data-action="create"]').trigger('click')
    expect(empty.emitted('action')).toHaveLength(1)
    expect(empty.emitted('reset')).toBeUndefined()

    const filtered = mountRow({ registryEmpty: false })
    await filtered.get('[data-action="reset-filters"]').trigger('click')
    expect(filtered.emitted('reset')).toHaveLength(1)
    expect(filtered.emitted('action')).toBeUndefined()
  })

  it('ячейка занимает заданное число столбцов и несёт класс empty-row', () => {
    const wrapper = mountRow({ colspan: 7 })

    expect(wrapper.get('td').attributes('colspan')).toBe('7')
    expect(wrapper.get('td').classes()).toContain('empty-row')
  })
})
