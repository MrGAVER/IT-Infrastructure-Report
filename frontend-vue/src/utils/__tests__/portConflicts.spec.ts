import { describe, it, expect } from 'vitest'
import { buildPortConflictNotice, computePortConflicts, snapshotPortConfigs } from '../portConflicts'
import type { DeviceInterfaceConnection } from '../../api/deviceConnectivity'
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
    allVlansDiffer: false,
    other: { is_management: false, is_data_transfer: true, vlan_mode: 'access', all_vlans: false },
    ...overrides,
  }
}

describe('snapshotPortConfigs', () => {
  it('запоминает конфигурацию только сохранённых портов (с id)', () => {
    const snapshot = snapshotPortConfigs([row(), row({ id: undefined, name: 'новый' })])
    expect([...snapshot.keys()]).toEqual(['if-1'])
    expect(snapshot.get('if-1')).toEqual({ is_management: false, is_data_transfer: true, vlan_mode: 'trunk', all_vlans: false })
  })

  it('«Все VLAN» входит в снимок только в trunk: у access-порта признака нет', () => {
    const snapshot = snapshotPortConfigs([row({ id: 'if-1', vlan_mode: 'trunk', all_vlans: true }), row({ id: 'if-2', vlan_mode: 'access', all_vlans: true })])
    expect(snapshot.get('if-1')).toMatchObject({ all_vlans: true })
    expect(snapshot.get('if-2')).toMatchObject({ all_vlans: false })
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
    const c = conflict({
      flagsDiffer: true,
      vlanModeDiffer: false,
      other: { is_management: false, is_data_transfer: true, vlan_mode: 'trunk', all_vlans: false },
    })
    const text = buildPortConflictNotice(rows, { 'if-1': c }, new Map())
    expect(text).toContain('«Управление»: да / у соседа нет')
    expect(text).toContain('«Передача данных»: нет / у соседа да')
  })

  it('расхождение «Все VLAN» попадает в текст уведомления; изменение одного только признака считается новой конфигурацией порта', () => {
    const before = snapshotPortConfigs([row({ vlan_mode: 'trunk', all_vlans: false })])
    const rows = [row({ vlan_mode: 'trunk', all_vlans: true })]
    const c = conflict({
      vlanModeDiffer: false,
      allVlansDiffer: true,
      other: { is_management: false, is_data_transfer: true, vlan_mode: 'trunk', all_vlans: false },
    })
    expect(buildPortConflictNotice(rows, { 'if-1': c }, before)).toContain('«Все VLAN»: да / у соседа нет')
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
  // Подключение порта устройства так, как его отдаёт сервер: сведения о соседе уже внутри записи.
  const neighbor = (interfaceId: string, peerId: string, overrides: Partial<DeviceInterfaceConnection> = {}): DeviceInterfaceConnection => ({
    interface_id: interfaceId,
    connection_id: `c-${interfaceId}`,
    connection_type_id: 'ct',
    description: null,
    peer_interface_id: peerId,
    peer_interface_name: `${peerId}-name`,
    peer_device_id: 'dev-peer',
    peer_device_name: 'sw-dst',
    peer_is_management: false,
    peer_is_data_transfer: true,
    peer_vlan_mode: 'trunk',
    peer_all_vlans: false,
    ...overrides,
  })

  it('различия с соседом помечаются независимыми флагами, имена соседа берутся из записи сервера', () => {
    const rows = [row({ id: 'if-1', is_management: true, vlan_mode: 'trunk' })]
    const result = computePortConflicts(rows, [neighbor('if-1', 'if-2', { peer_vlan_mode: 'access' })])
    expect(result['if-1']).toEqual({
      otherInterfaceId: 'if-2',
      otherDeviceName: 'sw-dst',
      otherInterfaceName: 'if-2-name',
      flagsDiffer: true,
      vlanModeDiffer: true,
      allVlansDiffer: false, // режимы разные — признак отдельно не сверяется
      other: { is_management: false, is_data_transfer: true, vlan_mode: 'access', all_vlans: false },
    })
  })

  it('«Все VLAN» у одного из двух trunk-портов — расхождение allVlansDiffer (в обе стороны); у обоих — нет', () => {
    const own = row({ id: 'if-1', vlan_mode: 'trunk', all_vlans: true })
    const peerWithout = computePortConflicts([own], [neighbor('if-1', 'if-2', { peer_all_vlans: false })])
    expect(peerWithout['if-1']).toMatchObject({ allVlansDiffer: true, flagsDiffer: false, vlanModeDiffer: false, other: { all_vlans: false } })
    const ownWithout = computePortConflicts([row({ id: 'if-1', vlan_mode: 'trunk', all_vlans: false })], [neighbor('if-1', 'if-2', { peer_all_vlans: true })])
    expect(ownWithout['if-1']).toMatchObject({ allVlansDiffer: true, other: { all_vlans: true } })
    expect(computePortConflicts([own], [neighbor('if-1', 'if-2', { peer_all_vlans: true })])).toEqual({})
  })

  it('отличается только режим порта или только флаги — поднимается ровно соответствующий флаг', () => {
    const modeOnly = computePortConflicts([row({ id: 'if-1' })], [neighbor('if-1', 'if-2', { peer_vlan_mode: 'access' })])
    expect(modeOnly['if-1']).toMatchObject({ flagsDiffer: false, vlanModeDiffer: true })
    const flagsOnly = computePortConflicts([row({ id: 'if-1' })], [neighbor('if-1', 'if-2', { peer_is_data_transfer: false })])
    expect(flagsOnly['if-1']).toMatchObject({ flagsDiffer: true, vlanModeDiffer: false })
  })

  it('совпадающая конфигурация, порт без подключения, пустой ответ и строки без id — не конфликты', () => {
    expect(computePortConflicts([row({ id: 'if-1' })], [neighbor('if-1', 'if-2')])).toEqual({})
    expect(computePortConflicts([row({ id: 'if-1' })], [neighbor('if-9', 'if-2', { peer_vlan_mode: 'access' })])).toEqual({})
    expect(computePortConflicts([row({ id: 'if-1' })], [])).toEqual({})
    expect(computePortConflicts([row({ id: undefined })], [neighbor('if-1', 'if-2', { peer_vlan_mode: 'access' })])).toEqual({})
  })

  it('несколько подключений у порта — берётся первое в порядке ответа сервера', () => {
    const connections = [neighbor('if-1', 'if-2', { peer_vlan_mode: 'access' }), neighbor('if-1', 'if-3', { peer_vlan_mode: 'access' })]
    expect(computePortConflicts([row({ id: 'if-1' })], connections)['if-1'].otherInterfaceId).toBe('if-2')
  })

  it('кабель между двумя портами одного устройства: расхождение видно с каждой стороны по своей записи', () => {
    const rows = [row({ id: 'if-1', vlan_mode: 'trunk' }), row({ id: 'if-2', name: 'Gi0/2', vlan_mode: 'access' })]
    const connections = [neighbor('if-1', 'if-2', { peer_vlan_mode: 'access' }), neighbor('if-2', 'if-1', { peer_vlan_mode: 'trunk' })]
    const result = computePortConflicts(rows, connections)
    expect(result['if-1']).toMatchObject({ otherInterfaceId: 'if-2', vlanModeDiffer: true })
    expect(result['if-2']).toMatchObject({ otherInterfaceId: 'if-1', vlanModeDiffer: true })
  })
})
