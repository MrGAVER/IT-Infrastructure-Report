import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DeviceVlanListEditor from '../DeviceVlanListEditor.vue'
import type { DeviceVlanDraftRow, VLANDefinition } from '../../api/types'

const vlanOptions: VLANDefinition[] = [
  { id: 'v-10', vlan_id: 10, name: 'Мониторинг', description: '', domain_id: null, domain_name: '', devices: [] },
  { id: 'v-20', vlan_id: 20, name: 'Управление', description: '', domain_id: 'dom-1', domain_name: 'Ядро сети', devices: [] },
]

describe('DeviceVlanListEditor.vue', () => {
  it('показывает подсказку, если VLAN не назначены', () => {
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [], vlanOptions } })
    expect(wrapper.text()).toContain('VLAN не назначены')
  })

  it('добавляет пустую строку по клику на "+ VLAN"', async () => {
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [], vlanOptions } })
    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' }])
  })

  it('показывает домен в подписи опции VLAN', () => {
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [{ vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' }], vlanOptions } })
    expect(wrapper.find('select.col-vlan').text()).toContain('20 — Управление [Ядро сети]')
  })

  it('обновляет IP-адрес, не мутируя исходный проп', async () => {
    const rows: DeviceVlanDraftRow[] = [{ id: 'dv-1', vlan_id: 'v-10', ip_address: '', prefix_length: '', is_management: false, description: '' }]
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions } })

    await wrapper.find('input.col-ip').setValue('10.0.10.5')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ id: 'dv-1', vlan_id: 'v-10', ip_address: '10.0.10.5', prefix_length: '', is_management: false, description: '' }])
    expect(rows[0].ip_address).toBe('')
  })

  it('отмечает VLAN как управляющий чекбоксом', async () => {
    const rows: DeviceVlanDraftRow[] = [{ vlan_id: 'v-10', ip_address: '', prefix_length: '', is_management: false, description: '' }]
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions } })

    await wrapper.find('input[type="checkbox"]').setValue(true)

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as DeviceVlanDraftRow[])[0].is_management).toBe(true)
  })

  it('удаляет строку по клику на кнопку удаления', async () => {
    const rows: DeviceVlanDraftRow[] = [
      { id: 'dv-1', vlan_id: 'v-10', ip_address: '', prefix_length: '', is_management: false, description: '' },
      { id: 'dv-2', vlan_id: 'v-20', ip_address: '', prefix_length: '', is_management: true, description: '' },
    ]
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions } })

    await wrapper.findAll('.icon-btn.danger')[0].trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([rows[1]])
  })
})
