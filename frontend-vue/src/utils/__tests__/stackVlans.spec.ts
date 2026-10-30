import { describe, expect, it } from 'vitest'
import type { DeviceVlanDraftRow, StackMemberChange, StackVlanRow } from '../../api/types'
import {
  describeMemberChange,
  formatStackValues,
  lockedVlanReasons,
  matchesSharedSetting,
  mergeSharedSettingsIntoDraft,
  sharedSettingPayload,
  stackVlanStatus,
  validateSharedIp,
} from '../stackVlans'

function row(overrides: Partial<StackVlanRow> = {}): StackVlanRow {
  return {
    vlan_id: 'v-10',
    vlan_number: 10,
    vlan_name: 'mgmt',
    domain_id: null,
    is_shared: true,
    ip_address: '10.0.10.1',
    prefix_length: 24,
    is_management: true,
    is_uniform: true,
    assigned_count: 3,
    member_count: 3,
    members: [
      {
        physical_device_id: 'dev-1',
        device_name: 'fw-1',
        assigned: true,
        ip_address: '10.0.10.1',
        prefix_length: 24,
        is_management: true,
        description: 'кластер',
      },
    ],
    ...overrides,
  }
}

describe('stackVlanStatus', () => {
  it('строка без применённой настройки', () => {
    expect(stackVlanStatus(null).kind).toBe('new')
  })

  it('применено ко всем участникам — ok со счётчиком', () => {
    expect(stackVlanStatus(row())).toEqual({ kind: 'ok', text: 'Применено ко всем (3)' })
  })

  it('VLAN назначен не всем — warn с количеством', () => {
    expect(stackVlanStatus(row({ is_uniform: false, assigned_count: 2 }))).toEqual({ kind: 'warn', text: 'VLAN назначен не у всех: 2 из 3' })
  })

  it('назначен всем, но значения у некоторых отличаются — warn', () => {
    expect(stackVlanStatus(row({ is_uniform: false })).text).toBe('У некоторых устройств значения отличаются от настройки')
  })
})

describe('validateSharedIp', () => {
  it('корректная и пустая пара допустимы', () => {
    expect(validateSharedIp('10.0.10.5', '24')).toBeNull()
    expect(validateSharedIp('', '')).toBeNull()
    expect(validateSharedIp('  ', ' ')).toBeNull()
  })

  it('IP без префикса и префикс без IP отклоняются — как на бэкенде', () => {
    expect(validateSharedIp('10.0.10.5', '')).toContain('префикс')
    expect(validateSharedIp('', '24')).toContain('IP-адрес')
  })

  it('некорректный IPv4 (в том числе IPv6, который пока не нужен) и префикс вне 0–32', () => {
    expect(validateSharedIp('999.1.1.1', '24')).toBe('Некорректный IPv4-адрес')
    expect(validateSharedIp('fe80::1', '64')).toBe('Некорректный IPv4-адрес')
    expect(validateSharedIp('10.0.10.5', '33')).toBe('Префикс — целое число от 0 до 32')
    expect(validateSharedIp('10.0.10.5', '2.5')).toBe('Префикс — целое число от 0 до 32')
  })
})

describe('sharedSettingPayload / matchesSharedSetting', () => {
  it('приводит префикс к числу, режет пробелы и несёт флаг «Управление»', () => {
    expect(sharedSettingPayload(' 10.0.10.5 ', '24', true)).toEqual({ ip_address: '10.0.10.5', prefix_length: 24, is_management: true })
  })

  it('пустые поля — null, а префикс 0 — не «пусто»', () => {
    expect(sharedSettingPayload('', '', false)).toEqual({ ip_address: null, prefix_length: null, is_management: false })
    expect(sharedSettingPayload('0.0.0.0', '0', false).prefix_length).toBe(0)
  })

  it('«нечего применять» только когда всё применено и ввод, включая флаг, не меняет настройку', () => {
    expect(matchesSharedSetting(row(), '10.0.10.1', '24', true)).toBe(true)
    expect(matchesSharedSetting(row(), '10.0.10.1', '24', false)).toBe(false) // изменился только флаг
    expect(matchesSharedSetting(row(), '10.0.10.2', '24', true)).toBe(false)
    expect(matchesSharedSetting(row({ is_uniform: false }), '10.0.10.1', '24', true)).toBe(false)
    expect(matchesSharedSetting(null, '', '', false)).toBe(false)
  })
})

describe('текст изменений при добавлении в стек', () => {
  const after = { ip_address: '10.0.10.1', prefix_length: 24, is_management: true }
  const add: StackMemberChange = { vlan_id: 'v-10', vlan_number: 10, vlan_name: 'mgmt', action: 'add', before: null, after }
  const update: StackMemberChange = { ...add, action: 'update', before: { ip_address: '10.0.10.9', prefix_length: 25, is_management: false } }

  it('formatStackValues: адрес с префиксом, флаг и «адрес не задан»', () => {
    expect(formatStackValues(after)).toBe('10.0.10.1/24, «Управление»')
    expect(formatStackValues({ ip_address: null, prefix_length: null, is_management: false })).toBe('адрес не задан')
  })

  it('добавление VLAN и замена значений («было → станет»)', () => {
    expect(describeMemberChange(add)).toBe('Будет назначен VLAN: 10.0.10.1/24, «Управление»')
    expect(describeMemberChange(update)).toBe('Будет заменено: 10.0.10.9/25 → 10.0.10.1/24, «Управление»')
  })
})

describe('lockedVlanReasons', () => {
  it('причина блокировки для каждого общего VLAN с названием стека', () => {
    const reasons = lockedVlanReasons([row(), row({ vlan_id: 'v-20' })], 'Ядро')
    expect(Object.keys(reasons)).toEqual(['v-10', 'v-20'])
    expect(reasons['v-10']).toContain('«Ядро»')
  })
})

describe('mergeSharedSettingsIntoDraft', () => {
  const draft = (overrides: Partial<DeviceVlanDraftRow> = {}): DeviceVlanDraftRow => ({
    vlan_id: 'v-10',
    ip_address: '1.1.1.1',
    prefix_length: '8',
    is_management: false,
    description: 'своё',
    ...overrides,
  })

  it('подменяет IP, префикс и «Управление» у существующей строки, не трогая описание и остальные строки', () => {
    const other = draft({ vlan_id: 'v-99', ip_address: '9.9.9.9' })
    const merged = mergeSharedSettingsIntoDraft([draft(), other], [row()], 'dev-1')
    expect(merged[0]).toEqual({ vlan_id: 'v-10', ip_address: '10.0.10.1', prefix_length: '24', is_management: true, description: 'своё' })
    expect(merged[1]).toEqual(other)
  })

  it('добавляет недостающую строку с описанием назначения этого устройства', () => {
    const merged = mergeSharedSettingsIntoDraft([], [row()], 'dev-1')
    expect(merged).toEqual([{ vlan_id: 'v-10', ip_address: '10.0.10.1', prefix_length: '24', is_management: true, description: 'кластер' }])
    expect(mergeSharedSettingsIntoDraft([], [row({ ip_address: null, prefix_length: null })], 'other-dev')[0]).toMatchObject({
      ip_address: '',
      prefix_length: '',
      description: '',
    })
  })

  it('не мутирует входной черновик', () => {
    const rows = [draft()]
    mergeSharedSettingsIntoDraft(rows, [row()], 'dev-1')
    expect(rows[0].ip_address).toBe('1.1.1.1')
  })
})
