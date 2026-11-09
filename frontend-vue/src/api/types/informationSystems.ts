// Информационные системы. Часть типов API, см. ./index.ts.

import type { IPAddress } from './workloads'

/** GET /api/v1/resources/information-systems/{id}/details — атомарно синхронизируется через
 * PUT на тот же путь (backend/app/services/crud/information_system.py:sync_information_system_details), так же
 * как интерфейсы устройства (см. DeviceInterfacesEditor.vue), только эндпоинт лежит под
 * /resources/, а не /devices/. sources — единственный (с миграции b7f2c1e5a904) механизм связи
 * ИС с оборудованием/ВМ/контейнером и IP-адресом источника, не относящегося ни к одному из них
 * ('manual'); устаревшие таблицы-связки (ips/devices/vms/containers) и клиентская миграция в
 * sources удалены вместе с ними. */
export interface InformationSystemDetails {
  departments: Array<{ id: string; department_id: string }>
  protocols: Array<{ id: string; protocol_catalog_id: string; description: string | null }>
  sources: ISSource[]
  placement_assets: Array<{ id: string; placement_asset_id: string }>
}

/** owner_id — id устройства/ВМ/контейнера в зависимости от source_type (миграция 944bd490d967,
 * см. backend/app/models.py:InformationSystemSource) — заменяет прежние три отдельные FK-поля
 * (physical_device_id/virtual_machine_id/container_id), у которых реально было заполнено от силы
 * одно; null при source_type='manual'. */
export interface ISSource {
  id: string
  source_type: string
  owner_id: string | null
  ips: IPAddress[]
  purpose: string | null
  role: string | null
  external_interaction: boolean
}

/** Черновая строка CatalogPickerListEditor.vue — компонент не знает, какой каталог и какое
 * бэкенд-поле за ним стоит (передаётся через props), поэтому и строка максимально общая.
 * Переиспользуется для подразделений ИС (department_id) и мест размещения ИС
 * (placement_asset_id) — обе связи имеют одинаковую форму "выбери одну запись справочника". */
export interface CatalogPickerDraftRow {
  id?: string
  catalogId: string
}

/** Черновая строка ISProtocolsListEditor.vue. protocol/port больше не колонки backend-модели
 * (см. models.py, миграция b7f2c1e5a904) — значения показываются read-only из выбранной записи
 * справочника (protocol_catalog_id), обязательного поля. */
export interface ISProtocolDraftRow {
  id?: string
  protocol_catalog_id: string
  description: string
}

/** Черновая строка одного IP-адреса "ручного" источника ИС (ISSourcesListEditor.vue) — самый
 * простой из трёх вариантов черновых IP-строк (см. VmIpDraftRow/InterfaceIpDraftRow): ни
 * prefix_length, ни purpose, ни is_management источнику ИС не нужны, это просто список адресов
 * (миграция d8e35a1c7f60, вопрос 3/5 отчёта по анализу БД — несколько отдельных полей вместо
 * одного текстового через запятую). */
export interface SourceIpDraftRow {
  id?: string
  ip_address: string
}

/** Черновая строка ISSourcesListEditor.vue — см. комментарий к InformationSystemDetails.sources.
 * owner_id — единственное отправляемое на backend поле-владелец (id устройства при source_type=
 * 'device', ВМ при 'vm', контейнера при 'container'; пусто при 'manual'). vmHostHint — НЕ
 * отправляется на backend (см. buildDetailsPayload в InformationSystemFormModal.vue): чисто
 * клиентское состояние для UX выбора ВМ по её хосту (см. комментарий в ISSourcesListEditor.vue) —
 * нужно только пока при source_type='vm' сама ВМ ещё не выбрана (owner_id пуст), после выбора ВМ
 * её хост уже выводится из vmOptions по owner_id. */
export interface ISSourceDraftRow {
  id?: string
  source_type: 'manual' | 'device' | 'vm' | 'container'
  owner_id: string
  vmHostHint: string
  ips: SourceIpDraftRow[]
  purpose: string
  role: string
  external_interaction: boolean
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
  /** IP-адреса ИС — как в столбце «IP-адреса» отчёта: ручные источники и связанные ВМ (у ВМ с префиксом).
   * Есть в ответе списка и /resources (обогащение, см. services/serialization.py), в ответах на создание/правку — нет. */
  ip_addresses?: string[]
  created_at?: string
  updated_at?: string
}
