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
  vlan_mode: VlanMode
  /** «Все VLAN» — сохраняемый признак (backend models.DeviceInterface.all_vlans), а не вывод из числа выбранных VLAN.
   * Порт с признаком (только trunk) не хранит связей: его VLAN — все VLAN устройства, их отдаёт
   * GET /devices/{id}/interface-vlans. */
  all_vlans?: boolean
  /** Группа портов (InterfaceGroup), в которую входит порт; null — вне групп. */
  group_id?: string | null
  /** Подинтерфейсы порта — приходят только в ответе PUT /devices/{id}/interfaces (в generic-списке
   * /resources/interfaces их нет: подинтерфейс — не физический порт). */
  subinterfaces?: DeviceSubinterface[]
}

/** Подинтерфейс порта устройства (backend models.DeviceSubinterface, GET /devices/{id}/subinterfaces и
 * поле subinterfaces элементов ответа PUT /devices/{id}/interfaces): логический интерфейс на одном VLAN со
 * своими IP, открытыми портами и флагами роли — как `Gi0/0.10` у маршрутизатора или межсетевого экрана.
 * vlan_id — id записи справочника VLAN (VLANDefinition.id), не номер VLAN. */
export interface DeviceSubinterface {
  id: string
  parent_interface_id: string
  name: string
  vlan_id: string
  is_management: boolean
  is_data_transfer: boolean
  description: string | null
  ips: { id: string; ip_address: string; prefix_length: number | null; purpose: string | null }[]
  open_ports: { id: string; protocol_catalog_id: string; transport_protocol: string; description: string | null }[]
}

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
  // Принадлежность к стеку устройств (DeviceStackMember) — см. models.py. Устройство состоит
  // максимум в одном стеке, все три поля либо все null (вне стека), либо все заполнены разом.
  stack_id: string | null
  stack_name: string | null
  stack_position: number | null
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
 * (InterfaceDraftRow.open_ports ниже, фикс п.1.4 батч4, owner_type='device_interface'), т.к.
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
}

/** GET /api/v1/resources/information-systems/{id}/details — атомарно синхронизируется через
 * PUT на тот же путь (backend/app/services/crud.py:sync_information_system_details), так же
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

/** Элемент ответа GET /api/v1/devices/{id}/interface-vlans — VLAN одного порта с учётом «Все VLAN». У порта с признаком
 * vlan_ids — все VLAN его устройства (набор вычисляется на сервере, связей у такого порта нет), у остальных — выбранные.
 * Номера VLAN отсортированы по номеру. Запрос ограничен устройством: общий список связей реестра
 * (/resources/interface-vlans) отдаёт не больше 1000 записей, и при их превышении VLAN свежих портов «пропадали». */
export interface InterfaceVlansEntry {
  interface_id: string
  all_vlans: boolean
  vlan_ids: string[]
}

/** Черновая строка IP-адреса интерфейса внутри DeviceInterfacesEditor.vue. Конвертируется в
 * payload IPAddress при сохранении (owner_type='device_interface', is_management наследуется от
 * самого интерфейса — не редактируется на уровне отдельного IP, см. _sync_interface_ips). */
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
/** Пункты 1-2 правки "физическое устройство: расхождение с соседним портом" — DeviceFormModal.vue
 * (interfaceConflicts) считает это по активному Connection этого интерфейса, DeviceInterfacesEditor.vue
 * только показывает и предлагает разрешить (кнопки "Применить текущую"/"Применить соседа"). Один
 * объект — на интерфейс, у которого есть активное подключение и (хотя бы одно) расхождение;
 * flagsDiffer/vlanModeDiffer — независимые флаги, т.к. это два разных пункта правки с разным
 * местом в UI (col-check ячейки vs строка "Режим порта" в развёрнутой детали). */
export interface PortConflictInfo {
  otherInterfaceId: string
  otherDeviceName: string
  otherInterfaceName: string
  flagsDiffer: boolean
  vlanModeDiffer: boolean
  /** Оба порта в trunk, и «Все VLAN» стоит только у одного (utils/allVlans.ts:allVlansDiffer). */
  allVlansDiffer: boolean
  other: { is_management: boolean; is_data_transfer: boolean; vlan_mode: 'access' | 'trunk'; all_vlans: boolean }
}

/** Черновик подключения порта в блоке «Порты / интерфейсы» формы устройства (см.
 * components/InterfaceConnectionEditor.vue). Хранится в InterfaceDraftRow.connection. Подключение
 * активное; направление (источник/назначение) задаёт сервер: новый порт — источник. peer_device_id
 * нужен только интерфейсу формы (каскад «устройство → порт»), на сервер не отправляется.
 *
 * Сосед — ровно одно из двух: peer_interface_id (сохранённый порт, в том числе другой порт ЭТОГО же
 * устройства) либо peer_row_key (ещё не сохранённая строка этой же формы, InterfaceDraftRow.key: у
 * неё нет id). При отправке peer_row_key превращается в номер элемента массива interfaces (peer_row). */
export interface InterfaceConnectionDraft {
  peer_device_id: string
  peer_interface_id: string
  connection_type_id: string
  description: string
  peer_row_key?: string
  /** Имя порта соседа для подписи в свёрнутой строке (только отображение, на сервер не уходит). Задаётся при
   * загрузке подключения с сервера и при выборе порта соседа на другом устройстве. */
  peer_interface_name?: string
  /** Подпись устройства соседа (только отображение, на сервер не уходит): полный список устройств форме не
   * загружается, поэтому подпись выбранного соседа хранится в черновике. Задаётся при загрузке подключения
   * с сервера и при выборе устройства. */
  peer_device_name?: string
}

/** Черновик подинтерфейса порта внутри DeviceInterfacesEditor.vue (components/InterfaceSubinterfacesEditor.vue).
 * key — стабильный ключ строки в пределах формы (у новой строки нет id), на сервер не отправляется.
 * vlan_id пуст, пока VLAN не выбран; сохранить подинтерфейс без VLAN нельзя (utils/subinterfaces.ts). */
export interface SubinterfaceDraftRow {
  id?: string
  key: string
  name: string
  vlan_id: string
  is_management: boolean
  is_data_transfer: boolean
  description: string
  ips: InterfaceIpDraftRow[]
  open_ports: OpenPortDraftRow[]
}

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
  /** «Все VLAN» (только trunk): сохраняемый признак порта. Пока он стоит, vlan_ids зеркалит ВСЕ допустимые VLAN
   * устройства (форма показывает их отмеченными и сверяет с изменением VLAN устройства), а сервер хранит только
   * признак. Любой ручной выбор VLAN снимает признак — даже если выбраны все. Не задано = false. */
  all_vlans?: boolean
  ips: InterfaceIpDraftRow[]
  /** Фикс п.1.4 (батч4): "Открытые порты" переехали с уровня всего устройства на уровень
   * КОНКРЕТНОГО интерфейса — раньше один общий список (DeviceFormModal.vue) относился ко всему
   * устройству разом, что не позволяло корректно заполнить Лист 3 отчёта (колонка "Перечень
   * открытых портов" относится к конкретному физическому/логическому порту, см.
   * backend/app/reporting.py:_port_open_info) и не давало скопировать набор портов с одного
   * интерфейса на другой. Персистится атомарно вместе с интерфейсом, см.
   * api/deviceInterfaces.ts:persistDeviceInterfaces. */
  open_ports: OpenPortDraftRow[]
  /** Ключ группы портов (InterfaceGroupDraft.key), в которую входит порт; пусто/не задан — порт вне
   * групп. У сохранённой группы ключ равен её id. Значения параметров, которыми управляет группа,
   * уже записаны в поля этой строки (utils/interfaceGroups.ts:applyGroupToRow) — сервер их
   * подтверждает при сохранении, а таблица и отчёты видят итоговые значения порта. */
  group_key?: string
  /** Подключение порта к порту другого устройства: null — порт не подключён (или не загружен),
   * не задано — форма подключения не редактируется (окно «Управлять портами»). Сохраняется тем же
   * PUT, что и порт (api/deviceInterfaces.ts:persistDeviceInterfaces, backend
   * services/interface_connections.py), поэтому доступно и для ещё не сохранённых портов. */
  connection?: InterfaceConnectionDraft | null
  /** Подинтерфейсы порта (логические интерфейсы на VLAN со своими IP и параметрами). Не задано — подинтерфейсы
   * порта не редактируются этой формой и сервер их не трогает; [] — у порта их нет (сервер удалит прежние).
   * Загрузка и отправка — api/deviceInterfaces.ts. */
  subinterfaces?: SubinterfaceDraftRow[]
  /** Стабильный ключ строки в пределах формы (в отличие от индекса не меняется при добавлении и
   * удалении строк). Нужен только строкам без id, на которые ссылается подключение другого порта
   * этой же формы (InterfaceConnectionDraft.peer_row_key). Задаёт редактор портов при создании
   * строки (только если включено редактирование подключений); на сервер не отправляется. */
  key?: string
}

/** Черновик группы портов устройства (backend models.InterfaceGroup): параметры, заданные один
 * раз и применяемые ко всем портам группы. Параметр «управляется» группой только если задан:
 * vlan_mode !== '' — режим порта и VLAN; ip_address !== '' — общий IP (один адрес на все порты);
 * ip_purpose !== '' (при заданном IP) — назначение этого IP; manage_open_ports — полный список
 * открытых портов. Незаданные параметры порты хранят свои. */
export interface InterfaceGroupDraft {
  id?: string
  /** Сохранённая группа: её id. Новая: временный ключ (utils/interfaceGroups.ts:newGroupKey) —
   * по нему порты ссылаются на группу, у которой id ещё нет. */
  key: string
  name: string
  vlan_mode: '' | 'access' | 'trunk'
  vlan_ids: string[]
  /** «Все VLAN» группы (только trunk) — тот же признак, что у порта (InterfaceDraftRow.all_vlans): сервер хранит
   * только его, а порты группы получают такой же признак. Не задано = false. */
  all_vlans?: boolean
  ip_address: string
  prefix_length: string
  /** Назначение общего IP («Назначение» рядом с «IP-адрес» и «Префикс»); хранится, только пока задан ip_address. */
  ip_purpose: string
  manage_open_ports: boolean
  open_ports: OpenPortDraftRow[]
  /** Группа задаёт полный список подинтерфейсов своих портов (как manage_open_ports — открытых портов): каждому порту
   * записываются подинтерфейсы `<порт>.<номер VLAN>` по шаблонам ниже. Не задано = false. */
  manage_subinterfaces?: boolean
  /** Шаблоны подинтерфейсов группы (учитываются, только пока manage_subinterfaces). Свои имена у шаблонов пусты: имя
   * подинтерфейса порта строится из имени порта и номера VLAN. VLAN шаблона — один из VLAN группы. Не задано = []. */
  subinterfaces?: SubinterfaceDraftRow[]
}

/** GET /api/v1/devices/{id}/interface-groups (и поле groups ответа PUT .../interfaces). */
export interface InterfaceGroup {
  id: string
  physical_device_id: string
  name: string
  vlan_mode: 'access' | 'trunk' | null
  vlan_ids: string[]
  /** «Все VLAN» группы: при признаке vlan_ids — все VLAN устройства (вычисляются сервером, связей у группы нет). */
  all_vlans?: boolean
  ip_address: string | null
  prefix_length: number | null
  ip_purpose: string | null
  manage_open_ports: boolean
  open_ports: { id: string; protocol_catalog_id: string; transport_protocol: string; description: string | null }[]
  manage_subinterfaces?: boolean
  subinterfaces?: InterfaceGroupSubinterface[]
}

/** Подинтерфейс группы портов в ответе сервера (шаблон, который группа записывает в каждый свой порт): без имени и порта-родителя. */
export interface InterfaceGroupSubinterface {
  id: string
  group_id: string
  vlan_id: string
  is_management: boolean
  is_data_transfer: boolean
  description: string | null
  ips: { id: string; ip_address: string; prefix_length: number | null; purpose: string | null }[]
  open_ports: { id: string; protocol_catalog_id: string; transport_protocol: string; description: string | null }[]
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

/** Состояние одного VLAN у одного участника стека — GET /api/v1/device-stacks/{id}/vlans (members). */
export interface StackVlanMemberState {
  physical_device_id: string
  device_name: string
  assigned: boolean
  ip_address: string | null
  prefix_length: number | null
  is_management: boolean
  description: string | null
}

/** Общая настройка VLAN стека (кластера): IP-адрес, префикс и «Управление» заданы стеку и записаны каждому участнику.
 * is_uniform — у каждого участника VLAN назначен и значения равны настройке (иначе нужно «Применить ко всем»). */
export interface StackVlanRow {
  vlan_id: string
  vlan_number: number
  vlan_name: string
  domain_id: string | null
  is_shared: true
  ip_address: string | null
  prefix_length: number | null
  is_management: boolean
  is_uniform: boolean
  assigned_count: number
  member_count: number
  members: StackVlanMemberState[]
}

/** VLAN справочника, который ещё можно сделать общим для стека (его можно назначить каждому участнику). Адрес с префиксом —
 * подсказка: значение, на котором сошлись участники с этим VLAN; is_management — «Управление» включено хотя бы у одного. */
export interface StackVlanOption {
  vlan_id: string
  vlan_number: number
  vlan_name: string
  ip_address: string | null
  prefix_length: number | null
  is_management: boolean
  assigned_count: number
}

/** Ответ GET/PUT/DELETE /api/v1/device-stacks/{id}/vlans[/{vlan_id}]. */
export interface DeviceStackVlans {
  stack_name: string
  member_count: number
  items: StackVlanRow[]
  available: StackVlanOption[]
}

/** Значения, которые общая настройка задаёт устройству. */
export interface StackVlanValues {
  ip_address: string | null
  prefix_length: number | null
  is_management: boolean
}

/** Одна строка предпросмотра добавления устройства в стек: 'add' — VLAN будет назначен, 'update' — значения заменятся (before → after). */
export interface StackMemberChange {
  vlan_id: string
  vlan_number: number
  vlan_name: string
  action: 'add' | 'update'
  before: StackVlanValues | null
  after: StackVlanValues
}

/** GET /api/v1/device-stacks/{id}/members/preview — что произойдёт с данными устройства при добавлении в стек. */
export interface StackMemberPreview {
  stack_name: string
  device_name: string
  already_member: boolean
  changes: StackMemberChange[]
  unchanged_count: number
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
/** Домен VLAN, в который устройство входит (pending: false) либо будет включено при сохранении
 * формы (pending: true) — см. DeviceVlanListEditor.vue (memberDomains) и DeviceFormModal.vue. */
export interface DeviceMemberDomain {
  id: string
  name: string
  pending: boolean
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

/** Запись журнала аудита (GET /api/v1/audit-log). Автор действия — actor_*: имя пользователя известно,
 * только если аутентификация была включена; адрес клиента — всегда, кроме записей, сделанных до
 * появления этих полей (у них все три равны null). */
export interface AuditLogEntry {
  id: string
  entity_type: string
  entity_id: string
  action: 'CREATE' | 'UPDATE' | 'DELETE' | 'SYNC' | string
  details: string | null
  created_at: string
  actor_id: string | null
  actor_username: string | null
  actor_ip: string | null
}

// --- Правила автоматического согласования данных порта (backend/app/services/port_sync_rules.py) ---

/** auto — применяется автоматически (после предпросмотра и подтверждения); manual — расхождение
 * известного вида, направление выбирает человек; ignore — пару не трогать. */
export type PortSyncAction = 'auto' | 'manual' | 'ignore'
/** Условие на роль порта; any — любая. */
export type PortSyncRoleCondition = 'any' | PortRole
export type PortSyncModeCondition = 'any' | VlanMode
/** Состояние VLAN порта: none — не назначены совсем; set — назначен хотя бы один (в том числе все);
 * all — назначены ВСЕ VLAN, доступные устройству («Все VLAN»). */
export type PortSyncVlanCondition = 'any' | 'none' | 'set' | 'all'
/** Отношение значений целевого порта и порта-источника. */
export type PortSyncRelation = 'any' | 'same' | 'differs'
/** Что делать с VLAN: keep — не менять; copy — взять набор соседа; adapt — привести к режиму
 * (в access остаётся один VLAN с наименьшим номером); union — объединить: ОБА порта получают объединение
 * наборов обоих (ни один VLAN не снимается), направление выбирать не нужно; all — «Все VLAN»: порт получает все VLAN
 * СВОЕГО устройства (номера VLAN соседа не переносятся), уже назначенные не снимаются. */
export type PortSyncVlanPolicy = 'keep' | 'copy' | 'adapt' | 'union' | 'all'

export interface PortSyncCondition<V> {
  role: PortSyncRoleCondition
  mode: PortSyncModeCondition
  vlans: V
}

export interface PortSyncRule {
  id: string
  /** Устойчивый идентификатор стандартного правила; у пользовательского null. */
  code: string | null
  builtin: boolean
  /** Стандартное правило изменено относительно исходного (порядок и «включено» не считаются). */
  modified: boolean
  name: string
  description: string
  enabled: boolean
  /** Порядок проверки: меньше — раньше. */
  priority: number
  action: PortSyncAction
  /** Условия на порт, которому применяются изменения. */
  target: PortSyncCondition<PortSyncVlanCondition>
  /** Условия на порт на другом конце подключения, чьи значения берутся. */
  source: PortSyncCondition<PortSyncVlanCondition>
  relation: { role: PortSyncRelation; mode: PortSyncRelation; vlans: PortSyncRelation }
  apply: { role: boolean; mode: boolean; vlans: PortSyncVlanPolicy }
  created_at?: string | null
  updated_at?: string | null
}

/** Тело POST/PUT /port-sync/rules: без служебных полей. */
export type PortSyncRuleInput = Omit<PortSyncRule, 'id' | 'code' | 'builtin' | 'modified' | 'created_at' | 'updated_at'>

export type PortSyncOutcome = 'auto' | 'blocked' | 'manual' | 'ignored' | 'none' | 'skipped'

export interface PortSyncPortView {
  interface_id: string
  name: string
  device_id: string | null
  device_name: string
  role: PortRole | null
  mode: VlanMode | null
  vlans: number[]
}

export interface PortSyncChanges {
  role: { from: PortRole; to: PortRole } | null
  mode: { from: VlanMode; to: VlanMode } | null
  /** skipped — номера VLAN соседа, которых нет у устройства порта: они не назначаются. */
  vlans: { from: number[]; to: number[]; skipped: number[] } | null
}

export interface PortSyncOption {
  target: 'source' | 'destination'
  /** all_vlans — порту нужно «Все VLAN» устройства (номера определит устройство порта); у остальных вариантов отсутствует. */
  changes: { role: PortRole | null; mode: VlanMode | null; vlans: number[] | null; all_vlans?: boolean }
}

/** Один из портов подключения, которым правило применяет изменения. */
export interface PortSyncTarget {
  target: 'source' | 'destination'
  changes: PortSyncChanges | null
  /** Почему именно этому порту изменение не применится (группа, нет VLAN у устройства…); null — применится. */
  blocked: string | null
}

export interface PortSyncPlanItem {
  connection_id: string
  outcome: PortSyncOutcome
  reason: string | null
  rule: { id: string | null; code: string | null; name: string; action: PortSyncAction } | null
  /** Какой порт подключения меняется (для auto и blocked); both — оба (симметричное правило «объединить»). */
  target: 'source' | 'destination' | 'both' | null
  source: PortSyncPortView
  destination: PortSyncPortView
  /** Изменения единственного целевого порта; при target = both — null, см. targets. */
  changes: PortSyncChanges | null
  /** Целевые порты с изменениями каждого (для auto и blocked). Может отсутствовать в старых ответах. */
  targets?: PortSyncTarget[]
  options: PortSyncOption[]
  warnings: string[]
  /** Решение применимо, но расхождение после применения останется: часть VLAN пропущена (нет у устройства порта)
   * или один из двух портов пары не меняется. Может отсутствовать в старых ответах. */
  partial?: boolean
}

export interface PortSyncSummary {
  connections: number
  /** Сколько ПОРТОВ будет изменено при применении (у симметричного правила одно подключение даёт два порта;
   * число подключений — auto). */
  applicable: number
  shown: number
  total_items: number
  auto: number
  blocked: number
  manual: number
  ignored: number
  none: number
  skipped: number
  /** Сколько подключений плана после применения останутся с расхождением (по всему плану, не только по показанным).
   * Может отсутствовать в старых ответах. */
  partial?: number
}

/** Положение страницы в плане: total — всего элементов плана, has_more — есть ли ещё после этой страницы. */
export interface PortSyncPlanPage {
  offset: number
  limit: number
  total: number
  has_more: boolean
}

export interface PortSyncPlan {
  /** Элементы ЭТОЙ страницы плана (summary.shown — их число); summary и plan_hash — по всему плану. */
  items: PortSyncPlanItem[]
  summary: PortSyncSummary
  plan_hash: string
  /** Может отсутствовать в ответах старого сервера (тогда план пришёл целиком, не более 300 элементов). */
  page?: PortSyncPlanPage
}

export interface PortSyncApplyResult {
  applied: { ports: number; connections: number }
  connection_ids: string[]
  summary: PortSyncSummary
}

/** Счётчики журнала по ВСЕМУ журналу — не зависят от поиска и фильтров. by_action: число записей
 * по каждому действию (CREATE, UPDATE, DELETE, SYNC, LOGIN…); действия без записей отсутствуют. */
export interface AuditLogSummary {
  total: number
  by_action: Record<string, number>
}

/** GET /api/v1/audit-log — страница журнала: поиск, фильтры и порядок «новые сверху» считает
 * сервер. total — под теми же условиями, что и items; summary и entity_types — по всему журналу
 * (entity_types — разделы, реально встречающиеся в журнале, для фильтра «Раздел»). */
export interface AuditLogPage {
  items: AuditLogEntry[]
  total: number
  offset: number
  limit: number
  summary: AuditLogSummary
  entity_types: string[]
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
  /** IP-адреса ИС — как в столбце «IP-адреса» отчёта: ручные источники и связанные ВМ (у ВМ с префиксом).
   * Есть в ответе списка и /resources (обогащение, см. services/serialization.py), в ответах на создание/правку — нет. */
  ip_addresses?: string[]
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
