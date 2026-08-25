import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DeviceInterfacesEditor from '../DeviceInterfacesEditor.vue'
import type { CatalogItem, InterfaceDraftRow } from '../../api/types'

const typeOptions: CatalogItem[] = [{ id: 't-eth', name: 'Ethernet' }]
const speedOptions: CatalogItem[] = [{ id: 's-1g', name: '1 Гбит/с' }]

function emptyRow(): InterfaceDraftRow {
  return { name: '', interface_type_id: '', mac_address: '', speed_id: '', is_management: false, is_data_transfer: false, description: '', vlan_ids: [], ips: [] }
}

describe('DeviceInterfacesEditor.vue', () => {
  it('показывает подсказку, если интерфейсы не добавлены', () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions } })
    expect(wrapper.text()).toContain('Интерфейсы не добавлены')
  })

  it('добавляет пустую строку по клику на "+ Интерфейс"', async () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions } })
    await wrapper.findAll('button.btn-secondary')[1].trigger('click') // 0 = "Сгенерировать", 1 = "+ Интерфейс"

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([emptyRow()])
  })

  it('генерирует интерфейсы по шаблону имени', async () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions } })

    const inputs = wrapper.findAll('.generator input')
    await inputs[0].setValue('3') // Количество
    await inputs[1].setValue('eth{n}') // Шаблон имени
    await wrapper.find('.generator select').setValue('t-eth') // Тип по умолчанию
    await wrapper.find('.generator button.btn-secondary').trigger('click') // Сгенерировать

    const emitted = wrapper.emitted('update:modelValue')!
    const rows = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
    expect(rows.map((r) => r.name)).toEqual(['eth1', 'eth2', 'eth3'])
    expect(rows.every((r) => r.interface_type_id === 't-eth')).toBe(true)
  })

  it('генерация сохраняет id и IP уже существующего интерфейса по индексу', async () => {
    const existing: InterfaceDraftRow[] = [{ id: 'if-1', name: 'old-name', interface_type_id: '', mac_address: '', speed_id: '', is_management: true, is_data_transfer: false, description: '', vlan_ids: ['vlan-1'], ips: [{ id: 'ip-1', ip_address: '10.0.0.1', prefix_length: '24', purpose: '' }] }]
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: existing, typeOptions, speedOptions } })

    await wrapper.find('.generator button.btn-secondary').trigger('click') // Сгенерировать с количеством по умолчанию (1)

    const emitted = wrapper.emitted('update:modelValue')!
    const rows = emitted[0][0] as InterfaceDraftRow[]
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ id: 'if-1', name: 'eth1', is_management: true, vlan_ids: ['vlan-1'], ips: existing[0].ips })
  })

  it('добавляет и удаляет IP-адрес интерфейса', async () => {
    const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1' }]
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions } })

    await wrapper.find('.ip-head button').trigger('click')
    let emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as InterfaceDraftRow[])[0].ips).toEqual([{ ip_address: '', prefix_length: '', purpose: '' }])

    const withIp: InterfaceDraftRow[] = [{ ...rows[0], ips: [{ id: 'ip-1', ip_address: '10.0.0.5', prefix_length: '', purpose: '' }] }]
    await wrapper.setProps({ modelValue: withIp })
    await wrapper.find('.ip-row .icon-btn.danger').trigger('click')
    emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[emitted.length - 1][0] as InterfaceDraftRow[])[0].ips).toEqual([])
  })

  it('удаляет интерфейс по клику на кнопку удаления карточки', async () => {
    const rows: InterfaceDraftRow[] = [
      { ...emptyRow(), id: 'if-1', name: 'eth1' },
      { ...emptyRow(), id: 'if-2', name: 'eth2' },
    ]
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions } })

    await wrapper.find('.iface-card-head .icon-btn.danger').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([rows[1]])
  })
})
