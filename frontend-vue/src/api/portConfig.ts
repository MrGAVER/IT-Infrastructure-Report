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
  /** Актуальные записи одобренных подключений; при одобрении «всех найденных» пустой. */
  items: Connection[]
  /** Подключения, у которых одобрять было нечего (расхождение уже устранено или подключение неактивно). */
  skipped_ids: string[]
  /** Сколько расхождений одобрено именно этим запросом. */
  approved_count: number
}

export function approvePortConfig(connectionIds: string[]) {
  return api.post<ApprovePortConfigResult>('/connections/port-config/approve', { connection_ids: connectionIds })
}

/** Условия «одобрить все найденные» — те же поиск и фильтр активности, что у списка. Одобряются
 * ВСЕ подключения с расхождением под ними, а не только показанная страница. */
export interface ApproveMatch {
  q?: string | null
  is_active?: boolean | null
}

export function approveMatchingPortConfig(match: ApproveMatch) {
  return api.post<ApprovePortConfigResult>('/connections/port-config/approve', { match })
}

export function revokePortConfigApproval(connectionId: string) {
  return api.delete<Connection>(`/connections/${connectionId}/port-config/approval`)
}
