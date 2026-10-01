// Роли портов (управление / передача данных) и их сравнение для подключений.
//
// Источник данных — флаги самого порта (DeviceInterface.is_management / is_data_transfer). Итоговый
// статус подключения (ok / mismatch / approved) считает БЭКЕНД и приходит в Connection
// (port_config_status); здесь только то, что нужно клиенту ДО сохранения подключения — форма
// сравнивает два ещё не сохранённых порта. Правило то же, что в backend/app/services/port_config.py:
// любое различие пары флагов — расхождение.
import type { DeviceInterface, PortRole } from '../api/types'

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
