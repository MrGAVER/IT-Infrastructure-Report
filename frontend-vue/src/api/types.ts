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
