import { describe, it, expect } from 'vitest'
import { buildPortConflictNotice, computePortConflicts, snapshotPortConfigs } from '../portConflicts'
import type { Connection, DeviceInterface, InterfaceDraftRow, PortConflictInfo } from '../../api/types'

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

describe('computePortConflicts', () => {
  const iface = (id: string, overrides: Partial<DeviceInterface> = {}): DeviceInterface => ({
    id, name: id, physical_device_id: 'dev', interface_type_id: null, mac_address: null, speed_id: null,
    is_management: false, is_data_transfer: true, description: null, vlan_mode: 'trunk', ...overrides,
  })
  const connection = (id: string, source: string, destination: string, overrides: Partial<Connection> = {}): Connection => ({
    id, source_interface_id: source, destination_interface_id: destination, connection_type_id: 'ct',
    is_active: true, description: null, source_device_name: 'sw-src', source_interface_name: `${source}-name`,
    destination_device_name: 'sw-dst', destination_interface_name: `${destination}-name`, connection_type_name: 'UTP',
    source_port_role: 'data', destination_port_role: 'data', port_config_status: 'ok', ...overrides,
  })

  it('порт — источник подключения: сосед берётся с destination-стороны, различия помечаются независимыми флагами', () => {
    const rows = [row({ id: 'if-1', is_management: true, vlan_mode: 'trunk' })]
    const result = computePortConflicts(rows, [connection('c1', 'if-1', 'if-2')], [iface('if-2', { vlan_mode: 'access' })])
    expect(result['if-1']).toEqual({
      otherInterfaceId: 'if-2',
      otherDeviceName: 'sw-dst',
      otherInterfaceName: 'if-2-name',
      flagsDiffer: true,
      vlanModeDiffer: true,
      other: { is_management: false, is_data_transfer: true, vlan_mode: 'access' },
    })
  })

  it('порт — приёмник подключения: сосед и его имена берутся с source-стороны', () => {
    const rows = [row({ id: 'if-2', vlan_mode: 'trunk' })]
    const result = computePortConflicts(rows, [connection('c1', 'if-1', 'if-2')], [iface('if-1', { vlan_mode: 'access' })])
    expect(result['if-2']).toMatchObject({ otherInterfaceId: 'if-1', otherDeviceName: 'sw-src', otherInterfaceName: 'if-1-name', flagsDiffer: false, vlanModeDiffer: true })
  })

  it('неактивные подключения, совпадающие конфигурации, неизвестный сосед и строки без id — не конфликты', () => {
    const same = iface('if-2', { is_management: false, is_data_transfer: true, vlan_mode: 'trunk' })
    expect(computePortConflicts([row({ id: 'if-1' })], [connection('c1', 'if-1', 'if-2')], [same])).toEqual({})
    expect(computePortConflicts([row({ id: 'if-1' })], [connection('c1', 'if-1', 'if-2', { is_active: false })], [iface('if-2', { vlan_mode: 'access' })])).toEqual({})
    expect(computePortConflicts([row({ id: 'if-1' })], [connection('c1', 'if-1', 'if-2')], [])).toEqual({})
    expect(computePortConflicts([row({ id: undefined })], [connection('c1', 'if-1', 'if-2')], [iface('if-2', { vlan_mode: 'access' })])).toEqual({})
  })

  it('несколько активных подключений у порта — берётся первое в порядке списка', () => {
    const connections = [connection('c1', 'if-1', 'if-2'), connection('c2', 'if-1', 'if-3')]
    const result = computePortConflicts([row({ id: 'if-1' })], connections, [iface('if-2', { vlan_mode: 'access' }), iface('if-3', { vlan_mode: 'access' })])
    expect(result['if-1'].otherInterfaceId).toBe('if-2')
  })
})
