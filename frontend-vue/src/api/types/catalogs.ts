// Справочники и размещение. Часть типов API, см. ./index.ts.

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

/** GET /api/v1/resources — список всех CRUD-ресурсов с человекочитаемым именем
 * (DISPLAY_NAMES на бэкенде) — используется для резолва entity_type в аудите вместо
 * дублирования того же словаря вручную во фронтенде (см. backend/app/api/resources.py). */
export interface ResourceDescriptor {
  key: string
  name: string
}
