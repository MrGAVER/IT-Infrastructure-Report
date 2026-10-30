import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AllVlansChoiceModal from '../AllVlansChoiceModal.vue'
import type { VLANDefinition } from '../../api/types'

const vlan = (id: string, number: number): VLANDefinition => ({
  id,
  vlan_id: number,
  name: `VLAN ${number}`,
  description: '',
  domain_id: null,
  domain_name: '',
  devices: [],
})
const options = [vlan('a10', 10), vlan('a20', 20), vlan('a30', 30)]

function mountModal(props: Partial<InstanceType<typeof AllVlansChoiceModal>['$props']> = {}) {
  return mount(AllVlansChoiceModal, {
    props: {
      portLabel: '«Gi0/24» (sw-02)',
      sourceLabel: 'текущего порта',
      description: '«Все VLAN»: у порта «Gi0/1» стоит, у порта «Gi0/24» не стоит.',
      sourceValue: { allVlans: true, vlanIds: [] },
      missing: [],
      options,
      ...props,
    },
    attachTo: document.body,
  })
}
const emitted = <T>(wrapper: ReturnType<typeof mountModal>, name: string) => wrapper.emitted(name)!.at(-1)![0] as T

describe('AllVlansChoiceModal', () => {
  it('по умолчанию выбрано значение источника: «Применить» отдаёт его', async () => {
    const wrapper = mountModal()
    expect(wrapper.get('[data-testid="choice-source-text"]').text()).toBe('Все VLAN')

    await wrapper.get('[data-testid="choice-apply"]').trigger('click')

    expect(emitted(wrapper, 'confirm')).toEqual({ allVlans: true, vlanIds: [] })
    wrapper.unmount()
  })

  it('набор источника показан номерами, а номера, которых нет у устройства порта, — предупреждением', () => {
    const wrapper = mountModal({ sourceValue: { allVlans: false, vlanIds: ['a10', 'a30'] }, missing: [99] })

    expect(wrapper.get('[data-testid="choice-source-text"]').text()).toBe('VLAN 10, 30')
    expect(wrapper.get('[data-testid="choice-missing"]').text()).toContain('нет VLAN 99')
    wrapper.unmount()
  })

  it('«Другое значение»: окно выбора VLAN стартует со значения источника, ручной выбор снимает «Все VLAN» и уходит в confirm', async () => {
    const wrapper = mountModal()

    await wrapper.get('[data-testid="choice-other"]').setValue(true)
    expect(wrapper.get('[data-testid="choice-other-text"]').text()).toBe('Все VLAN')
    await wrapper.get('[data-testid="choice-pick"]').trigger('click')
    const checks = wrapper.findAll('.vlan-picker-modal .vlan-check:not(.vlan-check-all) input[type="checkbox"]')
    expect(checks).toHaveLength(3)
    expect(checks.every((c) => (c.element as HTMLInputElement).checked)).toBe(true) // «Все VLAN» отмечает все VLAN устройства
    await checks[1].setValue(false) // снять VLAN 20
    await wrapper.findAll('.vlan-picker-modal .picker-foot button')[0].trigger('click') // «Готово»

    expect(wrapper.find('.vlan-picker-modal').exists()).toBe(false)
    expect(wrapper.get('[data-testid="choice-other-text"]').text()).toBe('VLAN 10, 30')
    await wrapper.get('[data-testid="choice-apply"]').trigger('click')
    expect(emitted(wrapper, 'confirm')).toEqual({ allVlans: false, vlanIds: ['a10', 'a30'] })
    wrapper.unmount()
  })

  it('«Другое значение»: галочка «Все VLAN» в окне выбора возвращает признак; «Отмена» ничего не подтверждает', async () => {
    const wrapper = mountModal({ sourceValue: { allVlans: false, vlanIds: ['a10'] } })

    await wrapper.get('[data-testid="choice-other"]').setValue(true)
    await wrapper.get('[data-testid="choice-pick"]').trigger('click')
    await wrapper.get('.vlan-picker-modal .vlan-check-all input').setValue(true)
    await wrapper.findAll('.vlan-picker-modal .picker-foot button')[0].trigger('click')
    expect(wrapper.get('[data-testid="choice-other-text"]').text()).toBe('Все VLAN')

    await wrapper.findAll('.choice-foot button')[0].trigger('click') // «Отмена»
    expect(wrapper.emitted('confirm')).toBeUndefined()
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    wrapper.unmount()
  })
})
