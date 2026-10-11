import { describe, it, expect } from 'vitest'
import {
  adaptVlanIdsToMode,
  buildPortConfigPatch,
  cloneDraft,
  differencesFromNeighbor,
  isDirty,
  numbersOf,
  sameIds,
  validateDraft,
  vlanIdsForNumbers,
  type PortDraft,
} from '../portEdit'
import type { VLANDefinition } from '../../api/types'

const vlan = (id: string, number: number, name = ''): VLANDefinition => ({ id, vlan_id: number, name, description: '', domain_id: null, domain_name: '', devices: [] })
const OPTIONS = [vlan('a', 10), vlan('b', 20), vlan('c', 30), vlan('c2', 30, 'дубль в другом домене')]
const draft = (overrides: Partial<PortDraft> = {}): PortDraft => ({ role: 'data', mode: 'trunk', vlanIds: [], allVlans: false, ...overrides })

describe('portEdit — наборы VLAN', () => {
  it('sameIds сравнивает без учёта порядка и повторов', () => {
    expect(sameIds(['a', 'b'], ['b', 'a'])).toBe(true)
    expect(sameIds(['a', 'a'], ['a'])).toBe(true)
    expect(sameIds(['a'], ['a', 'b'])).toBe(false)
    expect(sameIds([], [])).toBe(true)
  })

  it('vlanIdsForNumbers: по номеру берётся первая запись, недоступные номера возвращаются отдельно', () => {
    expect(vlanIdsForNumbers(OPTIONS, [30, 10, 99])).toEqual({ ids: ['a', 'c'], missing: [99] })
    expect(vlanIdsForNumbers(OPTIONS, [])).toEqual({ ids: [], missing: [] })
    expect(vlanIdsForNumbers(OPTIONS, [10, 10])).toEqual({ ids: ['a'], missing: [] })
  })

  it('numbersOf: номера выбранных записей по возрастанию, неизвестные id пропускаются', () => {
    expect(numbersOf(OPTIONS, ['c', 'a', 'нет такого'])).toEqual([10, 30])
    expect(numbersOf(OPTIONS, ['c', 'c2'])).toEqual([30]) // одна и та же метка в двух доменах — один тег
  })

  it('adaptVlanIdsToMode: в access остаётся VLAN с наименьшим номером, в trunk набор сохраняется', () => {
    expect(adaptVlanIdsToMode(OPTIONS, ['c', 'b', 'a'], 'access')).toEqual(['a'])
    expect(adaptVlanIdsToMode(OPTIONS, ['c', 'b'], 'trunk')).toEqual(['c', 'b'])
    expect(adaptVlanIdsToMode(OPTIONS, ['b'], 'access')).toEqual(['b'])
    expect(adaptVlanIdsToMode(OPTIONS, [], 'access')).toEqual([])
  })

  it('adaptVlanIdsToMode не меняет исходный массив', () => {
    const ids = ['c', 'a']
    adaptVlanIdsToMode(OPTIONS, ids, 'access')
    expect(ids).toEqual(['c', 'a'])
  })
})

describe('portEdit — сравнение с соседом', () => {
  const neighbor = { role: 'data' as const, mode: 'trunk' as const, vlans: [10, 20] }

  it('совпадающая конфигурация — различий нет', () => {
    expect(differencesFromNeighbor(draft(), [20, 10], neighbor)).toEqual([])
  })

  it('различия называются в порядке «роль, режим, VLAN»', () => {
    expect(differencesFromNeighbor(draft({ role: 'management', mode: 'access' }), [10], neighbor)).toEqual(['role', 'mode', 'vlans'])
    expect(differencesFromNeighbor(draft(), [10, 20, 30], neighbor)).toEqual(['vlans'])
  })

  it('неизвестные у соседа роль и режим (порт удалён) различием не считаются', () => {
    expect(differencesFromNeighbor(draft(), [], { role: null, mode: null, vlans: [] })).toEqual([])
  })
})

describe('portEdit — тело запроса и проверка', () => {
  const initial = draft({ vlanIds: ['a'] })

  it('ничего не менялось — отправлять нечего', () => {
    expect(buildPortConfigPatch(initial, cloneDraft(initial), { modeChanged: false, vlansLocked: false })).toBeNull()
  })

  it('роль без VLAN: в теле только роль и проверочный режим', () => {
    expect(buildPortConfigPatch(initial, draft({ role: 'management', vlanIds: ['a'] }), { modeChanged: false, vlansLocked: false })).toEqual({ role: 'management', mode: 'trunk' })
  })

  it('VLAN: уходит полный набор без повторов', () => {
    expect(buildPortConfigPatch(initial, draft({ vlanIds: ['a', 'b', 'b'] }), { modeChanged: false, vlansLocked: false })).toEqual({ vlan_ids: ['a', 'b'], mode: 'trunk' })
    expect(buildPortConfigPatch(initial, draft({ vlanIds: [] }), { modeChanged: false, vlansLocked: false })).toEqual({ vlan_ids: [], mode: 'trunk' }) // снять все
  })

  it('после смены режима набор отправляется заново, даже если он тот же: каскад мог его урезать', () => {
    const after = draft({ mode: 'access', vlanIds: ['a'] })
    expect(buildPortConfigPatch(draft({ mode: 'trunk', vlanIds: ['a'] }), after, { modeChanged: true, vlansLocked: false })).toEqual({ vlan_ids: ['a'], mode: 'access' })
  })

  it('порт в группе: набор VLAN не отправляется никогда, роль — отправляется', () => {
    expect(buildPortConfigPatch(initial, draft({ vlanIds: ['b'] }), { modeChanged: false, vlansLocked: true })).toBeNull()
    expect(buildPortConfigPatch(initial, draft({ role: 'none', vlanIds: ['b'] }), { modeChanged: true, vlansLocked: true })).toEqual({ role: 'none', mode: 'trunk' })
  })

  it('«Все VLAN»: признак уходит без набора, а его снятие — набором вместе с all_vlans: false', () => {
    const flagged = draft({ vlanIds: ['a', 'b'], allVlans: true })
    expect(buildPortConfigPatch(initial, flagged, { modeChanged: false, vlansLocked: false })).toEqual({ all_vlans: true, mode: 'trunk' })
    // признак уже стоял и не менялся — отправлять нечего (набор зеркалит VLAN устройства, а не правка пользователя)
    expect(buildPortConfigPatch(flagged, cloneDraft(flagged), { modeChanged: false, vlansLocked: false })).toBeNull()
    // тот же полный набор вручную: признак снимается, набор уходит явно — без all_vlans: false сервер оставил бы признак
    expect(buildPortConfigPatch(flagged, draft({ vlanIds: ['a', 'b'], allVlans: false }), { modeChanged: false, vlansLocked: false })).toEqual({ vlan_ids: ['a', 'b'], all_vlans: false, mode: 'trunk' })
    expect(buildPortConfigPatch(flagged, draft({ vlanIds: [], allVlans: false }), { modeChanged: false, vlansLocked: false })).toEqual({ vlan_ids: [], all_vlans: false, mode: 'trunk' })
  })

  it('«Все VLAN» после смены режима отправляется заново, у порта в группе — не отправляется вовсе', () => {
    const flagged = draft({ vlanIds: ['a', 'b'], allVlans: true })
    expect(buildPortConfigPatch(draft({ mode: 'access', vlanIds: ['a'] }), flagged, { modeChanged: true, vlansLocked: false })).toEqual({ all_vlans: true, mode: 'trunk' })
    expect(buildPortConfigPatch(initial, flagged, { modeChanged: false, vlansLocked: true })).toBeNull()
  })

  it('isDirty учитывает признак «Все VLAN», даже когда набор совпал', () => {
    const manual = draft({ vlanIds: ['a', 'b'], allVlans: false })
    expect(isDirty(manual, draft({ vlanIds: ['b', 'a'], allVlans: true }))).toBe(true)
    expect(isDirty(manual, cloneDraft(manual))).toBe(false)
  })

  it('isDirty: роль, режим и набор VLAN (без учёта порядка)', () => {
    expect(isDirty(initial, cloneDraft(initial))).toBe(false)
    expect(isDirty(draft({ vlanIds: ['a', 'b'] }), draft({ vlanIds: ['b', 'a'] }))).toBe(false)
    expect(isDirty(initial, draft({ role: 'none', vlanIds: ['a'] }))).toBe(true)
    expect(isDirty(initial, draft({ mode: 'access', vlanIds: ['a'] }))).toBe(true)
    expect(isDirty(initial, draft({ vlanIds: [] }))).toBe(true)
  })

  it('validateDraft: в access не более одного VLAN, кроме порта в группе (набор не отправляется)', () => {
    expect(validateDraft(draft({ mode: 'access', vlanIds: ['a', 'b'] }), { vlansLocked: false })).toContain('access')
    expect(validateDraft(draft({ mode: 'access', vlanIds: ['a', 'a'] }), { vlansLocked: false })).toBeNull()
    expect(validateDraft(draft({ mode: 'access', vlanIds: ['a', 'b'] }), { vlansLocked: true })).toBeNull()
    expect(validateDraft(draft({ mode: 'trunk', vlanIds: ['a', 'b'] }), { vlansLocked: false })).toBeNull()
  })

  it('cloneDraft не разделяет массив VLAN с исходным', () => {
    const copy = cloneDraft(initial)
    copy.vlanIds.push('z')
    expect(initial.vlanIds).toEqual(['a'])
  })
})
