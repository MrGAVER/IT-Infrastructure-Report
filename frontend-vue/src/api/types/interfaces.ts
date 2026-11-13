// Порты, подинтерфейсы и группы портов устройства. Часть типов API, см. ./index.ts.

import type { CatalogItem } from './catalogs'
import type { VlanMode } from './connections'
import type { OpenPortDraftRow } from './workloads'

/** GET /api/v1/resources/interfaces?physical_device_id=... — физический/логический порт
 * устройства (Лист 3 отчёта). Persist идёт НЕ через обычный CRUD /resources/interfaces, а через
 * атомарный PUT /api/v1/devices/{device_id}/interfaces (см. backend/app/services/crud/interfaces.py:
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
 * устройству VLAN — то же множество, которое backend/app/services/crud/interfaces.py:sync_interfaces
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
 * vlan_mode !== '' — режим порта и VLAN; ips с непустым адресом — общие IP (один или несколько
 * адресов, у каждого префикс и назначение; на все порты группы записывается ПОЛНЫЙ список); manage_open_ports —
 * полный список открытых портов. Незаданные параметры порты хранят свои. */
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
  /** Общие IP-адреса группы: адрес, префикс и назначение каждого (как «IP-адреса интерфейса» порта). Строка без адреса
   * — пустой плейсхолдер формы: не хранится и не задаёт управление IP. Не повторяются в пределах группы. */
  ips: InterfaceIpDraftRow[]
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
  ips: { id: string; ip_address: string; prefix_length: number | null; purpose: string | null }[]
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
