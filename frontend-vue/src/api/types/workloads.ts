// Виртуальные машины, контейнеры, IP-адреса, порты и ПО. Часть типов API, см. ./index.ts.

/** GET /api/v1/vms — {items,total}, как /devices (не {items,total,offset,limit} и не
 * плоский массив как /information-systems) — третий вариант формы ответа в этом API. */
export interface VirtualMachine {
  id: string
  name: string
  operating_system_id: string | null
  physical_device_id: string | null
  hypervisor_os_id: string | null
  purpose: string | null
  description: string | null
  created_at?: string
  updated_at?: string
}

export interface VMsResponse {
  items: VirtualMachine[]
  total: number
}

/** GET /api/v1/resources/ip-addresses?owner_type=...&owner_id=... — единая модель вместо
 * прежних отдельных InterfaceIP/VMIP и IP-адреса(ов) на строке InformationSystemSource
 * (backend/app/models.py:IPAddress, миграция d8e35a1c7f60), тот же паттерн owner_type/owner_id,
 * что уже применён к OpenPort/DeployedSoftware. Лист 4 требует "IP-адрес виртуальной
 * машины/контейнера" — у одного владельца их может быть несколько, поэтому отдельная таблица, а
 * не колонка на владельце. */
export interface IPAddress {
  id: string
  owner_type: string
  owner_id: string
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

/** Черновая строка редактора IP-адресов ВМ (VmIpListEditor.vue). Поля — строки для прямого
 * v-model на input'ах (в т.ч. числовое prefix_length: пустая строка — валидное "не задано",
 * что не выразить через number). Конвертируется в payload IPAddress при сохранении (owner_type=
 * 'virtual_machine'), см. VMFormModal.vue:persistSoftwareAssets и аналогичный persistVmIps.
 * `id` присутствует только у строк, загруженных с бэкенда. */
export interface VmIpDraftRow {
  id?: string
  ip_address: string
  prefix_length: string
  purpose: string
  is_management: boolean
}

/** Черновая строка редактора открытых портов (OpenPortListEditor.vue) — переиспользуется и для
 * ВМ (VMFormModal.vue, owner_type='virtual_machine'), и для интерфейсов физических устройств
 * (InterfaceDraftRow.open_ports в ./interfaces.ts, фикс п.1.4 батч4, owner_type='device_interface'), т.к.
 * OpenPort — полиморфная таблица с одинаковым набором полей независимо от owner_type.
 *
 * Без port/protocol (правка "убрать текстовые поля Порт/Протокол — эта информация уже есть в
 * справочнике портов"): единственный вход теперь — protocol_catalog_id; port/protocol больше не
 * колонки backend-модели вовсе (см. models.py, миграция b7f2c1e5a904) — сервер вычисляет их из
 * справочника на КАЖДОЕ чтение (services/serialization.py:enrich_open_port(s)) и возвращает в
 * ответе OpenPort ниже — черновику их хранить не нужно. */
export interface OpenPortDraftRow {
  id?: string
  protocol_catalog_id: string
  transport_protocol: string
  description: string
}

/** GET /api/v1/resources/deployed-software?owner_type=...&owner_id=... — единая модель вместо
 * прежних отдельных VMSoftware/DeviceSoftware (backend/app/models.py:DeployedSoftware,
 * миграция c4a91e6f2b83), тот же паттерн owner_type/owner_id, что уже применён к OpenPort. */
export interface DeployedSoftware {
  id: string
  owner_type: 'physical_device' | 'virtual_machine'
  owner_id: string
  software_asset_id: string
  version: string | null
}

/** Черновая строка SoftwareAssetListEditor.vue — переиспользуется VMFormModal.vue и
 * DeviceFormModal.vue (маппится в DeployedSoftware вызывающим кодом, с нужным owner_type). */
export interface SoftwareAssetDraftRow {
  id?: string
  software_asset_id: string
  version: string
}

/** GET /api/v1/resources/containers — сейчас читается только для одного выпадающего списка
 * (ISSourcesListEditor.vue). Собственного экрана/стора у контейнеров пока нет, см.
 * "Ещё не сделано" во frontend-vue/README.md. */
/** GET /api/v1/resources/containers — простой generic-ресурс, свой экран см.
 * views/ContainersView.vue. */
export interface Container {
  id: string
  name: string
  virtual_machine_id: string | null
  physical_device_id: string | null
  runtime: string | null
  runtime_version: string | null
  purpose: string | null
  /** Отметка последнего изменения: форма передаёт её серверу при сохранении (оптимистичная блокировка, см. useStaleRecordGuard). */
  updated_at?: string
}
