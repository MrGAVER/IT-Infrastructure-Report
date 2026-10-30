import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import VlanModeCascadeModal from '../VlanModeCascadeModal.vue'
import type { VlanModeCascadePlan } from '../../api/vlanModeCascade'
import { groupChange, makePlan, portChange, vlanRef } from '../../utils/__tests__/cascadePlanFixture'

// Группа соседа (сразу) + группа и порт редактируемого устройства (в форме), с снимаемым VLAN.
function bigPlan(patch: Partial<VlanModeCascadePlan> = {}): VlanModeCascadePlan {
  return makePlan({
    edited_device_id: 'dev-1',
    groups: [
      groupChange({
        id: 'g9',
        name: 'Магистраль',
        device_id: 'dev-2',
        device_name: 'sw-02',
        vlans_before: [vlanRef(10, 'Серверы'), vlanRef(20, 'Гости')],
        vlans_after: [vlanRef(10, 'Серверы')],
        dropped_vlans: [vlanRef(20, 'Гости')],
      }),
      groupChange({ id: 'g1', name: 'vmnic', device_id: 'dev-1', device_name: 'esxi-01', deferred: true, ports: [{ id: 'if-5', name: 'vmnic5' }] }),
    ],
    ports: [portChange({ id: 'if-7', name: 'vmnic7', device_id: 'dev-1', device_name: 'esxi-01', deferred: true })],
    devices: [
      { id: 'dev-1', name: 'esxi-01', deferred: true, port_count: 2, group_count: 1 },
      { id: 'dev-2', name: 'sw-02', deferred: false, port_count: 2, group_count: 1 },
    ],
    totals: { ports: 4, devices: 2, groups: 2, deferred_ports: 2, immediate_ports: 2, immediate_devices: 1, dropped_vlans: 1 },
    warnings: [
      { code: 'immediate', severity: 'warning', text: 'Изменения на других устройствах применяются сразу.' },
      { code: 'deferred', severity: 'info', text: 'Изменения на редактируемом устройстве сохранятся с формой.' },
    ],
    ...patch,
  })
}

function mountModal(plan: VlanModeCascadePlan, applying = false) {
  return mount(VlanModeCascadeModal, { props: { plan, applying, portLabel: '«Gi0/2» (sw-02)' } })
}

describe('VlanModeCascadeModal.vue', () => {
  it('заголовок и описание называют целевой режим, порт соседа и размер области изменения', () => {
    const wrapper = mountModal(bigPlan())

    expect(wrapper.find('h3').text()).toContain('Access')
    const desc = wrapper.find('.cascade-desc').text()
    expect(desc).toContain('«Gi0/2» (sw-02)')
    expect(desc).toContain('портов — 4')
    expect(desc).toContain('устройств — 2')
    expect(desc).toContain('групп — 2')
  })

  it('предупреждения показаны с уровнем: «Внимание» для warning и «К сведению» для info', () => {
    const wrapper = mountModal(bigPlan())

    const items = wrapper.findAll('.cascade-warning')
    expect(items.map((i) => i.attributes('data-code'))).toEqual(['immediate', 'deferred'])
    expect(items[0].classes()).toContain('warning')
    expect(items[0].text()).toContain('Внимание')
    expect(items[1].text()).toContain('К сведению')
  })

  it('по каждому устройству указано, применится оно сразу или сохранится с формой, и перечислены группы и порты', () => {
    const wrapper = mountModal(bigPlan())

    const devices = wrapper.findAll('.cascade-device')
    expect(devices.map((d) => d.find('b').text())).toEqual(['esxi-01', 'sw-02'])
    expect(devices[0].find('.cascade-badge').text()).toContain('сохранится с формой')
    expect(devices[0].find('.cascade-badge').classes()).toContain('deferred')
    expect(devices[1].find('.cascade-badge').text()).toBe('применится сразу')
    expect(devices[0].text()).toContain('Группа «vmnic» — 1 порт')
    expect(devices[0].text()).toContain('Порт «vmnic7»')
    expect(devices[1].text()).toContain('Группа «Магистраль» — 2 порта')
    expect(devices[1].text()).toContain('Gi0/2, Gi0/4')
    expect(devices[1].text()).toContain('Trunk → Access')
  })

  it('снимаемые VLAN названы в списке изменений: что останется и что будет снято', () => {
    const wrapper = mountModal(bigPlan())

    const vlans = wrapper.find('.cascade-item-vlans').text()
    expect(vlans).toContain('останется 10 «Серверы»')
    expect(vlans).toContain('будут сняты: 20 «Гости»')
  })

  it('кнопка применения недоступна, пока не отмечено «Я ознакомился с последствиями»', async () => {
    const wrapper = mountModal(bigPlan())
    const confirm = wrapper.find('.cascade-actions .btn-primary')

    expect(confirm.attributes('disabled')).toBeDefined()
    await confirm.trigger('click')
    expect(wrapper.emitted('confirm')).toBeUndefined()

    await wrapper.find('.cascade-ack input').setValue(true)
    expect(confirm.attributes('disabled')).toBeUndefined()
    expect(confirm.text()).toContain('Access (портов: 4)')
    await confirm.trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('«Отмена» и крестик отправляют cancel', async () => {
    const wrapper = mountModal(bigPlan())

    await wrapper.find('.cascade-actions .btn-secondary').trigger('click')
    await wrapper.find('.cascade-head .icon-btn').trigger('click')

    expect(wrapper.emitted('cancel')).toHaveLength(2)
  })

  it('во время применения всё заблокировано и показано «Применение…»', () => {
    const wrapper = mountModal(bigPlan(), true)

    expect(wrapper.find('.cascade-ack input').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.cascade-actions .btn-secondary').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.cascade-actions .btn-primary').text()).toBe('Применение…')
  })

  it('новый план (другой hash) сбрасывает подтверждение — его нужно дать заново', async () => {
    const wrapper = mountModal(bigPlan())
    await wrapper.find('.cascade-ack input').setValue(true)
    expect((wrapper.find('.cascade-ack input').element as HTMLInputElement).checked).toBe(true)

    await wrapper.setProps({ plan: bigPlan({ hash: 'hash-2' }) })

    expect((wrapper.find('.cascade-ack input').element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.find('.cascade-actions .btn-primary').attributes('disabled')).toBeDefined()
  })

  it('склонение числа портов группы: 1 порт, 2 порта, 5 портов, 11 портов, 12 портов, 21 порт', () => {
    const title = (count: number) => {
      const ports = Array.from({ length: count }, (_, i) => ({ id: `p${i}`, name: `p${i}` }))
      const plan = makePlan({ groups: [groupChange({ id: 'g1', name: 'Г', ports })], ports: [], totals: { ...makePlan().totals, ports: count, groups: 1 } })
      return mountModal(plan).find('.cascade-item-title').text()
    }

    expect(title(1)).toBe('Группа «Г» — 1 порт')
    expect(title(2)).toBe('Группа «Г» — 2 порта')
    expect(title(5)).toBe('Группа «Г» — 5 портов')
    expect(title(11)).toBe('Группа «Г» — 11 портов')
    expect(title(12)).toBe('Группа «Г» — 12 портов')
    expect(title(21)).toBe('Группа «Г» — 21 порт')
  })
})
