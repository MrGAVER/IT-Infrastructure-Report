// Проверка конфигураций портов-соседей подключений — см. backend/app/api/port_config.py.
import { api } from './client'
import type { Connection, DeviceInterface, PortConfigPreview, PortRole, VlanMode } from './types'
import { flagsFromRole } from '../utils/portConfig'

/** Точечно меняет роль порта, не трогая остальные его настройки (в отличие от PUT
 * /devices/{id}/interfaces, который синхронизирует устройство целиком). Ответ — порт в том же
 * виде, что и в каталоге 'interfaces', им заменяют запись в кэше (catalogs.replaceInterface). */
export function setPortRole(interfaceId: string, role: PortRole) {
  return api.put<DeviceInterface>(`/interfaces/${interfaceId}/port-role`, flagsFromRole(role))
}

/** Правка порта с дашборда: роль и/или ПОЛНЫЙ набор VLAN (id записей справочника) одной атомарной операцией.
 * `mode` — не смена режима (её делает каскад, api/vlanModeCascade.ts), а проверка: набор выбран для этого режима,
 * и если у порта режим уже другой, сервер ответит 409. Ответ — порт в виде каталога 'interfaces'. */
export interface PortConfigPatch {
  role?: PortRole
  vlan_ids?: string[]
  /** «Все VLAN»: true — порт несёт все VLAN устройства (набор не нужен, сервер его игнорирует); false вместе с
   * vlan_ids — снять признак и задать набор вручную. Только trunk. */
  all_vlans?: boolean
  mode?: VlanMode
}

export function setPortConfig(interfaceId: string, patch: PortConfigPatch) {
  return api.put<DeviceInterface>(`/interfaces/${interfaceId}/port-config`, patch)
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

export interface PreviewPortConfigParams {
  source_interface_id: string
  destination_interface_id: string
  /** Правка существующего подключения: сервер учтёт его одобрение. Без него — новое подключение. */
  connection_id?: string
  is_active: boolean
}

/** Статус сверки роли, режима и VLAN пары портов до сохранения — для предупреждения в форме. */
export function previewPortConfig(params: PreviewPortConfigParams) {
  const qs = new URLSearchParams({
    source_interface_id: params.source_interface_id,
    destination_interface_id: params.destination_interface_id,
    is_active: String(params.is_active),
  })
  if (params.connection_id) qs.set('connection_id', params.connection_id)
  return api.get<PortConfigPreview>(`/connections/port-config/preview?${qs.toString()}`)
}
