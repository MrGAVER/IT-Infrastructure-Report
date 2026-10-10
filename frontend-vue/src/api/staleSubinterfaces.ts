// Диагностика «подинтерфейсы на VLAN, не разрешённом устройству» — GET /api/v1/integrity/stale-subinterfaces
// (backend/app/services/integrity.py:find_stale_subinterfaces). Такие подинтерфейсы возникают, когда VLAN сняли с устройства,
// убрали из его типа или перенесли в другой домен: система их не удаляет (на них IP-адреса и открытые порты), а показывает здесь
// и в форме устройства (предупреждение, перенос на другой VLAN).
import { api } from './client'

/** Один подинтерфейс на недоступном устройству VLAN. vlan_id — id записи справочника VLAN, vlan_number — номер VLAN (802.1Q). */
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
}

export interface StaleSubinterfacesReport {
  ok: boolean
  total: number
  subinterfaces: StaleSubinterface[]
}

export interface StaleSubinterfacesGroup {
  device_id: string
  device_name: string
  items: StaleSubinterface[]
}

export function fetchStaleSubinterfaces(): Promise<StaleSubinterfacesReport> {
  return api.get<StaleSubinterfacesReport>('/integrity/stale-subinterfaces')
}

/** Раскладывает подинтерфейсы по устройствам, сохраняя порядок сервера (устройство → порт → подинтерфейс): так экран показывает
 * «что исправить в каком устройстве», а не россыпь строк. */
export function groupStaleByDevice(items: readonly StaleSubinterface[]): StaleSubinterfacesGroup[] {
  const groups = new Map<string, StaleSubinterfacesGroup>()
  for (const item of items) {
    const group = groups.get(item.device_id) ?? { device_id: item.device_id, device_name: item.device_name, items: [] }
    group.items.push(item)
    groups.set(item.device_id, group)
  }
  return [...groups.values()]
}

/** «VLAN 30 — Резерв» для строки диагностики (имя необязательно). */
export function staleVlanText(item: Pick<StaleSubinterface, 'vlan_number' | 'vlan_name'>): string {
  return item.vlan_name ? `VLAN ${item.vlan_number} — ${item.vlan_name}` : `VLAN ${item.vlan_number}`
}
