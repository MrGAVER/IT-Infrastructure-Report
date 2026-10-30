import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Device, InterfaceDraftRow, InterfaceGroupDraft } from '../types'
import type { DeviceInterfaceConnection } from '../deviceConnectivity'
import { makeRow } from '../../utils/__tests__/interfaceRowFixture'

const listAllResource = vi.fn()
const loadDeviceInterfaceDraftRows = vi.fn()
const loadDeviceInterfaceGroups = vi.fn()
const fetchDeviceInterfaceConnections = vi.fn()
const loadDeviceTypeVlanIds = vi.fn()

vi.mock('../client', () => ({ listAllResource: (...args: unknown[]) => listAllResource(...args) }))
vi.mock('../deviceInterfaces', () => ({
  loadDeviceInterfaceDraftRows: (...args: unknown[]) => loadDeviceInterfaceDraftRows(...args),
  loadDeviceInterfaceGroups: (...args: unknown[]) => loadDeviceInterfaceGroups(...args),
}))
vi.mock('../deviceConnectivity', () => ({ fetchDeviceInterfaceConnections: (...args: unknown[]) => fetchDeviceInterfaceConnections(...args) }))
vi.mock('../portVlans', () => ({ loadDeviceTypeVlanIds: (...args: unknown[]) => loadDeviceTypeVlanIds(...args) }))

const { loadDeviceNestedData } = await import('../deviceFormData')

const device = { id: 'dev-1', device_type_id: 't-sw' } as Device

const connection: DeviceInterfaceConnection = {
  interface_id: 'if-1',
  connection_id: 'c-1',
  connection_type_id: 'ct-1',
  description: null,
  peer_interface_id: 'p-1',
  peer_interface_name: 'Gi0/9',
  peer_device_id: 'dev-2',
  peer_device_name: 'sw-02',
  peer_is_management: false,
  peer_is_data_transfer: false,
  peer_vlan_mode: 'access',
  peer_all_vlans: false,
}

const group: InterfaceGroupDraft = {
  id: 'g-1',
  key: 'gk-1',
  name: 'Uplinks',
  vlan_mode: 'trunk',
  vlan_ids: ['v10'],
  all_vlans: false,
  ips: [],
  open_ports: [],
  subinterfaces: [],
} as unknown as InterfaceGroupDraft

function portRow(): InterfaceDraftRow {
  return makeRow({ id: 'if-1', name: 'Gi0/1', group_key: 'gk-1', ips: [{ id: 'ip-1', ip_address: '10.0.0.1', prefix_length: '24', purpose: '' }] })
}

beforeEach(() => {
  vi.clearAllMocks()
  listAllResource.mockImplementation(async (resource: string) => {
    if (resource === 'deployed-software') return { items: [{ id: 'ds-1', software_asset_id: 'sa-1', version: null }] }
    if (resource === 'device-vlans')
      return { items: [{ id: 'dv-1', vlan_id: 'v10', ip_address: '10.9.0.1', prefix_length: 24, is_management: true, description: null }] }
    if (resource === 'vlan-domain-devices')
      return {
        items: [
          { id: 'l-1', domain_id: 'dom-1' },
          { id: 'l-2', domain_id: 'dom-2' },
        ],
      }
    throw new Error(`неожиданный ресурс ${resource}`)
  })
  loadDeviceInterfaceDraftRows.mockResolvedValue([portRow()])
  loadDeviceInterfaceGroups.mockResolvedValue([group])
  loadDeviceTypeVlanIds.mockResolvedValue(new Set(['v10', 'v20']))
  fetchDeviceInterfaceConnections.mockResolvedValue([connection])
})

describe('loadDeviceNestedData: редактирование', () => {
  it('запрашивает вложенные данные именно этого устройства и ждёт справочник VLAN', async () => {
    const ensureVlansLoaded = vi.fn(async () => undefined)
    await loadDeviceNestedData(device, false, ensureVlansLoaded)

    expect(listAllResource).toHaveBeenCalledWith('deployed-software', { owner_type: 'physical_device', owner_id: 'dev-1' })
    expect(listAllResource).toHaveBeenCalledWith('device-vlans', { physical_device_id: 'dev-1' })
    expect(listAllResource).toHaveBeenCalledWith('vlan-domain-devices', { physical_device_id: 'dev-1' })
    expect(loadDeviceInterfaceDraftRows).toHaveBeenCalledWith('dev-1')
    expect(loadDeviceInterfaceGroups).toHaveBeenCalledWith('dev-1')
    expect(loadDeviceTypeVlanIds).toHaveBeenCalledWith('t-sw')
    expect(fetchDeviceInterfaceConnections).toHaveBeenCalledWith('dev-1')
    expect(ensureVlansLoaded).toHaveBeenCalledTimes(1)
  })

  it('id сохраняются, порты получают черновики подключений, подключения возвращаются как есть', async () => {
    const data = await loadDeviceNestedData(device, false, async () => undefined)

    expect(data.softwareAssets).toEqual([{ id: 'ds-1', software_asset_id: 'sa-1', version: '' }])
    expect(data.vlanRows).toEqual([{ id: 'dv-1', vlan_id: 'v10', ip_address: '10.9.0.1', prefix_length: '24', is_management: true, description: '' }])
    expect(data.interfaces[0].id).toBe('if-1')
    expect(data.interfaces[0].ips[0].id).toBe('ip-1')
    expect(data.interfaces[0].connection).toMatchObject({ peer_device_id: 'dev-2', peer_interface_id: 'p-1', connection_type_id: 'ct-1', description: '' })
    expect(data.interfaceGroups).toEqual([group])
    expect(data.interfaces[0].group_key).toBe('gk-1')
    expect(data.domainIds).toEqual(['dom-1', 'dom-2'])
    expect([...data.typeVlanIds]).toEqual(['v10', 'v20'])
    expect(data.connections).toEqual([connection])
  })

  it('ошибка любого запроса не глотается', async () => {
    loadDeviceInterfaceGroups.mockRejectedValue(new Error('группы недоступны'))
    await expect(loadDeviceNestedData(device, false, async () => undefined)).rejects.toThrow('группы недоступны')
  })

  it('ошибка загрузки справочника VLAN тоже доходит до вызывающего', async () => {
    await expect(
      loadDeviceNestedData(device, false, async () => {
        throw new Error('VLAN недоступны')
      }),
    ).rejects.toThrow('VLAN недоступны')
  })
})

describe('loadDeviceNestedData: копирование', () => {
  it('подключения донора не запрашиваются и не наследуются', async () => {
    const data = await loadDeviceNestedData(device, true, async () => undefined)

    expect(fetchDeviceInterfaceConnections).not.toHaveBeenCalled()
    expect(data.connections).toEqual([])
    expect(data.interfaces[0].connection).toBeNull()
  })

  it('у ПО, VLAN, портов и их IP нет id; id группы тоже стёрт', async () => {
    const data = await loadDeviceNestedData(device, true, async () => undefined)

    expect(data.softwareAssets[0].id).toBeUndefined()
    expect(data.vlanRows[0].id).toBeUndefined()
    expect(data.interfaces[0].id).toBeUndefined()
    expect(data.interfaces[0].ips[0].id).toBeUndefined()
    expect(data.interfaceGroups[0].id).toBeUndefined()
  })

  it('группы пересоздаются под новыми ключами, а порты перевязываются на них', async () => {
    const data = await loadDeviceNestedData(device, true, async () => undefined)

    expect(data.interfaceGroups).toHaveLength(1)
    expect(data.interfaceGroups[0].key).not.toBe('gk-1')
    expect(data.interfaces[0].group_key).toBe(data.interfaceGroups[0].key)
    // исходная группа донора не изменена
    expect(group.id).toBe('g-1')
    expect(group.key).toBe('gk-1')
  })

  it('домены и допустимые VLAN типа переносятся от донора', async () => {
    const data = await loadDeviceNestedData(device, true, async () => undefined)
    expect(data.domainIds).toEqual(['dom-1', 'dom-2'])
    expect([...data.typeVlanIds]).toEqual(['v10', 'v20'])
  })
})
