// Типы отражают реальные поля моделей бэкенда (backend/app/models.py) и то, что
// действительно возвращают эндпоинты (backend/app/services/serialization.py) —
// см. serialize(): отдаёт сырые колонки как есть, без резолва FK в имена.
// Резолв имён — задача фронтенда (см. stores/catalogs.ts), как и в текущем
// vanilla-фронтенде (frontend/static/core.js: lookupLabel/resourceMap).

/** Справочная запись общего вида — id + name достаточно для большинства каталогов. */
export interface CatalogItem {
  id: string
  name: string
  [key: string]: unknown
}

/** StructuralUnit и Department используют самоссылающуюся иерархию parent_id (см. память проекта). */
export interface StructuralUnit extends CatalogItem {
  parent_id: string | null
  description?: string | null
}

export interface Building extends CatalogItem {
  address?: string | null
  structural_unit_id?: string | null
}

export interface Room extends CatalogItem {
  building_id: string
}

export interface Rack extends CatalogItem {
  room_id: string
  height_u?: number | null
}

export interface DeviceModel extends CatalogItem {
  manufacturer_id: string
  device_type_id: string
  model: string
}

export interface DeviceInterface extends CatalogItem {
  physical_device_id: string
  interface_type_id: string | null
  mac_address: string | null
  speed_id: string | null
  is_management: boolean
  is_data_transfer: boolean
  description: string | null
}

/** GET /resources/connections — идёт через общий {items,total,offset,limit}, но
 * enrich_connections() (см. backend/app/services/serialization.py) добавляет уже
 * резолвленные поля *_name — для таблицы их достаточно, без клиентских джойнов. */
export interface Connection {
  id: string
  source_interface_id: string
  destination_interface_id: string
  connection_type_id: string
  purpose: string | null
  is_active: boolean
  description: string | null
  source_device_name: string
  source_interface_name: string
  destination_device_name: string
  destination_interface_name: string
  connection_type_name: string
}

export interface DeviceType extends CatalogItem {}
export interface Manufacturer extends CatalogItem {}
export interface OperatingSystem extends CatalogItem {
  version?: string | null
}
export interface EmbeddedOperatingSystem extends CatalogItem {
  version?: string | null
}

/** GET /api/v1/devices — сырые поля PhysicalDevice + обогащение из enrich_devices(). */
export interface Device {
  id: string
  device_type_id: string
  manufacturer_id: string | null
  model_id: string | null
  serial_number: string
  system_name: string | null
  operating_system_id: string | null
  embedded_os_id: string | null
  siem_enabled: boolean
  building_id: string | null
  room_id: string | null
  rack_id: string | null
  rack_position: string | null
  status: string | null
  description: string | null
  created_at?: string
  updated_at?: string
  // enrich_devices()
  management_interface: string
  management_ips: string
  interface_count: number
  embedded_os_name: string
  embedded_os_version: string
  vlan_summary: string
}

export interface DevicesResponse {
  items: Device[]
  total: number
}

export interface DashboardCounts {
  information_systems: number
  physical_devices: number
  virtual_machines: number
  containers: number
  connections: number
  vlan: number
  software: number
}

/** GET /api/v1/vms — {items,total}, как /devices (не {items,total,offset,limit} и не
 * плоский массив как /information-systems) — третий вариант формы ответа в этом API. */
export interface VirtualMachine {
  id: string
  name: string
  operating_system_id: string | null
  physical_device_id: string | null
  hypervisor_os_id: string | null
  purpose: string | null
  status: string
  description: string | null
  created_at?: string
  updated_at?: string
}

export interface VMsResponse {
  items: VirtualMachine[]
  total: number
}

/** GET /api/v1/resources/vm-ips?virtual_machine_id=... — генерический ресурс, {items,total,offset,limit}
 * (см. PagedResponse в api/client.ts). Лист 4 требует "IP-адрес виртуальной машины/контейнера" —
 * у одной ВМ их может быть несколько, поэтому отдельная таблица, а не колонка на VirtualMachine. */
export interface VMIP {
  id: string
  virtual_machine_id: string
  ip_address: string
  prefix_length: number | null
  purpose: string | null
  is_management: boolean
}

/** GET /api/v1/resources/open-ports?owner_type=...&owner_id=... — полиморфная таблица (owner_type
 * сейчас 'virtual_machine' или 'physical_device', см. backend/app/models.py:OpenPort), поэтому один
 * и тот же тип и один и тот же компонент-редактор (OpenPortListEditor.vue) годятся для обоих
 * владельцев — отличается только owner_type/owner_id, которые подставляет вызывающий код. */
export interface OpenPort {
  id: string
  owner_type: string
  owner_id: string
  transport_protocol: string
  port: number
  protocol: string | null
  protocol_catalog_id: string | null
  ip_address: string | null
  description: string | null
}

/** GET /api/v1/resources/protocol-port-catalog — справочник "порт + протокол" для быстрого выбора
 * в OpenPortListEditor.vue. Не входит в общий CatalogItem/CATALOGS в stores/catalogs.ts, т.к. у
 * записи нет поля name (см. backend/app/models.py:ProtocolPortCatalog) — это сломало бы
 * catalogs.label(), который читает item.name. */
export interface ProtocolPortCatalogEntry {
  id: string
  port: number
  protocol_type: string
  description: string | null
}

/** Черновая строка редактора IP-адресов ВМ (VmIpListEditor.vue). Поля — строки для прямого
 * v-model на input'ах (в т.ч. числовое prefix_length: пустая строка — валидное "не задано",
 * что не выразить через number). Конвертируется в payload VMIP при сохранении, см.
 * VMFormModal.vue:persistVmIps. `id` присутствует только у строк, загруженных с бэкенда. */
export interface VmIpDraftRow {
  id?: string
  ip_address: string
  prefix_length: string
  purpose: string
  is_management: boolean
}

/** Черновая строка редактора открытых портов (OpenPortListEditor.vue) — переиспользуется и для
 * ВМ (сейчас), и для физических устройств (см. "Ещё не сделано" в frontend-vue/README.md), т.к.
 * OpenPort — полиморфная таблица с одинаковым набором полей независимо от owner_type. */
export interface OpenPortDraftRow {
  id?: string
  protocol_catalog_id: string
  port: string
  protocol: string
  transport_protocol: string
  description: string
}

/** GET /api/v1/vlan-dashboard — сгруппировано по vlan_id, т.к. один и тот же VLAN ID
 * может иметь разные определения в разных доменах (см. backend/app/api/system.py:
 * vlan_dashboard). Формат ответа специфичный, четвёртый вариант в этом API. */
export interface VLANDeviceAssignment {
  device_id: string
  device_name: string
  ip_address: string | null
  is_management: boolean
}
export interface VLANDefinition {
  id: string
  vlan_id: number
  name: string
  description: string
  domain_id: string | null
  domain_name: string
  devices: VLANDeviceAssignment[]
}
export interface VLANDashboardGroup {
  vlan_id: number
  definitions: VLANDefinition[]
}
export interface VLANDashboardResponse {
  items: VLANDashboardGroup[]
}

/** GET /resources/audit-log — общий {items,total,offset,limit}, как большинство
 * ресурсов. Приложение пока без auth (см. README проекта), поэтому "кто сделал" в
 * записи нет — только что/когда/как. */
export interface AuditLogEntry {
  id: string
  entity_type: string
  entity_id: string
  action: 'CREATE' | 'UPDATE' | 'DELETE' | 'SYNC' | string
  details: string | null
  created_at: string
}

/** GET /api/v1/resources — список всех CRUD-ресурсов с человекочитаемым именем
 * (DISPLAY_NAMES на бэкенде) — используется для резолва entity_type в аудите вместо
 * дублирования того же словаря вручную во фронтенде (см. backend/app/api/resources.py). */
export interface ResourceDescriptor {
  key: string
  name: string
}

/** GET /api/v1/information-systems — плоский массив (в отличие от /devices, у которого
 * {items,total}, и /resources/{r}, у которого {items,total,offset,limit} — см. README). */
export interface InformationSystem {
  id: string
  number: number | null
  name: string
  type: string
  description: string | null
  purpose: string | null
  localization: string | null
  support_organization_id: string | null
  support_method_id: string | null
  process_description: string | null
  siem_enabled: boolean
  crypto_protection_enabled: boolean
  crypto_protection_description_id: string | null
  status: string
  created_at?: string
  updated_at?: string
}
