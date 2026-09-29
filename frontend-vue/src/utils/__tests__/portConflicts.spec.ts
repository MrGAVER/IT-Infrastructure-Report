import { describe, it, expect } from 'vitest'
import { buildPortConflictNotice, snapshotPortConfigs } from '../portConflicts'
import type { InterfaceDraftRow, PortConflictInfo } from '../../api/types'

function row(overrides: Partial<InterfaceDraftRow> = {}): InterfaceDraftRow {
  return {
    id: 'if-1',
    name: 'Gi0/1',
    interface_type_id: '',
    mac_address: '',
    speed_id: '',
    is_management: false,
    is_data_transfer: true,
    description: '',
    vlan_ids: [],
    vlan_mode: 'trunk',
    ips: [],
    open_ports: [],
    ...overrides,
  }
}

function conflict(overrides: Partial<PortConflictInfo> = {}): PortConflictInfo {
  return {
    otherInterfaceId: 'if-other',
    otherDeviceName: 'sw-02',
    otherInterfaceName: 'Gi0/24',
    flagsDiffer: false,
    vlanModeDiffer: true,
    other: { is_management: false, is_data_transfer: true, vlan_mode: 'access' },
    ...overrides,
  }
}

describe('snapshotPortConfigs', () => {
  it('запоминает конфигурацию только сохранённых портов (с id)', () => {
    const snapshot = snapshotPortConfigs([row(), row({ id: undefined, name: 'новый' })])
    expect([...snapshot.keys()]).toEqual(['if-1'])
    expect(snapshot.get('if-1')).toEqual({ is_management: false, is_data_transfer: true, vlan_mode: 'trunk' })
  })
})

describe('buildPortConflictNotice', () => {
  it('порт с новой конфигурацией и расхождением с соседом — текст с обоими портами и отличием', () => {
    const rows = [row({ vlan_mode: 'trunk' })]
    const initial = snapshotPortConfigs([row({ vlan_mode: 'access' })]) // раньше был access
    const text = buildPortConflictNotice(rows, { 'if-1': conflict() }, initial)
    expect(text).toContain('Gi0/1')
    expect(text).toContain('Gi0/24 (sw-02)')
    expect(text).toContain('режим порта: trunk / у соседа access')
  })

  it('перечисляет отличающиеся флаги «Управление»/«Передача данных»', () => {
    const rows = [row({ is_management: true, is_data_transfer: false })]
    const c = conflict({ flagsDiffer: true, vlanModeDiffer: false, other: { is_management: false, is_data_transfer: true, vlan_mode: 'trunk' } })
    const text = buildPortConflictNotice(rows, { 'if-1': c }, new Map())
    expect(text).toContain('«Управление»: да / у соседа нет')
    expect(text).toContain('«Передача данных»: нет / у соседа да')
  })

  it('конфигурация порта не менялась с момента открытия формы — не уведомляем повторно', () => {
    const rows = [row()]
    expect(buildPortConflictNotice(rows, { 'if-1': conflict() }, snapshotPortConfigs(rows))).toBeNull()
  })

  it('нет расхождения с соседом или строка без id — уведомлять не о чем', () => {
    expect(buildPortConflictNotice([row()], {}, new Map())).toBeNull()
    expect(buildPortConflictNotice([row({ id: undefined })], { 'if-1': conflict() }, new Map())).toBeNull()
  })

  it('больше трёх портов — остальные сворачиваются в «и ещё N»', () => {
    const rows = [1, 2, 3, 4, 5].map((n) => row({ id: `if-${n}`, name: `Gi0/${n}` }))
    const conflicts = Object.fromEntries(rows.map((r) => [r.id!, conflict()]))
    const text = buildPortConflictNotice(rows, conflicts, new Map())!
    expect(text).toContain('Gi0/3')
    expect(text).not.toContain('Gi0/4')
    expect(text).toContain('и ещё 2')
  })
})
