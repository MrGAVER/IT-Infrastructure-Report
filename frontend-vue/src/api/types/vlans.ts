// VLAN, VLAN-домены и их привязки. Часть типов API, см. ./index.ts.

/** GET /api/v1/resources/device-type-vlans?device_type_id=... — какие определения VLAN
 * разрешены для типа устройства. Бэкенд использует то же самое множество (объединённое с уже
 * назначенными устройству VLAN, PhysicalDeviceVLAN) как allowed_vlans при валидации vlan_ids
 * интерфейса — см. sync_interfaces в backend/app/services/crud/interfaces.py и api/portVlans.ts. */
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

/** GET /api/v1/vlan-dashboard — сгруппировано по vlan_id, т.к. один и тот же VLAN ID
 * может иметь разные определения в разных доменах (см. backend/app/api/vlan.py:
 * vlan_dashboard). Формат ответа специфичный, четвёртый вариант в этом API. */
export interface VLANDeviceAssignment {
  device_id: string
  device_name: string
  ip_address: string | null
  is_management: boolean
}

/** GET /api/v1/resources/vlan-domains — CRUD через generic /resources/vlan-domains, участники —
 * VLANDomainDeviceLink (см. ниже), синхронизация — POST /api/v1/vlan-domains/{id}/sync
 * (backend/app/api/vlan.py:sync_vlan_domain), копирует VLAN устройства source_device_id на
 * всех остальных участников домена. source_device_id опционален: без него синхронизация
 * недоступна (кнопка скрыта в VLANDomainsPanel.vue, как и в vanilla-версии до 2.60.0, где в рендере
 * списка ресурсов кнопка «Синхронизировать» показывается только при x.source_device_id). */
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
 * (saveDeviceVlans в vanilla-версии до 2.60.0). */
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

export interface VLANDashboardResponse {
  items: VLANDashboardGroup[]
}
