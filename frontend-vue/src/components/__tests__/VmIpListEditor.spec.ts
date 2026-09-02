import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import VmIpListEditor from '../VmIpListEditor.vue'
import type { VmIpDraftRow } from '../../api/types'

describe('VmIpListEditor.vue', () => {
  it('показывает подсказку, если IP-адреса не добавлены', () => {
    const wrapper = mount(VmIpListEditor, { props: { modelValue: [] } })
    expect(wrapper.text()).toContain('IP-адреса не добавлены')
  })

  it('добавляет пустую строку по клику на "+ IP-адрес"', async () => {
    const wrapper = mount(VmIpListEditor, { props: { modelValue: [] } })
    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted).toBeTruthy()
    expect(emitted![0][0]).toEqual([{ ip_address: '', prefix_length: '', purpose: '', is_management: false }])
  })

  it('обновляет поле, не мутируя исходный проп (контролируемый компонент)', async () => {
    const rows: VmIpDraftRow[] = [{ id: 'ip-1', ip_address: '10.0.0.1', prefix_length: '24', purpose: '', is_management: false }]
    const wrapper = mount(VmIpListEditor, { props: { modelValue: rows } })

    await wrapper.find('input[placeholder="IP-адрес"]').setValue('10.0.0.2')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ id: 'ip-1', ip_address: '10.0.0.2', prefix_length: '24', purpose: '', is_management: false }])
    expect(rows[0].ip_address).toBe('10.0.0.1') // проп не мутирован
  })

  it('отмечает IP как административный чекбоксом', async () => {
    const rows: VmIpDraftRow[] = [{ ip_address: '10.0.0.1', prefix_length: '', purpose: '', is_management: false }]
    const wrapper = mount(VmIpListEditor, { props: { modelValue: rows } })

    await wrapper.find('input[type="checkbox"]').setValue(true)

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as VmIpDraftRow[])[0].is_management).toBe(true)
  })

  it('удаляет строку по клику на кнопку удаления', async () => {
    const rows: VmIpDraftRow[] = [
      { id: 'ip-1', ip_address: '10.0.0.1', prefix_length: '', purpose: '', is_management: false },
      { id: 'ip-2', ip_address: '10.0.0.2', prefix_length: '', purpose: '', is_management: true },
    ]
    const wrapper = mount(VmIpListEditor, { props: { modelValue: rows } })

    await wrapper.findAll('.icon-btn.danger')[0].trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([rows[1]])
  })
})
