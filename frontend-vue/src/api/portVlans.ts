// Список VLAN, разрешённых для чекбоксов "VLAN на порту" конкретного устройства.
//
// Переиспользуется DeviceFormModal.vue (динамически, вместе с ещё не сохранёнными правками
// блока "VLAN устройства" самой формы) и DevicePortsModal.vue (статически, по уже сохранённым в
// БД данным устройства — см. управление портами с экрана «Подключения»). Разрешённый набор
// совпадает с тем, что backend/app/services/crud/interfaces.py:sync_interfaces фактически примет как
// allowed_vlans при PUT /devices/{id}/interfaces: DeviceTypeVLAN (каталог типа устройства) ∪
// PhysicalDeviceVLAN (уже назначенные устройству VLAN). Портировано из
// loadInterfaceEditor()/deviceVlanOptions/sortedVlanOptions() в
// прежнем vanilla-фронтенде (до 2.60.0).
import { api, listAllResource } from './client'
import type { Device, DeviceInterface, DeviceTypeVLAN, DeviceVLAN, InterfaceVlansEntry, VLANDefinition, VlanMode } from './types'

/** VLAN id'ы (vlans.id), разрешённые для типа устройства через /resources/device-type-vlans.
 * Пустой deviceTypeId (устройство ещё создаётся, тип не выбран) -> пустой набор. */
export async function loadDeviceTypeVlanIds(deviceTypeId: string): Promise<Set<string>> {
  if (!deviceTypeId) return new Set()
  const res = await listAllResource<DeviceTypeVLAN>('device-type-vlans', { device_type_id: deviceTypeId })
  return new Set(res.items.map((x) => x.vlan_id))
}

/** VLAN id'ы, уже назначенные устройству в БД через /resources/device-vlans. Для формы
 * устройства, где "VLAN устройства" ещё редактируется как черновик, вместо этого источника
 * нужно брать текущий черновик (deviceVlans.value), а не перезапрашивать БД — см.
 * DeviceFormModal.vue:portVlanOptions. */
export async function loadAssignedDeviceVlanIds(deviceId: string): Promise<Set<string>> {
  const res = await listAllResource<DeviceVLAN>('device-vlans', { physical_device_id: deviceId })
  return new Set(res.items.map((x) => x.vlan_id))
}

/**
 * Объединяет каталог типа устройства и уже назначенные VLAN в единый список опций для
 * чекбоксов "VLAN на порту", отсортированный по номеру VLAN — тот же порядок объединения и
 * сортировки, что deviceVlanOptions/sortedVlanOptions() в vanilla-версии.
 *
 * @example
 * const options = computePortVlanOptions(vlansStore.allDefinitions, typeVlanIds, assignedVlanIds)
 */
export function computePortVlanOptions(all: VLANDefinition[], typeVlanIds: Set<string>, assignedVlanIds: Set<string>): VLANDefinition[] {
  const byId = new Map(all.map((v) => [v.id, v]))
  const seen = new Set<string>()
  const result: VLANDefinition[] = []
  for (const id of [...typeVlanIds, ...assignedVlanIds]) {
    if (seen.has(id)) continue
    const v = byId.get(id)
    if (!v) continue
    seen.add(id)
    result.push(v)
  }
  return result.sort((a, b) => a.vlan_id - b.vlan_id)
}

/** Что нужно знать о порте ДРУГОГО устройства, чтобы сверить и записать его VLAN: режим, «Все VLAN», выбранные VLAN и
 * VLAN, допустимые устройству порта. */
export interface PortVlanContext {
  mode: VlanMode
  /** «Все VLAN» с учётом режима (в access всегда false). */
  allVlans: boolean
  /** id выбранных записей справочника VLAN; у порта с «Все VLAN» — все VLAN его устройства. */
  vlanIds: string[]
  /** VLAN, допустимые устройству порта (тип устройства ∪ назначенные устройству). */
  options: VLANDefinition[]
}

/**
 * Текущее состояние VLAN порта по его id — с сервера, а не из кэша каталога: окно «Все VLAN» сверяет порт соседа
 * сразу после смены его режима каскадом, и кэш мог отстать. Запросы: порт, устройство, VLAN порта (учитывает признак
 * «Все VLAN»), VLAN типа устройства и назначенные устройству.
 *
 * @param definitions справочник VLAN (stores/vlans.ts: allDefinitions) — по нему строятся допустимые устройству VLAN
 *
 * @example
 * const ctx = await loadPortVlanContext(peerInterfaceId, vlansStore.allDefinitions)
 */
export async function loadPortVlanContext(interfaceId: string, definitions: VLANDefinition[]): Promise<PortVlanContext> {
  const iface = await api.get<DeviceInterface>(`/resources/interfaces/${encodeURIComponent(interfaceId)}`)
  const [device, portVlans] = await Promise.all([
    api.get<Device>(`/resources/devices/${encodeURIComponent(iface.physical_device_id)}`),
    api.get<{ items: InterfaceVlansEntry[] }>(`/devices/${encodeURIComponent(iface.physical_device_id)}/interface-vlans`),
  ])
  const [typeVlanIds, assignedVlanIds] = await Promise.all([loadDeviceTypeVlanIds(device.device_type_id), loadAssignedDeviceVlanIds(iface.physical_device_id)])
  const entry = portVlans.items.find((item) => item.interface_id === interfaceId)
  const mode: VlanMode = iface.vlan_mode || 'trunk'
  return {
    mode,
    allVlans: mode === 'trunk' && entry?.all_vlans === true,
    vlanIds: [...new Set(entry?.vlan_ids ?? [])],
    options: computePortVlanOptions(definitions, typeVlanIds, assignedVlanIds),
  }
}
