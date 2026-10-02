// Роли портов (управление / передача данных), режим и VLAN — подписи и сравнение для подключений.
//
// Источник данных — сам порт (DeviceInterface.is_management / is_data_transfer / vlan_mode и
// связи с VLAN). Итоговый статус подключения (ok / mismatch / approved) и список различающихся
// граней считает БЭКЕНД и приходит в Connection (port_config_status, port_config_diff); здесь
// только подписи и то, что нужно клиенту ДО сохранения подключения: форма сравнивает роли двух ещё
// не сохранённых портов (правило то же, что в backend/app/services/port_config.py).
import type { DeviceInterface, PortConfigFacet, PortRole, VlanMode } from '../api/types'

export const PORT_ROLE_LABELS: Record<PortRole, string> = {
  none: 'не задано',
  management: 'Управление активами',
  data: 'Передача данных',
  management_data: 'Передача данных и управление активами',
}

type RoleFlags = Pick<DeviceInterface, 'is_management' | 'is_data_transfer'>

export function roleFromFlags(isManagement: boolean, isDataTransfer: boolean): PortRole {
  if (isManagement && isDataTransfer) return 'management_data'
  if (isManagement) return 'management'
  if (isDataTransfer) return 'data'
  return 'none'
}

export function portRoleOf(iface: Partial<RoleFlags>): PortRole {
  return roleFromFlags(Boolean(iface.is_management), Boolean(iface.is_data_transfer))
}

export function flagsFromRole(role: PortRole): RoleFlags {
  return {
    is_management: role === 'management' || role === 'management_data',
    is_data_transfer: role === 'data' || role === 'management_data',
  }
}

export function roleLabel(role: PortRole | null | undefined): string {
  return role ? PORT_ROLE_LABELS[role] : '—'
}

export function hasRoleMismatch(a: Partial<RoleFlags>, b: Partial<RoleFlags>): boolean {
  return portRoleOf(a) !== portRoleOf(b)
}

export const PORT_CONFIG_FACET_LABELS: Record<PortConfigFacet, string> = {
  role: 'роль',
  mode: 'режим',
  vlans: 'VLAN',
}

/** «роль, режим» — для бейджей и подсказок; пустая строка, если различий нет. */
export function facetsLabel(facets: readonly PortConfigFacet[]): string {
  return facets.map((f) => PORT_CONFIG_FACET_LABELS[f]).join(', ')
}

export function modeLabel(mode: VlanMode | null | undefined): string {
  return mode ?? '—'
}

/** Номера VLAN с диапазонами подряд идущих: [10, 11, 12, 20] → «10–12, 20». Транк может нести
 * сотни VLAN — перечисление по одному не помещается в ячейку таблицы. Пустой набор — «нет». */
export function formatVlans(vlans: readonly number[] | null | undefined): string {
  const sorted = [...new Set(vlans ?? [])].sort((a, b) => a - b)
  if (!sorted.length) return 'нет'
  const parts: string[] = []
  let start = sorted[0]
  let end = start
  const flush = () => parts.push(start === end ? String(start) : end - start === 1 ? `${start}, ${end}` : `${start}–${end}`)
  for (const n of sorted.slice(1)) {
    if (n === end + 1) {
      end = n
      continue
    }
    flush()
    start = end = n
  }
  flush()
  return parts.join(', ')
}

/** Режим и VLAN порта одной строкой: «trunk · VLAN 10–12, 20». */
export function modeAndVlansLabel(mode: VlanMode | null | undefined, vlans: readonly number[] | null | undefined): string {
  return `${modeLabel(mode)} · VLAN ${formatVlans(vlans)}`
}
