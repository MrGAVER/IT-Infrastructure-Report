// Подключения и сверка конфигураций портов. Часть типов API, см. ./index.ts.

/** GET /resources/connections — идёт через общий {items,total,offset,limit}, но
 * enrich_connections() (см. backend/app/services/serialization.py) добавляет уже
 * резолвленные поля *_name — для таблицы их достаточно, без клиентских джойнов. */
export interface Connection {
  id: string
  source_interface_id: string
  destination_interface_id: string
  connection_type_id: string
  is_active: boolean
  description: string | null
  source_device_name: string
  source_interface_name: string
  destination_device_name: string
  destination_interface_name: string
  connection_type_name: string
  /** Конфигурацию портов (роль, режим, VLAN) и статус её сверки считает бэкенд
   * (services/port_config.py) — клиент их не пересчитывает, чтобы форма, дашборд и любой другой
   * потребитель видели одно и то же. Для «осиротевшего» подключения (порт удалён) — null / []. */
  source_port_role: PortRole | null
  destination_port_role: PortRole | null
  source_vlan_mode: VlanMode | null
  destination_vlan_mode: VlanMode | null
  /** Номера VLAN (802.1Q-теги) порта по возрастанию. */
  source_vlans: number[]
  destination_vlans: number[]
  /** Чем различаются порты; пусто, если конфигурации совпадают или подключение неактивно. */
  port_config_diff: PortConfigFacet[]
  port_config_status: PortConfigStatus
}

/** Итоги по ВСЕМ подключениям реестра (не зависят от поиска и фильтров) — GET /connections. */
export interface ConnectionsSummary {
  total: number
  active: number
  inactive: number
  mismatch: number
  approved: number
}

/** GET /connections — страница подключений: поиск, фильтры и статус сверки считает сервер.
 * total — под теми же условиями, что и items; summary — по всему реестру. */
export interface ConnectionsPage {
  items: Connection[]
  total: number
  offset: number
  limit: number
  summary: ConnectionsSummary
}

/** Роль порта: комбинация флагов DeviceInterface.is_management / is_data_transfer. */
export type PortRole = 'none' | 'management' | 'data' | 'management_data'

/** ok — роль, режим и набор VLAN портов совпадают (или подключение неактивно); mismatch —
 * различаются, решения ещё нет; approved — различаются, но пользователь одобрил именно это
 * расхождение. */
export type PortConfigStatus = 'ok' | 'mismatch' | 'approved'

/** Режим порта: access — один VLAN, trunk — набор VLAN. */
export type VlanMode = 'access' | 'trunk'

/** Грань конфигурации порта, по которой пара портов-соседей может различаться. */
export type PortConfigFacet = 'role' | 'mode' | 'vlans'

/** Один конец пары портов в предпросмотре сверки (GET /connections/port-config/preview). */
export interface PortConfigPreviewSide {
  interface_id: string
  role: PortRole
  mode: VlanMode
  /** Номера VLAN (802.1Q-теги) порта по возрастанию. */
  vlans: number[]
}

/** Статус сверки пары портов ДО сохранения подключения — те же правила, что у дашборда. status
 * для неактивного подключения всегда ok (diff пуст), для существующего учитывает его одобрение. */
export interface PortConfigPreview {
  status: PortConfigStatus
  diff: PortConfigFacet[]
  source: PortConfigPreviewSide
  destination: PortConfigPreviewSide
}
