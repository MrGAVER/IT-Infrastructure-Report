// Стеки устройств и общие VLAN стека. Часть типов API, см. ./index.ts.

import type { Connection } from './connections'
import type { Device } from './devices'

/** Пункт 5 правки "создание физического устройства": стек физических устройств. CRUD — через
 * generic /resources/device-stacks, членство — через /resources/device-stack-members (не путать
 * с добавлением участника — POST /device-stacks/{id}/members ниже, идемпотентный и с понятной
 * 409, если устройство уже в другом стеке, см. backend/app/api/device_stacks.py). */
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

/** GET /api/v1/device-stacks/{id}/detail (backend/app/api/device_stacks.py:device_stack_detail) —
 * "просмотр... вместе": участники — Device (см. enrich_devices) плюс два поля из членства, и
 * связывающие подключения — та же форма, что Connection (./connections.ts, см. enrich_connections),
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
