import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ISSourcesListEditor from '../ISSourcesListEditor.vue'
import type { Container, Device, ISSourceDraftRow, VirtualMachine } from '../../api/types'

const devices: Device[] = [
  { id: 'dev-1', system_name: 'srv-01', serial_number: 'SN-1' } as Device,
  { id: 'dev-2', system_name: 'srv-02', serial_number: 'SN-2' } as Device,
]
const vms: VirtualMachine[] = [
  { id: 'vm-1', name: 'app-vm-1', physical_device_id: 'dev-1' } as VirtualMachine,
  { id: 'vm-2', name: 'app-vm-2', physical_device_id: 'dev-2' } as VirtualMachine,
]
const containers: Container[] = [{ id: 'ct-1', name: 'nginx-container', virtual_machine_id: null, physical_device_id: null, runtime: null, runtime_version: null, purpose: null }]

function emptyRow(): ISSourceDraftRow {
  return { source_type: 'manual', physical_device_id: '', virtual_machine_id: '', container_id: '', ip_address: '', purpose: '', role: '', external_interaction: false }
}

const baseProps = { deviceOptions: devices, vmOptions: vms, containerOptions: containers }

describe('ISSourcesListEditor.vue', () => {
  it('показывает подсказку, если источники не добавлены', () => {
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: [] } })
    expect(wrapper.text()).toContain('Не добавлено')
  })

  it('добавляет пустую строку с типом "вручную" по умолчанию', async () => {
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: [] } })
    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([emptyRow()])
  })

  it('при смене типа сбрасывает device/vm/container/ip выбранной строки', async () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'manual', ip_address: '10.0.0.1' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    await wrapper.find('.source-grid select').setValue('device')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ ...emptyRow(), source_type: 'device' }])
  })

  it('при выборе ВМ подставляет её хост и переключает тип на "vm"', async () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'vm' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    const vmSelect = wrapper.findAll('.source-grid select')[2] // 0=type, 1=device, 2=vm
    await vmSelect.setValue('vm-2')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ ...emptyRow(), source_type: 'vm', virtual_machine_id: 'vm-2', physical_device_id: 'dev-2' }])
  })

  it('при ручном выборе устройства сбрасывает уже выбранную ВМ', async () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'vm', virtual_machine_id: 'vm-1', physical_device_id: 'dev-1' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    const deviceSelect = wrapper.findAll('.source-grid select')[1]
    await deviceSelect.setValue('dev-2')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ ...emptyRow(), source_type: 'vm', physical_device_id: 'dev-2', virtual_machine_id: '' }])
  })

  it('IP-адрес редактируется только при типе "вручную"', () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'device' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    expect(wrapper.find('.source-grid input').element).toHaveProperty('disabled', true)
  })

  it('удаляет строку по клику на кнопку удаления', async () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), id: 's1' }, { ...emptyRow(), id: 's2', purpose: 'второй' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    await wrapper.findAll('.icon-btn.danger')[0].trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([rows[1]])
  })
})
