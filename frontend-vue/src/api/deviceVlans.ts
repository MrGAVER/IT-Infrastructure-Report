// Сохранение блока «VLAN устройства» (PhysicalDeviceVLAN) одним атомарным запросом
// PUT /devices/{id}/vlans (см. backend/app/services/crud/device_vlans.py:sync_device_vlans) — по образцу
// api/deviceInterfaces.ts:persistDeviceInterfaces. Раньше DeviceFormModal.vue сам удалял все записи
// устройства и создавал их заново отдельными запросами без транзакции: ошибка на середине оставляла
// устройство без части VLAN, а неизменённые записи каждый раз получали новые id.
import { api } from './client'
import type { DeviceVLAN, DeviceVlanDraftRow } from './types'

/** Строки черновика → payload. Строки без выбранного VLAN (пустая строка, которую пользователь ещё
 * не заполнил) в запрос не попадают, как и в прежней реализации. Пустые IP/описание → null,
 * префикс → число либо null. Бэкенд сопоставляет записи по vlan_id, поэтому id строки не передаётся.
 *
 * @example
 * const { items } = await persistDeviceVlans('dev-123', deviceVlans.value)
 */
export async function persistDeviceVlans(deviceId: string, rows: DeviceVlanDraftRow[]): Promise<{ items: DeviceVLAN[] }> {
  return api.put<{ items: DeviceVLAN[] }>(`/devices/${deviceId}/vlans`, {
    vlans: rows
      .filter((row) => row.vlan_id)
      .map((row) => ({
        vlan_id: row.vlan_id,
        ip_address: row.ip_address || null,
        prefix_length: row.prefix_length === '' ? null : Number(row.prefix_length),
        is_management: row.is_management,
        description: row.description || null,
      })),
  })
}
