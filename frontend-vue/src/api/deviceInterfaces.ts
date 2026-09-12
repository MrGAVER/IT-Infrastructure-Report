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
import type { DeviceInterface, InterfaceIP, InterfaceVLAN, InterfaceDraftRow, OpenPort } from './types'

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
  const [ifaces, allIps, allVlans, allOpenPorts] = await Promise.all([
    listResource<DeviceInterface>('interfaces', { physical_device_id: deviceId, limit: 1000 }),
    listResource<InterfaceIP>('interface-ips', { limit: 1000 }),
    listResource<InterfaceVLAN>('interface-vlans', { limit: 1000 }),
    // Фикс п.1.4 (батч4): открытые порты — теперь свойство интерфейса (owner_type=
    // 'device_interface', owner_id=id интерфейса), не всего устройства, см. комментарий к
    // InterfaceDraftRow.open_ports в types.ts и backend/app/services/crud.py:
    // _sync_interface_open_ports. Грузятся широким запросом по owner_type, а не по каждому
    // interface_id отдельно — тот же приём, что и allIps/allVlans выше.
    listResource<OpenPort>('open-ports', { owner_type: 'device_interface', limit: 1000 }),
  ])
  return ifaces.items.map((x): InterfaceDraftRow => {
    const links = allVlans.items.filter((v) => v.interface_id === x.id)
    return {
      id: x.id,
      name: x.name,
      interface_type_id: x.interface_type_id ?? '',
      mac_address: x.mac_address ?? '',
      speed_id: x.speed_id ?? '',
      is_management: x.is_management,
      is_data_transfer: x.is_data_transfer,
      description: x.description ?? '',
      vlan_ids: links.map((v) => v.vlan_id),
      // Фикс п.1.3.9: раньше режим порта выводился из InterfaceVLAN.mode ("trunk", если связей
      // нет или их mode не везде 'access') — при 0 VLAN на порту связей не было вовсе, и
      // access-режим без выбранного VLAN откатывался в trunk после каждого сохранения+
      // перезагрузки формы. Теперь режим читается напрямую с самого интерфейса
      // (DeviceInterface.vlan_mode, backend/app/models.py) — источник истины, не вывод.
      vlan_mode: x.vlan_mode,
      ips: allIps.items
        .filter((ip) => ip.interface_id === x.id)
        .map((ip) => ({
          id: ip.id,
          ip_address: ip.ip_address,
          prefix_length: ip.prefix_length == null ? '' : String(ip.prefix_length),
          purpose: ip.purpose ?? '',
        })),
      open_ports: allOpenPorts.items
        .filter((p) => p.owner_id === x.id)
        .sort((a, b) => a.port - b.port)
        .map((p) => ({
          id: p.id,
          protocol_catalog_id: p.protocol_catalog_id ?? '',
          port: String(p.port),
          protocol: p.protocol ?? '',
          transport_protocol: p.transport_protocol,
          description: p.description ?? '',
        })),
    }
  })
}

import { isValidIPv4, isValidPrefixLength } from '../utils/ipValidation'

/** У каждого интерфейса должно быть имя — бэкенд это тоже проверит (422), но лучше показать
 * понятную ошибку до запроса, чем ждать round-trip. UI (DeviceInterfacesEditor.vue) не даёт
 * набрать больше одного VLAN в режиме access, но проверка здесь — защита на случай данных,
 * загруженных из БД в уже несогласованном виде (см. комментарий к InterfaceDraftRow.vlan_mode).
 * Возвращает текст ошибки либо null.
 *
 * Фикс п.2.1.3: IP-адреса/префиксы интерфейса (InterfaceDraftRow.ips) — та же причина, что и у
 * остальных проверок здесь: показать понятную ошибку сразу, а не ждать 422 с бэкенда. */
export function validateInterfaceDraftRows(rows: InterfaceDraftRow[]): string | null {
  if (rows.some((row) => !row.name.trim())) return 'У каждого интерфейса должно быть имя.'
  if (rows.some((row) => row.vlan_mode === 'access' && row.vlan_ids.length > 1)) {
    return 'В режиме access у порта может быть не более одного VLAN.'
  }
  for (const row of rows) {
    for (const ip of row.ips) {
      if (!isValidIPv4(ip.ip_address)) return `Некорректный IP-адрес «${ip.ip_address}» на порту «${row.name}».`
      if (!isValidPrefixLength(ip.prefix_length)) return `Некорректный префикс «${ip.prefix_length}» на порту «${row.name}» — допустимо 0-32.`
    }
    // Фикс п.1.4 (батч4): открытые порты переехали на уровень интерфейса — та же проверка, что
    // раньше защищала список на уровне устройства (DeviceFormModal.vue:persistOpenPorts просто
    // молча пропускал пустые/нечисловые номера порта; здесь — явная ошибка до отправки запроса,
    // а не тихая потеря введённых данных).
    for (const port of row.open_ports) {
      if (!port.port.trim()) continue
      if (!Number.isInteger(Number(port.port)) || Number(port.port) < 0) {
        return `Некорректный номер открытого порта «${port.port}» на порту «${row.name}».`
      }
    }
  }
  return null
}

/**
 * Сохраняет набор интерфейсов устройства через атомарный PUT. vlan_ids каждого ряда отправляется
 * как пришло из loadDeviceInterfaceDraftRows (см. комментарий к InterfaceDraftRow в types.ts) —
 * если вызывающий компонент их не редактирует (как DevicePortsModal.vue), они просто
 * round-trip'ятся туда-обратно неизменными и НЕ стираются молча. vlan_mode round-trip'ится по
 * тому же принципу (п.1.4.3.2).
 *
 * Чистый API-вызов: НЕ обновляет catalogs.items['interfaces'] сама — этот модуль намеренно не
 * знает про Pinia-сторы (см. комментарий в шапке файла). Вызывающая сторона обязана сама
 * прогнать результат через catalogs.replaceDeviceInterfaces(deviceId, items) — иначе другие
 * компоненты, читающие этот кэш (напр. поле "Порт" в ConnectionFormModal.vue), продолжат
 * видеть старые данные до перезагрузки страницы. Забыли сделать это в DeviceFormModal.vue —
 * фикс п.3.1; DevicePortsModal.vue делал это с самого начала, см. её submit().
 *
 * @example
 * const { items } = await persistDeviceInterfaces('dev-123', rows)
 * catalogs.replaceDeviceInterfaces('dev-123', items)
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
      vlan_mode: row.vlan_mode,
      ips: row.ips
        .filter((ip) => ip.ip_address.trim())
        .map((ip) => ({
          id: ip.id,
          ip_address: ip.ip_address.trim(),
          prefix_length: ip.prefix_length === '' ? null : Number(ip.prefix_length),
          purpose: ip.purpose || null,
        })),
      // Фикс п.1.4 (батч4): открытые порты round-trip'ятся вместе со своим интерфейсом в том же
      // атомарном PUT — см. backend/app/services/crud.py:_sync_interface_open_ports. Пустой
      // port (после trim) пропускается так же, как раньше в DeviceFormModal.vue:persistOpenPorts
      // (колонка NOT NULL на бэкенде).
      open_ports: row.open_ports
        .filter((p) => p.port.trim())
        .map((p) => ({
          id: p.id,
          protocol_catalog_id: p.protocol_catalog_id || null,
          port: Number(p.port),
          protocol: p.protocol || null,
          transport_protocol: p.transport_protocol || 'TCP',
          description: p.description || null,
        })),
    })),
  })
}
