// Физические устройства и сводка дашборда. Часть типов API, см. ./index.ts.

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
