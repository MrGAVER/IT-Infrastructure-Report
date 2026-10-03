// Фикстуры скопированы по форме с реальных ответов локально поднятого бэкенда
// (см. отчёт о ручной проверке в сессии разработки) — не выдуманы вручную, чтобы
// тесты стора действительно защищали от расхождений с API, а не только с тем,
// что мы думаем, что API возвращает.
import type { PagedResponse } from '../../api/client'
import type { CatalogItem, Device, DevicesResponse, StructuralUnit } from '../../api/types'

export const structuralUnitsFixture: PagedResponse<StructuralUnit> = {
  items: [
    { id: 'root-1', name: 'Дирекция ИТ', parent_id: null },
    { id: 'child-1', name: 'Отдел эксплуатации', parent_id: 'root-1' },
    { id: 'root-2', name: 'Служба безопасности', parent_id: null },
  ],
  total: 3,
  offset: 0,
  limit: 1000,
}

export const buildingsFixture: PagedResponse<CatalogItem> = {
  items: [
    { id: 'b-main', name: 'Главный офис', address: 'Адрес организации', structural_unit_id: null },
    { id: 'b-a', name: 'Корпус А', address: 'ул. Тестовая, 1', structural_unit_id: 'child-1' },
    { id: 'b-b', name: 'Корпус Б', address: 'ул. Тестовая, 2', structural_unit_id: 'root-2' },
  ],
  total: 3,
  offset: 0,
  limit: 1000,
}

export const deviceTypesFixture: PagedResponse<CatalogItem> = {
  items: [
    { id: 'dt-server', name: 'Сервер' },
    { id: 'dt-net', name: 'Сетевое оборудование' },
  ],
  total: 2,
  offset: 0,
  limit: 1000,
}

function device(overrides: Partial<Device>): Device {
  return {
    id: 'id-' + Math.random().toString(36).slice(2),
    device_type_id: 'dt-server',
    manufacturer_id: null,
    model_id: null,
    serial_number: 'SN-0000',
    system_name: null,
    operating_system_id: null,
    embedded_os_id: null,
    siem_enabled: false,
    building_id: null,
    room_id: null,
    rack_id: null,
    rack_position: null,
    status: null,
    description: null,
    diagram_icon_id: null,
    oac_certificate_number: null,
    oac_certificate_registry_date: null,
    stack_id: null,
    stack_name: null,
    stack_position: null,
    management_interface: '',
    management_ips: '',
    interface_count: 0,
    embedded_os_name: '',
    embedded_os_version: '',
    vlan_summary: '',
    ...overrides,
  }
}

export const devicesFixture: DevicesResponse = {
  total: 3,
  items: [
    device({
      id: 'dev-1',
      serial_number: '7X2K9L3Q1',
      system_name: 'srv-db-01.corp.local',
      siem_enabled: true,
      building_id: 'b-a',
      management_ips: '10.10.1.15',
    }),
    device({
      id: 'dev-2',
      serial_number: 'HPE-88231LX',
      system_name: 'srv-app-02.corp.local',
      siem_enabled: true,
      building_id: 'b-a',
      management_ips: '10.10.1.16',
    }),
    device({
      id: 'dev-3',
      device_type_id: 'dt-net',
      serial_number: 'FCW2345X0Y1',
      system_name: 'sw-core-01',
      siem_enabled: false,
      building_id: 'b-b',
      management_ips: '10.10.0.1',
    }),
  ],
}

function informationSystem(overrides: Partial<import('../../api/types').InformationSystem>) {
  return {
    id: 'id-' + Math.random().toString(36).slice(2),
    number: null,
    name: 'ИС',
    type: 'ИС',
    description: null,
    purpose: null,
    localization: null,
    support_organization_id: null,
    support_method_id: null,
    process_description: null,
    siem_enabled: false,
    crypto_protection_enabled: false,
    crypto_protection_description_id: null,
    status: 'active',
    ...overrides,
  }
}

export const informationSystemsFixture: import('../../api/types').InformationSystem[] = [
  informationSystem({ id: 'is-1', name: 'Бухгалтерская система', purpose: 'Учёт', siem_enabled: true }),
  informationSystem({ id: 'is-2', name: 'CRM продаж', purpose: 'Работа с клиентами', siem_enabled: false }),
  informationSystem({ id: 'is-3', name: 'Портал СКЗИ', description: 'Криптозащита', crypto_protection_enabled: true, siem_enabled: true }),
]

export const vmsFixture: import('../../api/types').VMsResponse = {
  total: 2,
  items: [
    {
      id: 'vm-1', name: 'VM-DB-01', operating_system_id: null, physical_device_id: 'dev-1',
      hypervisor_os_id: null, purpose: 'База данных', status: 'active', description: null,
    },
    {
      id: 'vm-2', name: 'VM-APP-02', operating_system_id: null, physical_device_id: null,
      hypervisor_os_id: null, purpose: 'Приложение', status: 'active', description: null,
    },
  ],
}

function connection(overrides: Partial<import('../../api/types').Connection>): import('../../api/types').Connection {
  return {
    id: 'id-' + Math.random().toString(36).slice(2),
    source_interface_id: 'if-1',
    destination_interface_id: 'if-2',
    connection_type_id: 'ct-1',
    is_active: true,
    description: null,
    source_device_name: 'Устройство А',
    source_interface_name: 'eth0',
    destination_device_name: 'Устройство Б',
    destination_interface_name: 'Gi0/1',
    connection_type_name: 'Витая пара',
    source_port_role: 'data',
    destination_port_role: 'data',
    port_config_status: 'ok',
    source_vlan_mode: 'trunk', destination_vlan_mode: 'trunk', source_vlans: [], destination_vlans: [], port_config_diff: [],
    ...overrides,
  }
}

export const connectionsFixture: import('../../api/client').PagedResponse<import('../../api/types').Connection> = {
  items: [
    connection({ id: 'c-1', source_interface_id: 'if-1', destination_interface_id: 'if-2', is_active: true }),
    connection({
      id: 'c-2', source_interface_id: 'if-3', destination_interface_id: 'if-4',
      source_port_role: 'management', destination_port_role: 'data', // неактивное — в сверке не участвует (status ok)
      is_active: false, source_device_name: 'Коммутатор', destination_device_name: 'Файрвол',
    }),
  ],
  total: 2,
  offset: 0,
  limit: 1000,
}

/** Журнал из `count` записей, новые сверху: запись 0 — самая новая. Действие, раздел и текст
 * детерминированы: действие циклически CREATE/UPDATE/DELETE, каждая 4-я запись — раздел «vms». */
export function auditJournal(count: number): import('../../api/types').AuditLogEntry[] {
  const actions = ['CREATE', 'UPDATE', 'DELETE']
  return Array.from({ length: count }, (_, i) => ({
    id: `a-${i}`,
    entity_type: i % 4 === 0 ? 'vms' : 'devices',
    entity_id: `ent-${i}-xxxxxxxx`,
    action: actions[i % 3],
    details: `Запись ${i}`,
    created_at: new Date(Date.UTC(2026, 7, 1) + (count - i) * 60_000).toISOString(),
  }))
}

/** Эмулятор GET /api/v1/audit-log над данным журналом: поиск (подстрока без регистра в деталях
 * или id), фильтры по действию и разделу, offset/limit; summary и entity_types — по всему журналу.
 * Те же правила, что у backend/app/services/audit_query.py. */
export function auditServer(journal: import('../../api/types').AuditLogEntry[]) {
  return (url: string): import('../../api/types').AuditLogPage => {
    const p = new URL(url, 'http://x').searchParams
    const q = (p.get('q') ?? '').trim().toLowerCase()
    const matching = journal.filter(
      (e) =>
        (!q || [e.details, e.entity_id].some((v) => (v ?? '').toLowerCase().includes(q))) &&
        (!p.get('action') || e.action === p.get('action')) &&
        (!p.get('entity_type') || e.entity_type === p.get('entity_type')),
    )
    const offset = Number(p.get('offset') ?? 0)
    const limit = Number(p.get('limit') ?? 24)
    const by_action: Record<string, number> = {}
    for (const e of journal) by_action[e.action] = (by_action[e.action] ?? 0) + 1
    return {
      items: matching.slice(offset, offset + limit),
      total: matching.length,
      offset,
      limit,
      summary: { total: journal.length, by_action },
      entity_types: [...new Set(journal.map((e) => e.entity_type))].sort(),
    }
  }
}

export const vlanDashboardFixture: import('../../api/types').VLANDashboardResponse = {
  items: [
    {
      vlan_id: 10,
      definitions: [
        {
          id: 'vlan-1', vlan_id: 10, name: 'Данные', description: '', domain_id: null, domain_name: 'Локальный VLAN',
          devices: [{ device_id: 'dev-1', device_name: 'sw-core-01', ip_address: '10.10.10.1', is_management: true }],
        },
      ],
    },
    {
      vlan_id: 20,
      definitions: [
        { id: 'vlan-2', vlan_id: 20, name: 'Гости', description: '', domain_id: 'dom-1', domain_name: 'Домен А', devices: [] },
        { id: 'vlan-3', vlan_id: 20, name: 'Гостевой сегмент', description: '', domain_id: 'dom-2', domain_name: 'Домен Б', devices: [] },
      ],
    },
  ],
}

