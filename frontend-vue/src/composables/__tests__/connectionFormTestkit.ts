// Общие помощники спеков форм подключения (useConnection*.ts): фикстуры портов, подключений и ответов сверки, сторы с заданным состоянием.
import { createPinia, setActivePinia } from 'pinia'
import type { Connection, Device, DeviceInterface, PortConfigFacet, PortConfigPreview, PortConfigPreviewSide, PortConfigStatus } from '../../api/types'
import { useCatalogsStore } from '../../stores/catalogs'
import { useConnectionsStore } from '../../stores/connections'
import { useDevicesStore } from '../../stores/devices'

export function iface(id: string, deviceId: string, patch: Partial<DeviceInterface> = {}): DeviceInterface {
  return {
    id,
    name: id,
    physical_device_id: deviceId,
    interface_type_id: null,
    mac_address: null,
    speed_id: null,
    is_management: false,
    is_data_transfer: false,
    description: null,
    vlan_mode: 'access',
    ...patch,
  } as DeviceInterface
}

export function device(id: string, systemName: string | null, serial = `SN-${id}`): Device {
  return { id, system_name: systemName, serial_number: serial } as unknown as Device
}

export function connection(patch: Partial<Connection> = {}): Connection {
  return {
    id: 'c-1',
    source_interface_id: 'if-a',
    destination_interface_id: 'if-b',
    connection_type_id: 'ct-1',
    is_active: true,
    description: null,
    ...patch,
  } as Connection
}

export function previewSide(interfaceId: string, patch: Partial<PortConfigPreviewSide> = {}): PortConfigPreviewSide {
  return { interface_id: interfaceId, role: 'data', mode: 'access', vlans: [], ...patch }
}

export function preview(
  source: PortConfigPreviewSide,
  destination: PortConfigPreviewSide,
  status: PortConfigStatus = 'ok',
  diff: PortConfigFacet[] = [],
): PortConfigPreview {
  return { status, diff, source, destination }
}

/** Свежая Pinia с заданными устройствами, портами каталога и подключениями (занятость портов считает стор подключений). */
export function setupConnectionStores(state: { devices?: Device[]; interfaces?: DeviceInterface[]; connections?: Connection[] } = {}) {
  setActivePinia(createPinia())
  const catalogs = useCatalogsStore()
  const devices = useDevicesStore()
  const connections = useConnectionsStore()
  catalogs.items['interfaces'] = (state.interfaces ?? []) as never
  devices.all = state.devices ?? []
  connections.all = state.connections ?? []
  return { catalogs, devices, connections }
}
