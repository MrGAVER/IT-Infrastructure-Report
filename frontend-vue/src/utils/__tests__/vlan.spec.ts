import { describe, it, expect } from 'vitest'
import { filterVlansForDeviceDomains, mergeDomainVlansIntoDraft, reconcileVlanIds, removeDomainVlansFromDraft, vlanLabel } from '../vlan'
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

describe('removeDomainVlansFromDraft', () => {
  const definitions = [
    vlan({ id: 'v-10', vlan_id: 10, name: 'A', domain_id: 'dom-1' }),
    vlan({ id: 'v-20', vlan_id: 20, name: 'B', domain_id: 'dom-1' }),
    vlan({ id: 'v-99', vlan_id: 99, name: 'C', domain_id: 'dom-2' }),
    vlan({ id: 'v-1', vlan_id: 1, name: 'default', domain_id: null }),
  ]
  const draft = (vlanId: string, extra: Partial<DeviceVlanDraftRow> = {}): DeviceVlanDraftRow => ({
    vlan_id: vlanId, ip_address: '', prefix_length: '', is_management: false, description: '', ...extra,
  })

  it('убирает несохранённые строки VLAN отменяемого домена (в том числе введённые вручную), остальные не трогает', () => {
    const rows = [draft('v-10'), draft('v-99'), draft('v-1'), draft('v-20', { ip_address: '10.0.20.1' }), draft('')]
    expect(removeDomainVlansFromDraft(rows, definitions, 'dom-1').map((r) => r.vlan_id)).toEqual(['v-99', 'v-1', ''])
  })

  it('сохранённые строки (с id) остаются: они не могут принадлежать домену без членства', () => {
    const rows = [draft('v-10', { id: 'dv-1' }), draft('v-20')]
    expect(removeDomainVlansFromDraft(rows, definitions, 'dom-1')).toEqual([rows[0]])
  })

  it('нечего убирать — тот же массив, вход не мутируется', () => {
    const rows = [draft('v-99'), draft('v-1')]
    expect(removeDomainVlansFromDraft(rows, definitions, 'dom-1')).toBe(rows)
    expect(rows).toHaveLength(2)
  })

  it('обратна mergeDomainVlansIntoDraft: включение и отмена возвращают исходный черновик', () => {
    const original = [draft('v-99')]
    const joined = mergeDomainVlansIntoDraft(original, definitions, 'dom-1')
    expect(joined).toHaveLength(3)
    expect(removeDomainVlansFromDraft(joined, definitions, 'dom-1')).toEqual(original)
  })
})

describe('filterVlansForDeviceDomains', () => {
  const definitions = [
    vlan({ id: 'v-1', vlan_id: 1, name: 'default', domain_id: null }),
    vlan({ id: 'v-10', vlan_id: 10, name: 'Гостевой', domain_id: 'dom-1' }),
    vlan({ id: 'v-20', vlan_id: 20, name: 'Серверы', domain_id: 'dom-1' }),
    vlan({ id: 'v-99', vlan_id: 99, name: 'Чужой', domain_id: 'dom-2' }),
    vlan({ id: 'v-50', vlan_id: 50, name: 'Другой', domain_id: 'dom-3' }),
  ]

  it('устройство не в домене — только VLAN без домена', () => {
    expect(filterVlansForDeviceDomains(definitions, new Set()).map((d) => d.id)).toEqual(['v-1'])
  })

  it('устройство в домене — только VLAN этого домена, VLAN без домена и чужих доменов скрыты', () => {
    expect(filterVlansForDeviceDomains(definitions, new Set(['dom-1'])).map((d) => d.id)).toEqual(['v-10', 'v-20'])
  })

  it('устройство в нескольких доменах — объединение их VLAN в исходном порядке', () => {
    expect(filterVlansForDeviceDomains(definitions, new Set(['dom-2', 'dom-1'])).map((d) => d.id)).toEqual(['v-10', 'v-20', 'v-99'])
  })

  it('домен без VLAN даёт пустой список, входной массив не мутируется', () => {
    const copy = [...definitions]
    expect(filterVlansForDeviceDomains(definitions, new Set(['dom-unknown']))).toEqual([])
    expect(definitions).toEqual(copy)
  })
})

describe('reconcileVlanIds', () => {
  const opts = (...ids: string[]) => ids.map((id) => ({ id }))

  it('trunk с выбранными всеми прежними VLAN получает новые VLAN в конец', () => {
    expect(reconcileVlanIds(['a', 'b'], 'trunk', opts('a', 'b'), opts('a', 'b', 'c', 'd'))).toEqual(['a', 'b', 'c', 'd'])
  })

  it('trunk, где выбраны не все прежние VLAN, новые VLAN не получает — «Все VLAN» там и не было', () => {
    const ids = ['a']
    expect(reconcileVlanIds(ids, 'trunk', opts('a', 'b'), opts('a', 'b', 'c'))).toBe(ids)
  })

  it('access и пустой режим новых VLAN не получают', () => {
    const ids = ['a', 'b']
    expect(reconcileVlanIds(ids, 'access', opts('a', 'b'), opts('a', 'b', 'c'))).toBe(ids)
    expect(reconcileVlanIds(ids, '', opts('a', 'b'), opts('a', 'b', 'c'))).toBe(ids)
  })

  it('первая загрузка (прежних опций не было) ничего не раздаёт: «все выбраны» вырожденно истинно', () => {
    const ids: string[] = []
    expect(reconcileVlanIds(ids, 'trunk', [], opts('a', 'b'))).toBe(ids)
  })

  it('убирает VLAN, переставшие быть допустимыми, в любом режиме', () => {
    expect(reconcileVlanIds(['a', 'b'], 'trunk', opts('a', 'b'), opts('a'))).toEqual(['a'])
    expect(reconcileVlanIds(['b'], 'access', opts('a', 'b'), opts('a'))).toEqual([])
  })

  it('одновременное удаление и добавление: «Все VLAN» уже неполное — новые VLAN не добавляются', () => {
    expect(reconcileVlanIds(['a', 'b'], 'trunk', opts('a', 'b'), opts('a', 'c'))).toEqual(['a'])
  })

  it('не трогает VLAN вне каталога опций, если опции не менялись (VLAN, назначенные ранее), и возвращает тот же массив', () => {
    const ids = ['legacy', 'a']
    expect(reconcileVlanIds(ids, 'trunk', opts('a'), opts('a'))).toBe(ids)
  })

  it('не мутирует входной массив', () => {
    const ids = ['a', 'b']
    reconcileVlanIds(ids, 'trunk', opts('a', 'b'), opts('a', 'b', 'c'))
    expect(ids).toEqual(['a', 'b'])
  })
})
