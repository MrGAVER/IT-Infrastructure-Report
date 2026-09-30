// Проверка конфигураций портов-соседей подключений — см. backend/app/api/port_config.py.
import { api } from './client'
import type { Connection, DeviceInterface, PortRole } from './types'
import { flagsFromRole } from '../utils/portConfig'

/** Точечно меняет роль порта, не трогая остальные его настройки (в отличие от PUT
 * /devices/{id}/interfaces, который синхронизирует устройство целиком). Ответ — порт в том же
 * виде, что и в каталоге 'interfaces', им заменяют запись в кэше (catalogs.replaceInterface). */
export function setPortRole(interfaceId: string, role: PortRole) {
  return api.put<DeviceInterface>(`/interfaces/${interfaceId}/port-role`, flagsFromRole(role))
}

export interface ApprovePortConfigResult {
  items: Connection[]
  /** Подключения, у которых одобрять было нечего (расхождение уже устранено или подключение неактивно). */
  skipped_ids: string[]
}

export function approvePortConfig(connectionIds: string[]) {
  return api.post<ApprovePortConfigResult>('/connections/port-config/approve', { connection_ids: connectionIds })
}

export function revokePortConfigApproval(connectionId: string) {
  return api.delete<Connection>(`/connections/${connectionId}/port-config/approval`)
}
