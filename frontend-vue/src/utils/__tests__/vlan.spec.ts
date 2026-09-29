import { describe, it, expect } from 'vitest'
import { mergeDomainVlansIntoDraft, vlanLabel } from '../vlan'
import type { DeviceVlanDraftRow, VLANDefinition } from '../../api/types'

function vlan(overrides: Partial<VLANDefinition> = {}): VLANDefinition {
  return { id: 'v-1', vlan_id: 10, name: 'Гостевой', description: '', domain_id: null, domain_name: '', devices: [], ...overrides }
}

describe('vlanLabel', () => {
  it('без домена — "номер — имя"', () => {
    expect(vlanLabel(vlan())).toBe('10 — Гостевой')
  })

  it('с доменом — добавляет "[имя домена]"', () => {
    expect(vlanLabel(vlan({ domain_id: 'dom-1', domain_name: 'Филиал-1' }))).toBe('10 — Гостевой [Филиал-1]')
  })
})

describe('mergeDomainVlansIntoDraft', () => {
  const definitions = [
    vlan({ id: 'v-30', vlan_id: 30, name: 'Серверы', description: 'DMZ', domain_id: 'dom-1' }),
    vlan({ id: 'v-10', vlan_id: 10, name: 'Гостевой', domain_id: 'dom-1' }),
    vlan({ id: 'v-99', vlan_id: 99, name: 'Чужой', domain_id: 'dom-2' }),
    vlan({ id: 'v-1', vlan_id: 1, name: 'default', domain_id: null }),
  ]

  it('добавляет только VLAN выбранного домена, по возрастанию номера, с описанием из определения', () => {
    const result = mergeDomainVlansIntoDraft([], definitions, 'dom-1')
    expect(result.map((r) => r.vlan_id)).toEqual(['v-10', 'v-30'])
    expect(result[1]).toEqual({ vlan_id: 'v-30', ip_address: '', prefix_length: '', is_management: false, description: 'DMZ' })
  })

  it('не дублирует уже присутствующие VLAN и не трогает существующие строки (включая пустые)', () => {
    const existing: DeviceVlanDraftRow[] = [
      { id: 'dv-1', vlan_id: 'v-10', ip_address: '10.0.0.1', prefix_length: '24', is_management: true, description: 'моё' },
      { vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' },
    ]
    const result = mergeDomainVlansIntoDraft(existing, definitions, 'dom-1')
    expect(result).toHaveLength(3)
    expect(result[0]).toBe(existing[0])
    expect(result[1]).toBe(existing[1])
    expect(result[2].vlan_id).toBe('v-30')
  })

  it('у домена нет VLAN или все уже добавлены — возвращает тот же массив (без мутации входа)', () => {
    const existing: DeviceVlanDraftRow[] = [{ vlan_id: 'v-10', ip_address: '', prefix_length: '', is_management: false, description: '' }, { vlan_id: 'v-30', ip_address: '', prefix_length: '', is_management: false, description: '' }]
    expect(mergeDomainVlansIntoDraft(existing, definitions, 'dom-1')).toBe(existing)
    expect(mergeDomainVlansIntoDraft(existing, definitions, 'dom-без-vlan')).toBe(existing)
    expect(existing).toHaveLength(2)
  })
})
