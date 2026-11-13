import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PortConflictModal from '../PortConflictModal.vue'
import { conflictTitle } from '../../utils/interfaceRowView'
import { makeConflict, makeRow } from '../../utils/__tests__/interfaceRowFixture'

function mountModal(props: Partial<InstanceType<typeof PortConflictModal>['$props']> = {}) {
  return mount(PortConflictModal, {
    props: { row: makeRow({ name: 'Gi0/1', is_management: true }), conflict: makeConflict(), kind: 'flags', applying: false, ...props },
  })
}
const cells = (wrapper: ReturnType<typeof mountModal>) => wrapper.findAll('tbody tr').map((tr) => tr.findAll('td').map((td) => td.text()))

describe('PortConflictModal', () => {
  it('называет порт, соседний порт и устройство, а заголовок зависит от вида расхождения', () => {
    const wrapper = mountModal({ kind: 'vlan_mode' })

    expect(wrapper.text()).toContain('Порт «Gi0/1» соединён с портом «Gi0/9» устройства «sw-02»')
    expect(wrapper.get('h3').text()).toBe(conflictTitle('vlan_mode'))
  })

  it('назначение: Управление и Передача данных этого и соседнего порта рядом', () => {
    const conflict = makeConflict({ other: { is_management: false, is_data_transfer: true, vlan_mode: 'trunk', all_vlans: false } })
    expect(cells(mountModal({ conflict }))).toEqual([
      ['Управление', 'Да', 'Нет'],
      ['Передача данных', 'Нет', 'Да'],
    ])
  })

  it('«Все VLAN»: у этого порта значение берётся из признака порта, у соседа — из его конфигурации; подсказка — про выбор значения', () => {
    const row = makeRow({ vlan_mode: 'trunk', all_vlans: true })
    const wrapper = mountModal({ row, kind: 'all_vlans' })

    expect(cells(wrapper)).toEqual([['Все VLAN', 'Да', 'Нет']])
    expect(wrapper.get('.conflict-modal-hint').text()).toContain('значение для порта выбираете вы')
  })

  it('«Все VLAN» несёт только trunk-порт: у access-порта с остаточным признаком в окне «Нет»', () => {
    const row = makeRow({ vlan_mode: 'access', all_vlans: true })
    expect(cells(mountModal({ row, kind: 'all_vlans' }))).toEqual([['Все VLAN', 'Нет', 'Нет']])
  })

  it('режим порта: Access и Trunk у обоих портов, подсказка — про каскад на группу и связанные порты', () => {
    const conflict = makeConflict({ other: { is_management: false, is_data_transfer: false, vlan_mode: 'access', all_vlans: false } })
    const wrapper = mountModal({ row: makeRow({ vlan_mode: 'trunk' }), conflict, kind: 'vlan_mode' })

    expect(cells(wrapper)).toEqual([['Режим порта', 'Trunk', 'Access']])
    expect(wrapper.get('.conflict-modal-hint').text()).toContain('режим сменится у всей группы')
  })

  it('кнопки применения отдают выбор родителю и блокируются на время применения', async () => {
    const wrapper = mountModal()
    const [neighbor, current] = wrapper.findAll('.conflict-modal-actions button')
    await neighbor.trigger('click')
    await current.trigger('click')
    expect(wrapper.emitted('apply-neighbor')).toHaveLength(1)
    expect(wrapper.emitted('apply-current')).toHaveLength(1)

    await wrapper.setProps({ applying: true })
    expect(wrapper.findAll('.conflict-modal-actions button').every((b) => b.attributes('disabled') !== undefined)).toBe(true)
  })

  it('закрывается крестиком и кликом по подложке, но не выделением текста, закончившимся на подложке', async () => {
    const wrapper = mountModal()
    await wrapper.get('button[aria-label="Закрыть"]').trigger('click')
    const overlay = wrapper.get('.modal-overlay')
    await overlay.trigger('mousedown')
    await overlay.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(2)

    await wrapper.get('.conflict-modal').trigger('mousedown')
    await overlay.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(2)
  })

  it('без данных о расхождении (строка потеряла соседа) окно не падает', () => {
    const wrapper = mountModal({ conflict: undefined })
    expect(wrapper.text()).toContain('Порт «Gi0/1» соединён')
  })
})
