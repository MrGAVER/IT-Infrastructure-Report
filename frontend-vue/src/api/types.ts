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

/** GET /api/v1/resources/interfaces?physical_device_id=... — физический/логический порт
 * устройства (Лист 3 отчёта). Persist идёт НЕ через обычный CRUD /resources/interfaces, а через
 * атомарный PUT /api/v1/devices/{device_id}/interfaces (см. backend/app/services/crud.py:
 * sync_interfaces) — он одним запросом создаёт/обновляет/удаляет интерфейсы и их IP по diff'у с
 * тем, что уже есть в БД, и заодно валидирует vlan_ids. См. DeviceInterfacesEditor.vue.
 *
 * vlan_mode (фикс п.1.3.9) — хранится на самом интерфейсе (backend/app/models.py), а не выводится
 * из InterfaceVLAN.mode: при 0 назначенных VLAN связей нет вовсе, и без своей колонки режим
 * "access" было неоткуда восстановить при следующей загрузке (см. миграцию 5b5ea0e81d32).
 *
 * Аудит fix/usability-batch4 (находка №4): раньше этот тип был объявлен дважды в файле (здесь и
 * отдельно, самостоятельным блоком без extends CatalogItem, ближе к концу файла) — TypeScript
 * трактовал это как declaration merging, из-за чего поля вроде vlan_mode приходилось добавлять в
 * оба места синхронно. Объявление одно; extends CatalogItem сохранён, так как каталожный стор
 * (stores/catalogs.ts: sortCatalogItems<T extends CatalogItem>, items: Record<CatalogKey,
 * CatalogItem[]>) хранит интерфейсы устройства среди прочих каталожных сущностей. */
export interface DeviceInterface extends CatalogItem {
  physical_device_id: string
  interface_type_id: string | null
  mac_address: string | null
  speed_id: string | null
  is_management: boolean
  is_data_transfer: boolean
  description: string | null
  vlan_mode: 'access' | 'trunk'
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
  diagram_icon_id: string | null
  // Необязательный блок "Сертификат ОАЦ" — см. models.PhysicalDevice в backend/app/models.py.
  oac_certificate_number: string | null
  oac_certificate_registry_date: string | null
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
 * ВМ (VMFormModal.vue, owner_type='virtual_machine'), и для интерфейсов физических устройств
 * (InterfaceDraftRow.open_ports ниже, фикс п.1.4 батч4, owner_type='device_interface'), т.к.
 * OpenPort — полиморфная таблица с одинаковым набором полей независимо от owner_type.
 *
 * Без port/protocol (правка "убрать текстовые поля Порт/Протокол — эта информация уже есть в
 * справочнике портов"): единственный вход теперь — protocol_catalog_id, сервер сам подставляет
 * порт/протокол из справочника при сохранении (см. backend/app/services/crud.py:
 * _apply_open_port_catalog) и возвращает их в ответе OpenPort ниже — черновику их хранить не нужно. */
export interface OpenPortDraftRow {
  id?: string
  protocol_catalog_id: string
  transport_protocol: string
  description: string
}

/** GET /api/v1/resources/vm-software?virtual_machine_id=... — в отличие от OpenPort НЕ
 * полиморфная: у ВМ и устройства отдельные таблицы (vm_software/device_software) с разным
 * именем FK-колонки владельца, но одинаковым набором остальных полей — поэтому общий
 * SoftwareAssetListEditor.vue не завязан ни на одну из них (как и OpenPortListEditor.vue). */
export interface VMSoftware {
  id: string
  virtual_machine_id: string
  software_asset_id: string
  version: string | null
}

/** GET /api/v1/resources/device-software?physical_device_id=... — см. комментарий к VMSoftware. */
export interface DeviceSoftware {
  id: string
  physical_device_id: string
  software_asset_id: string
  version: string | null
}

/** Черновая строка SoftwareAssetListEditor.vue — переиспользуется VMFormModal.vue и
 * DeviceFormModal.vue (маппится в VMSoftware или DeviceSoftware вызывающим кодом). */
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
}

/** GET /api/v1/resources/information-systems/{id}/details — атомарно синхронизируется через
 * PUT на тот же путь (backend/app/services/crud.py:sync_information_system_details), так же
 * как интерфейсы устройства (см. DeviceInterfacesEditor.vue), только эндпоинт лежит под
 * /resources/, а не /devices/. `ips`/`devices`/`vms`/`containers` — устаревшие таблицы,
 * сохраняемые только ради обратной совместимости отчёта; читаются лишь один раз при первом
 * открытии формы для миграции в единый `sources`, если он ещё пуст (см.
 * InformationSystemFormModal.vue) — при сохранении всегда отправляются пустыми, как и в
 * vanilla-версии (frontend/static/information-systems.js:saveInformationSystemForm). */
export interface InformationSystemDetails {
  departments: Array<{ id: string; department_id: string }>
  ips: Array<{ id: string; ip_address: string; purpose: string | null; virtual_machine_id: string | null; physical_device_id: string | null; external_interaction: boolean }>
  protocols: Array<{ id: string; protocol_catalog_id: string | null; protocol: string; port: number | null; description: string | null }>
  devices: Array<{ id: string; physical_device_id: string; role: string | null }>
  vms: Array<{ id: string; virtual_machine_id: string; role: string | null }>
  containers: Array<{ id: string; container_id: string; role: string | null }>
  sources: ISSource[]
  placement_assets: Array<{ id: string; placement_asset_id: string }>
}

export interface ISSource {
  id: string
  source_type: string
  physical_device_id: string | null
  virtual_machine_id: string | null
  container_id: string | null
  ip_address: string | null
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

/** Черновая строка ISProtocolsListEditor.vue. protocol/port не редактируются напрямую —
 * подставляются при выборе protocol_catalog_id (см. компонент), но обязаны уйти в payload:
 * ISProtocol.protocol — обязательное поле на бэкенде (backend/app/models.py). */
export interface ISProtocolDraftRow {
  id?: string
  protocol_catalog_id: string
  protocol: string
  port: number | null
  description: string
}

/** Черновая строка ISSourcesListEditor.vue — см. комментарий к InformationSystemDetails.sources
 * и ISSourcesListEditor.vue про порядок полей source_type/physical_device_id/virtual_machine_id. */
export interface ISSourceDraftRow {
  id?: string
  source_type: 'manual' | 'device' | 'vm' | 'container'
  physical_device_id: string
  virtual_machine_id: string
  container_id: string
  ip_address: string
  purpose: string
  role: string
  external_interaction: boolean
}

/** GET /api/v1/resources/interface-ips?interface_id=... — см. комментарий к DeviceInterface. */
export interface InterfaceIP {
  id: string
  interface_id: string
  ip_address: string
  prefix_length: number | null
  purpose: string | null
  is_management: boolean
}

/** GET /api/v1/resources/device-type-vlans?device_type_id=... — какие определения VLAN
 * разрешены для типа устройства. Бэкенд использует то же самое множество (объединённое с уже
 * назначенными устройству VLAN, PhysicalDeviceVLAN) как allowed_vlans при валидации vlan_ids
 * интерфейса — см. sync_interfaces в backend/app/services/crud.py и api/portVlans.ts. */
export interface DeviceTypeVLAN {
  id: string
  device_type_id: string
  vlan_id: string
}

/** GET /api/v1/resources/interface-vlans?interface_id=... — назначение VLAN конкретному порту
 * (в отличие от DeviceVLAN — тот на устройство целиком). Список VLAN редактируется через
 * чекбоксы "VLAN на порту" в DeviceInterfacesEditor.vue (см. InterfaceDraftRow.vlan_ids). mode —
 * копия DeviceInterface.vlan_mode на момент сохранения (см. её комментарий и фикс п.1.3.9);
 * источник истины для режима порта — сам интерфейс, а не эта связь. */
export interface InterfaceVLAN {
  id: string
  interface_id: string
  vlan_id: string
  mode: string | null
}

/** Черновая строка IP-адреса интерфейса внутри DeviceInterfacesEditor.vue. */
export interface InterfaceIpDraftRow {
  id?: string
  ip_address: string
  prefix_length: string
  purpose: string
}

/** Черновая строка интерфейса внутри DeviceInterfacesEditor.vue. vlan_ids — id записей vlans
 * (VLANDefinition.id), назначенных этому порту через чекбоксы "VLAN на порту"; допустимый набор
 * опций вычисляется в api/portVlans.ts:computePortVlanOptions (тип устройства ∪ уже назначенные
 * устройству VLAN — то же множество, которое backend/app/services/crud.py:sync_interfaces
 * фактически разрешит при сохранении).
 *
 * vlan_mode (п.1.4.3.2) — режим порта: 'access' (ровно один VLAN) или 'trunk' (несколько VLAN,
 * в т.ч. "все" — это просто состояние, когда vlan_ids покрывает весь vlanOptions, отдельного
 * флага под это не заводили). Хранится на самом DeviceInterface.vlan_mode (фикс п.1.3.9,
 * backend/app/models.py + миграция 5b5ea0e81d32) — round-trip'ится через loadDeviceInterfaceDraftRows
 * / persistDeviceInterfaces напрямую, без вывода из связей. Раньше режим хранился только на
 * каждой связи InterfaceVLAN.mode и выводился как "trunk, если связей нет или их mode не везде
 * 'access'" — при 0 VLAN на порту связей не было вовсе, и access-режим без выбранного VLAN молча
 * откатывался в trunk после каждого сохранения+перезагрузки формы. item.vlan_mode по-прежнему
 * дублируется и на InterfaceVLAN.mode при сохранении (см. _sync_single_interface в crud.py) —
 * это не источник истины, а просто согласованность данных для любого другого читающего кода. */
export interface InterfaceDraftRow {
  id?: string
  name: string
  interface_type_id: string
  mac_address: string
  speed_id: string
  is_management: boolean
  is_data_transfer: boolean
  description: string
  vlan_ids: string[]
  vlan_mode: 'access' | 'trunk'
  ips: InterfaceIpDraftRow[]
  /** Фикс п.1.4 (батч4): "Открытые порты" переехали с уровня всего устройства на уровень
   * КОНКРЕТНОГО интерфейса — раньше один общий список (DeviceFormModal.vue) относился ко всему
   * устройству разом, что не позволяло корректно заполнить Лист 3 отчёта (колонка "Перечень
   * открытых портов" относится к конкретному физическому/логическому порту, см.
   * backend/app/reporting.py:_port_open_info) и не давало скопировать набор портов с одного
   * интерфейса на другой. Персистится атомарно вместе с интерфейсом, см.
   * api/deviceInterfaces.ts:persistDeviceInterfaces. */
  open_ports: OpenPortDraftRow[]
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
/** GET /api/v1/resources/vlan-domains — CRUD через generic /resources/vlan-domains, участники —
 * VLANDomainDeviceLink (см. ниже), синхронизация — POST /api/v1/vlan-domains/{id}/sync
 * (backend/app/api/system.py:sync_vlan_domain), копирует VLAN устройства source_device_id на
 * всех остальных участников домена. source_device_id опционален: без него синхронизация
 * недоступна (кнопка скрыта в VLANDomainsPanel.vue, как и в vanilla-версии — см. app.js, рендер
 * списка ресурсов: кнопка «Синхронизировать» показывается только при x.source_device_id). */
export interface VLANDomain {
  id: string
  name: string
  description: string | null
  source_device_id: string | null
  auto_sync: boolean
}
/** GET /api/v1/resources/device-vlans?physical_device_id=... — назначение VLAN устройству
 * (в отличие от interface_vlans — не привязано к конкретному порту, а к устройству в целом).
 * persist — обычный delete-затем-recreate через createResource/deleteResource (НЕ атомарный
 * PUT, в отличие от интерфейсов устройства и деталей ИС) — так же, как в vanilla-версии
 * (saveDeviceVlans в frontend/static/device-interfaces.js). */
export interface DeviceVLAN {
  id: string
  physical_device_id: string
  vlan_id: string
  ip_address: string | null
  prefix_length: number | null
  is_management: boolean
  description: string | null
}

/** GET /api/v1/resources/vlan-domain-devices?physical_device_id=... — членство устройства в
 * VLAN-домене; определяет, какие доменные VLAN доступны для выбора в DeviceVlanListEditor.vue
 * (домен-независимые VLAN доступны всем устройствам, доменные — только участникам домена). */
export interface VLANDomainDeviceLink {
  id: string
  domain_id: string
  physical_device_id: string
}

/** Пункт 5 правки "создание физического устройства": стек физических устройств. CRUD — через
 * generic /resources/device-stacks, членство — через /resources/device-stack-members (не путать
 * с добавлением участника — POST /device-stacks/{id}/members ниже, идемпотентный и с понятной
 * 409, если устройство уже в другом стеке, см. backend/app/api/system.py). */
export interface DeviceStack {
  id: string
  name: string
  description: string | null
}

export interface DeviceStackMember {
  id: string
  stack_id: string
  physical_device_id: string
  position: number
}

/** GET /api/v1/device-stacks/{id}/detail (backend/app/api/system.py:device_stack_detail) —
 * "просмотр... вместе": участники — Device (см. enrich_devices) плюс два поля из членства, и
 * связывающие подключения — та же форма, что Connection ниже (см. enrich_connections),
 * вычисленные на лету по признаку "оба конца — интерфейсы устройств из этого стека" (не
 * хранятся отдельным флагом, см. docstring класса DeviceStack в models.py). */
export interface DeviceStackMemberDetail extends Device {
  stack_member_id: string
  stack_position: number
}

export interface DeviceStackDetail {
  stack: DeviceStack
  members: DeviceStackMemberDetail[]
  connections: Connection[]
}

/** Черновая строка DeviceVlanListEditor.vue. */
export interface DeviceVlanDraftRow {
  id?: string
  vlan_id: string
  ip_address: string
  prefix_length: string
  is_management: boolean
  description: string
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

/** GET/POST/PUT /api/v1/report-templates — шаблоны конструктора произвольных отчётов. Свой
 * роутер (backend/app/api/report_builder.py), НЕ /resources/{resource} — у него нестандартные
 * операции (versions/restore, duplicate, generate), см. api/reportTemplates.ts. config —
 * непрозрачный для этого API JSON (структура описана в backend/app/services/report_grid.py для
 * xlsx и report_engine.py для docx); вся структурная валидация выполняется на сервере. */
export interface ReportTemplate {
  id: string
  name: string
  description: string | null
  format: 'xlsx' | 'docx'
  config: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}

/** Запись истории версий шаблона — только метаданные, сам config версии наружу не отдаётся
 * (см. list_template_versions в backend/app/api/report_builder.py); восстановление выполняется
 * целиком на сервере через отдельный POST .../restore. */
export interface ReportTemplateVersion {
  id: string
  version_number: number
  name: string
  description: string | null
  format: 'xlsx' | 'docx'
  created_at: string | null
}

/** GET /api/v1/report-builder/entities — метаданные сущностей для конструктора отчётов: поля +
 * связи "один-к-одному" (to_one) / обратные "один-ко-многим" (to_many), см.
 * backend/app/services/report_meta.py:entity_metadata_public. Используется и палитрой полей
 * (построение путей вида relation[].field, см. utils/reportEntityPaths.ts), и панелью источника
 * данных повторяющейся строки грид-редактора (root_entity/expand). */
export interface ReportEntityField {
  name: string
  label: string
  type: string
  is_foreign_key: boolean
}
export interface ReportEntityRelation {
  name: string
  target: string
}
export interface ReportEntityMeta {
  key: string
  label: string
  fields: ReportEntityField[]
  to_one: ReportEntityRelation[]
  to_many: ReportEntityRelation[]
}

/** Формат конфигурации грид-листа (config.sheets[i]) — подробно описан в
 * backend/app/services/report_grid.py; здесь только TS-проекция того же формата один в один,
 * структурная валидация полностью на сервере (см. validate_grid_config). */
export interface GridCellStyle {
  bold?: boolean
  italic?: boolean
  underline?: boolean
  align?: 'left' | 'center' | 'right'
  valign?: 'top' | 'middle' | 'bottom'
  wrap?: boolean
  bg?: string
  color?: string
  border?: boolean
  number_format?: string
}

export type GridCellKind = 'static' | 'field' | 'index' | 'formula'

export interface GridCell {
  col: number
  colspan?: number
  rowspan?: number
  kind: GridCellKind
  text?: string
  path?: string
  separator?: string
  style?: GridCellStyle
}

export type GridFilterOp = 'eq' | 'ne' | 'contains' | 'not_contains' | 'not_empty' | 'is_true' | 'is_false'
export interface GridDataSourceFilter {
  path: string
  op: GridFilterOp
  value: string
}
export interface GridDataSource {
  root_entity: string
  expand: string
  include_empty_expand: boolean
  filters: GridDataSourceFilter[]
  sort_by: string
}

export interface GridRow {
  height: number
  repeat: boolean
  data_source: GridDataSource | null
  cells: GridCell[]
}

export interface GridColumn {
  width: number
}

export interface GridSheet {
  title: string
  columns: GridColumn[]
  rows: GridRow[]
}

export interface GridConfig {
  sheets: GridSheet[]
}

/** Формат конфигурации docx-блоков (config.blocks) — см. backend/app/services/report_engine.py:
 * validate_config/build_docx. filters использует тот же формат {path, op, value}, что и
 * GridDataSourceFilter у повторяющейся строки xlsx — общая структура на обоих форматах. */
export interface DocxTableColumn {
  header: string
  source: 'field' | 'index' | 'static'
  path?: string
  separator?: string
  value?: string
}
export interface DocxHeadingBlock {
  type: 'heading'
  text: string
  level?: number
}
export interface DocxParagraphBlock {
  type: 'paragraph'
  text: string
  align?: 'left' | 'center'
}
export interface DocxPageBreakBlock {
  type: 'page_break'
}
export interface DocxTableBlock {
  type: 'table'
  title?: string
  root_entity: string
  expand?: string
  include_empty_expand?: boolean
  sort_by?: string
  filters: GridDataSourceFilter[]
  columns: DocxTableColumn[]
}
export type DocxBlock = DocxHeadingBlock | DocxParagraphBlock | DocxPageBreakBlock | DocxTableBlock

export interface DocxConfig {
  blocks: DocxBlock[]
}

/** Ответ POST /api/v1/report-builder/preview для format='xlsx' — материализованные физические
 * строки/ячейки каждого листа (повторяющиеся строки уже развёрнуты в отдельные физические
 * строки с реальными значениями, урезано до limit записей на повторение), см.
 * backend/app/services/report_grid.py:preview_grid/_physical_rows. cells внутри одной строки —
 * только те позиции, где реально начинается ячейка (как и в самом редакторе), colspan/rowspan
 * нужно так же учитывать при отрисовке (см. utils/gridCoverage.ts:visibleCellsForRow). */
export interface GridPreviewCell {
  col: number
  colspan: number
  rowspan: number
  value: unknown
  is_datetime: boolean
  style: GridCellStyle
}
export interface GridPreviewRow {
  height: number
  cells: GridPreviewCell[]
}
export interface GridPreviewSection {
  title: string
  error?: string
  n_cols?: number
  rows?: GridPreviewRow[]
  total_records?: number
}
export interface GridPreviewResponse {
  sections: GridPreviewSection[]
}

/** Ответ POST /api/v1/report-builder/preview для format='docx' — по одной секции на блок-таблицу
 * (остальные типы блоков в предпросмотре не участвуют, см.
 * backend/app/services/report_render.py:preview_rows/block_tables). rows — уже отрендеренные
 * значения ячеек (не объекты), total — сколько всего записей нашлось до обрезки limit'ом. */
export interface DocxPreviewSection {
  title: string
  error?: string
  headers?: string[]
  rows?: unknown[][]
  total?: number
}
export interface DocxPreviewResponse {
  sections: DocxPreviewSection[]
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

// --- Аутентификация (backend/app/api/auth.py, backend/app/services/auth.serialize_user) --------
// Ровно две роли — см. UserRole в backend/app/constants.py: admin (полный доступ + управление
// пользователями/тумблером) и viewer (только чтение, кроме собственного logout).
export type UserRole = 'admin' | 'viewer'

export interface AuthUser {
  id: string
  username: string
  role: UserRole
  is_active: boolean
  last_login_at: string | null
  locked: boolean
  created_at: string
}

export interface AuthStatus {
  enabled: boolean
  session_ttl_hours: number
}

export interface AuthMeResponse {
  enabled: boolean
  user: AuthUser | null
}

export interface LoginResponse {
  token: string
  user: AuthUser
}

export interface AuthSessionInfo {
  id: string
  created_at: string
  expires_at: string
  user_agent: string | null
  ip_address: string | null
  /** Сессия, которой был выполнен сам запрос GET /auth/sessions (см.
   * backend/app/services/auth.serialize_session) — не бизнес-данные конкретной сессии, а
   * relation to "текущий запрос". */
  current: boolean
}
