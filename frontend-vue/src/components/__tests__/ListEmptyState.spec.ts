import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ListEmptyState from '../ListEmptyState.vue'

// Хвост F-04: содержимое пустого списка отдельно от строки таблицы — им пользуются и таблицы (через ListEmptyRow), и не табличные
// списки (карточки VLAN). Здесь — само содержимое без обёртки; обёртку ячейки проверяет ListEmptyRow.spec.ts.

const mountState = (props: Record<string, unknown>) => mount(ListEmptyState, { props: { emptyText: 'Записей пока нет.', registryEmpty: true, ...props } })

describe('ListEmptyState.vue', () => {
  it('пустой реестр: «пока нет» и кнопка создания; без обёртки таблицы', () => {
    const wrapper = mountState({ actionLabel: 'Добавить запись' })

    expect(wrapper.element.tagName).toBe('DIV')
    expect(wrapper.get('[data-empty="registry"]').text()).toBe('Записей пока нет.')
    expect(wrapper.get('[data-action="create"]').text()).toBe('Добавить запись')
    expect(wrapper.find('[data-action="reset-filters"]').exists()).toBe(false)
  })

  it('без actionLabel кнопки создания нет (нет права записи или записи не создают вручную)', () => {
    expect(mountState({}).find('button').exists()).toBe(false)
  })

  it('записи есть, фильтр ничего не оставил: «не найдено» и «Сбросить фильтры», без кнопки создания', () => {
    const wrapper = mountState({ registryEmpty: false, actionLabel: 'Добавить запись' })

    expect(wrapper.get('[data-empty="filtered"]').text()).toBe('Ничего не найдено по заданным фильтрам.')
    expect(wrapper.get('[data-action="reset-filters"]').text()).toBe('Сбросить фильтры')
    expect(wrapper.find('[data-action="create"]').exists()).toBe(false)
  })

  it('клики отдают события action и reset', async () => {
    const empty = mountState({ actionLabel: 'Добавить запись' })
    await empty.get('[data-action="create"]').trigger('click')
    expect(empty.emitted('action')).toHaveLength(1)

    const filtered = mountState({ registryEmpty: false })
    await filtered.get('[data-action="reset-filters"]').trigger('click')
    expect(filtered.emitted('reset')).toHaveLength(1)
  })
})
