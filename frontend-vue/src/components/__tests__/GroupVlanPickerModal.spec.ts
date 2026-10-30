import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { makeVlan } from '../../utils/__tests__/interfaceRowFixture'
import GroupVlanPickerModal from '../GroupVlanPickerModal.vue'

const vlans = [makeVlan('v10', 10, 'Серверы'), makeVlan('v20', 20, 'Гости'), makeVlan('v30', 30, 'Телефония', 'Филиал')]

function mountModal(props: Partial<InstanceType<typeof GroupVlanPickerModal>['$props']> = {}) {
  return mount(GroupVlanPickerModal, { props: { vlanOptions: vlans, vlanIds: [], allVlans: false, ...props } })
}
const rowsOf = (wrapper: ReturnType<typeof mountModal>) => wrapper.findAll('.vlan-picker-list .check-inline:not(.vlan-check-all)')

describe('GroupVlanPickerModal', () => {
  it('галочки отражают выбор группы, сводка — «выбрано из всех»', () => {
    const wrapper = mountModal({ vlanIds: ['v20'] })

    expect(rowsOf(wrapper).map((r) => (r.get('input').element as HTMLInputElement).checked)).toEqual([false, true, false])
    expect(wrapper.get('.picker-summary').text()).toBe('Выбрано VLAN: 1 из 3')
    expect(rowsOf(wrapper)[0].text()).toContain('10 — Серверы')
  })

  it('в сводку не попадают VLAN, которых нет у устройства (удалённые или чужие id)', () => {
    const wrapper = mountModal({ vlanIds: ['v10', 'gone'] })
    expect(wrapper.get('.picker-summary').text()).toBe('Выбрано VLAN: 1 из 3')
  })

  it('«Все VLAN» отмечен по признаку allVlans, а не по числу выбранных VLAN', () => {
    const allSelectedButNoFlag = mountModal({ vlanIds: ['v10', 'v20', 'v30'], allVlans: false })
    expect((allSelectedButNoFlag.get('.vlan-check-all input').element as HTMLInputElement).checked).toBe(false)

    const flagged = mountModal({ allVlans: true })
    expect((flagged.get('.vlan-check-all input').element as HTMLInputElement).checked).toBe(true)
  })

  it('клик по VLAN уходит событием toggle с идентификатором и состоянием, по «Все VLAN» — toggle-all', async () => {
    const wrapper = mountModal({ vlanIds: ['v20'] })

    await rowsOf(wrapper)[0].get('input').setValue(true)
    await rowsOf(wrapper)[1].get('input').setValue(false)
    await wrapper.get('.vlan-check-all input').setValue(true)

    expect(wrapper.emitted('toggle')).toEqual([
      ['v10', true],
      ['v20', false],
    ])
    expect(wrapper.emitted('toggle-all')).toEqual([[true]])

    await wrapper.setProps({ allVlans: true })
    await wrapper.get('.vlan-check-all input').setValue(false)
    expect(wrapper.emitted('toggle-all')).toEqual([[true], [false]])
  })

  it('поиск сужает список по номеру, имени и домену, а «Все VLAN» остаётся: он действует на все VLAN, а не на найденные', async () => {
    const wrapper = mountModal()
    const search = wrapper.get('input[aria-label="Поиск VLAN"]')

    await search.setValue('гост')
    expect(rowsOf(wrapper).map((r) => r.text())).toEqual(['20 — Гости'])
    expect(wrapper.find('.vlan-check-all').exists()).toBe(true)
    expect(wrapper.get('.picker-summary').text()).toBe('Выбрано VLAN: 0 из 3') // сводка — по всем VLAN, не по найденным

    await search.setValue('филиал')
    expect(rowsOf(wrapper)).toHaveLength(1)
    await search.setValue('30')
    expect(rowsOf(wrapper)).toHaveLength(1)
  })

  it('если ничего не найдено — подсказка вместо списка', async () => {
    const wrapper = mountModal()
    expect(wrapper.find('.picker-empty').exists()).toBe(false)

    await wrapper.get('input[aria-label="Поиск VLAN"]').setValue('нет такого')
    expect(rowsOf(wrapper)).toHaveLength(0)
    expect(wrapper.get('.picker-empty').text()).toBe('Ничего не найдено')
  })

  it('закрывается крестиком, «Готово» и кликом по подложке, но не нажатием внутри карточки', async () => {
    const wrapper = mountModal()
    await wrapper.get('button[aria-label="Закрыть"]').trigger('click')
    await wrapper.get('.modal-foot .btn-primary').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(2)

    const overlay = wrapper.get('.overlay')
    await overlay.trigger('mousedown')
    await overlay.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(3)

    await wrapper.get('.vlan-picker-modal').trigger('mousedown')
    await overlay.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(3)
  })

  it('окно не меняет выбор само: без событий родителя галочки остаются прежними', async () => {
    const wrapper = mountModal({ vlanIds: ['v10'] })
    await rowsOf(wrapper)[1].get('input').setValue(true)

    expect(wrapper.get('.picker-summary').text()).toBe('Выбрано VLAN: 1 из 3')
    await wrapper.setProps({ vlanIds: ['v10', 'v20'] })
    expect(wrapper.get('.picker-summary').text()).toBe('Выбрано VLAN: 2 из 3')
  })
})
