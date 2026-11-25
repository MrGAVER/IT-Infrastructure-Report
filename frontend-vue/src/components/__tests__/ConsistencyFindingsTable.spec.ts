import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ConsistencyFindingsTable from '../ConsistencyFindingsTable.vue'
import { approvedFinding, finding } from '../../__tests__/consistencyFixtures'

const vm = finding({
  rule: 'vm_without_host',
  entity_type: 'virtual_machine',
  entity_id: 'vm-1',
  entity_name: 'orphan',
  message: 'orphan: нет хоста.',
  sheet: 4,
})

function mountTable(props: Partial<InstanceType<typeof ConsistencyFindingsTable>['$props']> = {}) {
  return mount(ConsistencyFindingsTable, {
    props: {
      items: [vm],
      canWrite: true,
      busy: false,
      opening: false,
      ruleTitle: (code: string) => `Правило ${code}`,
      registryEmpty: true,
      emptyText: 'Проблем нет.',
      ...props,
    },
  })
}

describe('ConsistencyFindingsTable', () => {
  it('строка на проблему: важность, название правила, категория, объект, описание и лист', () => {
    const row = mountTable().find('tbody tr')

    expect(row.text()).toContain('Предупреждение')
    expect(row.text()).toContain('Правило vm_without_host')
    expect(row.text()).toContain('Лист 4 — виртуальные машины')
    expect(row.find('.object-cell').text()).toBe('orphan')
    expect(row.find('.message-cell').text()).toBe('orphan: нет хоста.')
  })

  it('пишущему — столбец «Действие» и имя-кнопка; наблюдателю — ни того ни другого, имя ведёт в раздел', () => {
    const writer = mountTable()
    expect(writer.findAll('thead th').map((th) => th.text())).toContain('Действие')
    expect(writer.find('.entity-link').exists()).toBe(true)

    const viewer = mountTable({ canWrite: false })
    expect(viewer.findAll('thead th').map((th) => th.text())).not.toContain('Действие')
    expect(viewer.find('.entity-link').exists()).toBe(false)
    expect(viewer.find('.object-cell a').attributes('href')).toBe('/vms')
  })

  it('нажатия отдают события родителю: имя объекта, «Одобрить», «Отозвать одобрение»', async () => {
    const approved = approvedFinding({ entity_id: 'v2', entity_name: 'second' })
    const wrapper = mountTable({ items: [vm, approved] })

    await wrapper.find('.entity-link').trigger('click')
    await wrapper.findAll('.action-cell button')[0].trigger('click')
    await wrapper.findAll('.action-cell button')[1].trigger('click')

    expect(wrapper.emitted('open')).toEqual([[{ type: 'virtual_machine', id: 'vm-1', name: 'orphan' }]])
    expect(wrapper.emitted('approve')).toEqual([[vm]])
    expect(wrapper.emitted('revoke')).toEqual([[approved]])
  })

  it('пока идёт запрос — кнопки действий заблокированы; пока грузится объект — заблокировано имя', () => {
    const wrapper = mountTable({ busy: true, opening: true })

    expect(wrapper.find('.action-cell button').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.entity-link').attributes('disabled')).toBeDefined()
  })

  it('одобренная строка помечена бейджем и примечанием: автор, дата и комментарий', () => {
    const wrapper = mountTable({ items: [approvedFinding({}, { approved_by: 'anna', comment: 'общий адрес' })] })

    expect(wrapper.find('tr.approved').exists()).toBe(true)
    expect(wrapper.find('.approved-badge').text()).toBe('Одобрено')
    expect(wrapper.find('.approval-note').text()).toMatch(/Одобрено: anna, 23\.11\.2026.*— общий адрес/)
  })

  it('пустая таблица: «проблем нет» без фильтров и «Сбросить фильтры» с ними; ширина строки зависит от роли', async () => {
    const empty = mountTable({ items: [], registryEmpty: true })
    expect(empty.find('[data-empty="registry"]').text()).toBe('Проблем нет.')
    expect(empty.find('td.empty-row').attributes('colspan')).toBe('6')

    const filtered = mountTable({ items: [], registryEmpty: false, canWrite: false })
    expect(filtered.find('[data-empty="filtered"]').exists()).toBe(true)
    expect(filtered.find('td.empty-row').attributes('colspan')).toBe('5')
    await filtered.find('[data-action="reset-filters"]').trigger('click')
    expect(filtered.emitted('reset')).toHaveLength(1)
  })
})
