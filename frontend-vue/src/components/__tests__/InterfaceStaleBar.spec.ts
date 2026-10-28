import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import InterfaceStaleBar from '../InterfaceStaleBar.vue'
import { makeVlan } from '../../utils/__tests__/interfaceRowFixture'

const vlans = [makeVlan('v30', 30), makeVlan('v10', 10), makeVlan('v20', 20)]

function mountBar(props: Partial<InstanceType<typeof InterfaceStaleBar>['$props']> = {}) {
  return mount(InterfaceStaleBar, { props: { count: 3, vlanOptions: vlans, ...props } })
}

describe('InterfaceStaleBar', () => {
  it('показывает число подинтерфейсов, а VLAN для переноса предлагает по возрастанию номера', () => {
    const wrapper = mountBar({ count: 3 })

    expect(wrapper.text()).toContain('Подинтерфейсов на VLAN, не назначенном устройству: 3.')
    const options = wrapper.findAll('option').map((o) => o.text())
    expect(options[0]).toBe('Перенести все на VLAN…')
    expect(options.slice(1).map((t) => t.match(/\d+/)![0])).toEqual(['10', '20', '30'])
  })

  it('кнопка «Перенести» недоступна, пока VLAN не выбран; выбор отдаёт VLAN родителю и сбрасывается', async () => {
    const wrapper = mountBar()
    const button = wrapper.get('button')
    expect(button.attributes('disabled')).toBeDefined()

    await wrapper.get('select').setValue('v20')
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click')

    expect(wrapper.emitted('move')).toHaveLength(1)
    expect(wrapper.emitted('move')![0][0]).toMatchObject({ id: 'v20', vlan_id: 20 })
    expect((wrapper.get('select').element as HTMLSelectElement).value).toBe('')
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  })

  it('без VLAN у устройства выбор недоступен, и перенос ничего не отдаёт', async () => {
    const wrapper = mountBar({ vlanOptions: [] })

    expect(wrapper.get('select').attributes('disabled')).toBeDefined()
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('move')).toBeUndefined()
  })

  it('выбранный VLAN, которого уже нет среди VLAN устройства, не переносится', async () => {
    const wrapper = mountBar()
    await wrapper.get('select').setValue('v20')

    await wrapper.setProps({ vlanOptions: [makeVlan('v10', 10)] })
    await wrapper.get('button').trigger('click')

    expect(wrapper.emitted('move')).toBeUndefined()
  })
})
