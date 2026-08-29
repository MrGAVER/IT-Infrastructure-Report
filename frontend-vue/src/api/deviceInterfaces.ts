// Общая логика загрузки/сохранения интерфейсов (портов) физического устройства.
//
// Раньше жила только внутри DeviceFormModal.vue. Вынесена в отдельный модуль, чтобы её же
// переиспользовал DevicePortsModal.vue — управление портами прямо с экрана «Подключения»
// (см. frontend-vue/README.md: было в «Ещё не сделано», теперь реализовано). Обе точки входа
// используют один и тот же атомарный эндпоинт PUT /devices/{id}/interfaces (см.
// backend/app/services/crud.py:sync_interfaces) — он одним запросом создаёт/обновляет/удаляет
// набор интерфейсов и их IP по diff'у с тем, что уже есть в БД, поэтому здесь нет отдельных
// create/update/delete-функций, только load+persist целиком.
import { api, listResource } from './client'
import type { DeviceInterface, InterfaceIP, InterfaceVLAN, InterfaceDraftRow } from './types'

/**
 * Грузит интерфейсы одного устройства вместе с их IP и VLAN-привязками и приводит к формату
 * InterfaceDraftRow, который понимает DeviceInterfacesEditor.vue.
 *
 * IP и VLAN грузятся целиком по всем устройствам одним широким запросом, а не по каждому
 * interface_id отдельно (интерфейсов на устройство обычно немного десятков, и один такой запрос
 * дешевле N дополнительных round-trip'ов) — тот же приём, что и в vanilla-версии
 * (loadInterfaceEditor() в frontend/static/device-interfaces.js).
 *
 * @example
 * const rows = await loadDeviceInterfaceDraftRows('dev-123')
 */
export async function loadDeviceInterfaceDraftRows(deviceId: string): Promise<InterfaceDraftRow[]> {
  const [ifaces, allIps, allVlans] = await Promise.all([
    listResource<DeviceInterface>('interfaces', { physical_device_id: deviceId, limit: 1000 }),
    listResource<InterfaceIP>('interface-ips', { limit: 1000 }),
    listResource<InterfaceVLAN>('interface-vlans', { limit: 1000 }),
  ])
  return ifaces.items.map(
    (x): InterfaceDraftRow => ({
      id: x.id,
      name: x.name,
      interface_type_id: x.interface_type_id ?? '',
      mac_address: x.mac_address ?? '',
      speed_id: x.speed_id ?? '',
      is_management: x.is_management,
      is_data_transfer: x.is_data_transfer,
      description: x.description ?? '',
      vlan_ids: allVlans.items.filter((v) => v.interface_id === x.id).map((v) => v.vlan_id),
      ips: allIps.items
        .filter((ip) => ip.interface_id === x.id)
        .map((ip) => ({
          id: ip.id,
          ip_address: ip.ip_address,
          prefix_length: ip.prefix_length == null ? '' : String(ip.prefix_length),
          purpose: ip.purpose ?? '',
        })),
    }),
  )
}

/** У каждого интерфейса должно быть имя — бэкенд это тоже проверит (422), но лучше показать
 * понятную ошибку до запроса, чем ждать round-trip. Возвращает текст ошибки либо null. */
export function validateInterfaceDraftRows(rows: InterfaceDraftRow[]): string | null {
  if (rows.some((row) => !row.name.trim())) return 'У каждого интерфейса должно быть имя.'
  return null
}

/**
 * Сохраняет набор интерфейсов устройства через атомарный PUT. vlan_ids каждого ряда отправляется
 * как пришло из loadDeviceInterfaceDraftRows (см. комментарий к InterfaceDraftRow в types.ts) —
 * если вызывающий компонент их не редактирует (как DevicePortsModal.vue), они просто
 * round-trip'ятся туда-обратно неизменными и НЕ стираются молча.
 *
 * @example
 * const { items } = await persistDeviceInterfaces('dev-123', rows)
 */
export async function persistDeviceInterfaces(deviceId: string, rows: InterfaceDraftRow[]): Promise<{ items: DeviceInterface[] }> {
  return api.put<{ items: DeviceInterface[] }>(`/devices/${deviceId}/interfaces`, {
    interfaces: rows.map((row) => ({
      id: row.id,
      name: row.name.trim(),
      interface_type_id: row.interface_type_id || null,
      mac_address: row.mac_address || null,
      speed_id: row.speed_id || null,
      is_management: row.is_management,
      is_data_transfer: row.is_data_transfer,
      description: row.description || null,
      vlan_ids: row.vlan_ids,
      ips: row.ips
        .filter((ip) => ip.ip_address.trim())
        .map((ip) => ({
          id: ip.id,
          ip_address: ip.ip_address.trim(),
          prefix_length: ip.prefix_length === '' ? null : Number(ip.prefix_length),
          purpose: ip.purpose || null,
        })),
    })),
  })
}
