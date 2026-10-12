import { describe, it, expect, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import StackMemberAddConfirmModal from '../StackMemberAddConfirmModal.vue'
import type { StackMemberPreview } from '../../api/types'

const PREVIEW: StackMemberPreview = {
  stack_name: 'Кластер МЭ',
  device_name: 'fw-b',
  already_member: false,
  unchanged_count: 1,
  changes: [
    { vlan_id: 'v-10', vlan_number: 10, vlan_name: 'mgmt', action: 'update', before: { ip_address: '10.0.10.9', prefix_length: 24, is_management: false }, after: { ip_address: '10.0.10.1', prefix_length: 24, is_management: true } },
    { vlan_id: 'v-20', vlan_number: 20, vlan_name: 'users', action: 'add', before: null, after: { ip_address: '10.0.20.1', prefix_length: 24, is_management: false } },
  ],
}

const byId = (id: string) => document.body.querySelector(`[data-testid="${id}"]`) as HTMLElement | null

afterEach(() => {
  document.body.innerHTML = ''
})

describe('StackMemberAddConfirmModal.vue', () => {
  it('показывает устройство, стек, сводку и по строке на каждое изменение (что добавится и что заменится)', () => {
    mount(StackMemberAddConfirmModal, { props: { preview: PREVIEW, busy: false } })

    expect(byId('stack-member-confirm')?.textContent).toContain('«fw-b»')
    expect(byId('stack-member-confirm')?.textContent).toContain('«Кластер МЭ»')
    const summary = byId('stack-member-confirm-summary')?.textContent ?? ''
    expect(summary).toContain('VLAN будет назначено: 1')
    expect(summary).toContain('значений будет заменено: 1')
    expect(summary).toContain('уже совпадает: 1')
    const rows = Array.from(document.body.querySelectorAll('[data-testid="stack-member-change"]')).map((r) => r.textContent ?? '')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toContain('10 — mgmt')
    expect(rows[0]).toContain('Будет заменено: 10.0.10.9/24 → 10.0.10.1/24, «Управление»')
    expect(rows[1]).toContain('Будет назначен VLAN: 10.0.20.1/24')
  })

  it('кнопки: «Добавить в стек» подтверждает, «Отказаться» и клик по подложке отменяют', () => {
    const wrapper = mount(StackMemberAddConfirmModal, { props: { preview: PREVIEW, busy: false } })

    byId('stack-member-accept')!.click()
    byId('stack-member-cancel')!.click()
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    expect(wrapper.emitted('cancel')).toHaveLength(1)

    const overlay = byId('stack-member-confirm')!
    overlay.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    overlay.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(wrapper.emitted('cancel')).toHaveLength(2)
  })

  it('во время добавления кнопки заблокированы (нет двойной отправки)', () => {
    mount(StackMemberAddConfirmModal, { props: { preview: PREVIEW, busy: true } })
    expect((byId('stack-member-accept') as HTMLButtonElement).disabled).toBe(true)
    expect((byId('stack-member-cancel') as HTMLButtonElement).disabled).toBe(true)
  })
})
