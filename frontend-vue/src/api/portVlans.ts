// Список VLAN, разрешённых для чекбоксов "VLAN на порту" конкретного устройства.
//
// Переиспользуется DeviceFormModal.vue (динамически, вместе с ещё не сохранёнными правками
// блока "VLAN устройства" самой формы) и DevicePortsModal.vue (статически, по уже сохранённым в
// БД данным устройства — см. управление портами с экрана «Подключения»). Разрешённый набор
// совпадает с тем, что backend/app/services/crud.py:sync_interfaces фактически примет как
// allowed_vlans при PUT /devices/{id}/interfaces: DeviceTypeVLAN (каталог типа устройства) ∪
// PhysicalDeviceVLAN (уже назначенные устройству VLAN). Портировано из
// loadInterfaceEditor()/deviceVlanOptions/sortedVlanOptions() в
// frontend/static/device-interfaces.js.
import { listResource } from './client'
import type { DeviceTypeVLAN, DeviceVLAN, VLANDefinition } from './types'

/** VLAN id'ы (vlans.id), разрешённые для типа устройства через /resources/device-type-vlans.
 * Пустой deviceTypeId (устройство ещё создаётся, тип не выбран) -> пустой набор. */
export async function loadDeviceTypeVlanIds(deviceTypeId: string): Promise<Set<string>> {
  if (!deviceTypeId) return new Set()
  const res = await listResource<DeviceTypeVLAN>('device-type-vlans', { device_type_id: deviceTypeId, limit: 1000 })
  return new Set(res.items.map((x) => x.vlan_id))
}

/** VLAN id'ы, уже назначенные устройству в БД через /resources/device-vlans. Для формы
 * устройства, где "VLAN устройства" ещё редактируется как черновик, вместо этого источника
 * нужно брать текущий черновик (deviceVlans.value), а не перезапрашивать БД — см.
 * DeviceFormModal.vue:portVlanOptions. */
export async function loadAssignedDeviceVlanIds(deviceId: string): Promise<Set<string>> {
  const res = await listResource<DeviceVLAN>('device-vlans', { physical_device_id: deviceId, limit: 1000 })
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
