// Диагностика «подинтерфейсы на недоступном VLAN» — GET /api/v1/integrity/stale-subinterfaces
// (backend/app/services/integrity.py: find_stale_subinterfaces, find_off_port_subinterfaces, find_stale_group_subinterfaces).
// Три случая: VLAN больше не разрешён устройству (сняли с устройства, убрали из его типа, перенесли в другой домен), VLAN разрешён
// устройству, но не выбран на порту (VLAN подинтерфейса — один из VLAN порта), и шаблон подинтерфейса ГРУППЫ портов на VLAN, которого
// у группы больше нет. Система такие записи не удаляет (на них IP-адреса и открытые порты), а показывает здесь и в форме устройства
// (предупреждение, перенос на другой VLAN).
import { api } from './client'

/** Почему VLAN подинтерфейса недоступен: `device` — больше не разрешён устройству, `port` — разрешён устройству, но не выбран на порту. */
export type StaleReason = 'device' | 'port'

/** Один подинтерфейс порта на недоступном VLAN. vlan_id — id записи справочника VLAN, vlan_number — номер VLAN (802.1Q). */
export interface StaleSubinterface {
  subinterface_id: string
  subinterface_name: string
  port_id: string
  port_name: string
  device_id: string
  device_name: string
  vlan_id: string
  vlan_number: number
  vlan_name: string
  reason: StaleReason
}

/** Шаблон подинтерфейса группы портов на VLAN, которого у группы больше нет (у шаблона нет имени и порта — только группа). */
export interface StaleGroupSubinterface {
  subinterface_id: string
  group_id: string
  group_name: string
  device_id: string
  device_name: string
  vlan_id: string
  vlan_number: number
  vlan_name: string
}

export interface StaleSubinterfacesReport {
  ok: boolean
  /** Число записей в обоих списках. */
  total: number
  subinterfaces: StaleSubinterface[]
  group_subinterfaces: StaleGroupSubinterface[]
}

export interface StaleSubinterfacesGroup {
  device_id: string
  device_name: string
  items: StaleSubinterface[]
  group_items: StaleGroupSubinterface[]
}

export function fetchStaleSubinterfaces(): Promise<StaleSubinterfacesReport> {
  return api.get<StaleSubinterfacesReport>('/integrity/stale-subinterfaces')
}

/** Раскладывает подинтерфейсы портов и шаблоны групп по устройствам: строки внутри устройства — в порядке сервера (порт →
 * подинтерфейс; группа → VLAN), устройства — по имени. Так экран показывает «что исправить в каком устройстве», а не россыпь строк. */
export function groupStaleByDevice(items: readonly StaleSubinterface[], groupItems: readonly StaleGroupSubinterface[] = []): StaleSubinterfacesGroup[] {
  const groups = new Map<string, StaleSubinterfacesGroup>()
  const groupOf = (deviceId: string, deviceName: string) => {
    const group = groups.get(deviceId) ?? { device_id: deviceId, device_name: deviceName, items: [], group_items: [] }
    groups.set(deviceId, group)
    return group
  }
  for (const item of items) groupOf(item.device_id, item.device_name).items.push(item)
  for (const item of groupItems) groupOf(item.device_id, item.device_name).group_items.push(item)
  return [...groups.values()].sort((a, b) => (a.device_name < b.device_name ? -1 : a.device_name > b.device_name ? 1 : 0))
}

/** Причина для строки диагностики: «снят с устройства» / «не выбран на порту». */
export function staleReasonText(reason: StaleReason): string {
  return reason === 'device' ? 'снят с устройства' : 'не выбран на порту'
}

/** «VLAN 30 — Резерв» для строки диагностики (имя необязательно). */
export function staleVlanText(item: Pick<StaleSubinterface, 'vlan_number' | 'vlan_name'>): string {
  return item.vlan_name ? `VLAN ${item.vlan_number} — ${item.vlan_name}` : `VLAN ${item.vlan_number}`
}
