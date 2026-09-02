import { describe, it, expect } from 'vitest'
import { vlanLabel } from '../vlan'
import type { VLANDefinition } from '../../api/types'

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
