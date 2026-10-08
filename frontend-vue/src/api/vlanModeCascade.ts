// Каскадная смена режима порта (access/trunk) — см. backend/app/services/vlan_mode_cascade.py.
// Двухшаговый протокол: preview возвращает план (что изменится, какие VLAN снимутся, предупреждения)
// и его hash; apply принимает тот же hash и confirm=true — если данные изменились между шагами,
// сервер отвечает 409 вместо того, чтобы выполнить не показанный пользователю план.
import { api } from './client'
import type { DeviceInterface, PortRole } from './types'

export type VlanMode = 'access' | 'trunk'

export interface CascadeVlanRef {
  /** id записи VLAN (vlans.id), а не номер. */
  id: string
  /** Номер VLAN (VLAN ID) для показа пользователю. */
  vlan_id: number | null
  name: string
}

interface CascadeChange {
  id: string
  name: string
  device_id: string
  device_name: string
  /** Устройство с открытой формой: сервер его не пишет, изменения вносятся в черновик формы. */
  deferred: boolean
  from_mode: VlanMode
  to_mode: VlanMode
  vlans_before: CascadeVlanRef[]
  vlans_after: CascadeVlanRef[]
  dropped_vlans: CascadeVlanRef[]
}

/** Группа портов: режим меняется у всех её портов сразу. */
export interface CascadeGroupChange extends CascadeChange {
  ports: { id: string; name: string }[]
}

/** Порт вне меняемых групп (в группе без режима, без группы). */
export type CascadePortChange = CascadeChange

export interface CascadeDevice {
  id: string
  name: string
  deferred: boolean
  port_count: number
  group_count: number
}

export interface CascadeWarning {
  /** immediate | deferred | groups | cascade | vlans_dropped | trunk | inactive | large */
  code: string
  severity: 'info' | 'warning'
  text: string
}

export interface VlanModeCascadePlan {
  target_mode: VlanMode
  start_interface_id: string
  edited_device_id: string | null
  /** Менять нечего: режим уже совпадает. */
  empty: boolean
  groups: CascadeGroupChange[]
  ports: CascadePortChange[]
  devices: CascadeDevice[]
  totals: {
    ports: number
    devices: number
    groups: number
    deferred_ports: number
    immediate_ports: number
    immediate_devices: number
    dropped_vlans: number
  }
  warnings: CascadeWarning[]
  hash: string
}

export interface VlanModeCascadeResult {
  plan: VlanModeCascadePlan
  applied: { ports: number; groups: number; devices: number }
  /** Записанные сервером порты — в виде каталога 'interfaces' (для обновления кэша). */
  interfaces: DeviceInterface[]
  /** Роль и/или набор VLAN порта-инициатора из запроса (`port`) записаны вместе с каскадом. */
  port_written?: boolean
}

/** Роль и ПОЛНЫЙ набор VLAN (id записей справочника) порта-инициатора, которые сервер запишет в той же
 * транзакции, что и каскад (backend/app/services/port_edit.py). Проверяются под целевой режим уже при
 * предпросмотре. Не сочетается с `edited` (форма устройства открыта). */
export interface CascadePortRequest {
  role?: PortRole
  vlan_ids?: string[]
}

/** Порт устройства с открытой формой — как он выглядит в ЧЕРНОВИКЕ. */
export interface EditedPortState {
  name: string
  mode: VlanMode
  /** Ключ группы формы (id сохранённой группы или временный ключ новой); null — порт вне групп. */
  group: string | null
  vlan_ids: string[]
}

/** Группа устройства с открытой формой — как она выглядит в ЧЕРНОВИКЕ (в т.ч. новая, ещё не сохранённая). */
export interface EditedGroupState {
  name: string
  /** Пустая строка — группа режимом не управляет. */
  mode: VlanMode | ''
  vlan_ids: string[]
}

/** Состояние устройства с открытой формой: порты и группы В ЧЕРНОВИКЕ. Сервер считает по нему область
 * изменения: режим, состав групп и VLAN берутся из формы, а не из БД — порт, у которого в форме уже
 * целевой режим, менять не нужно, а порт, перенесённый в форме в другую группу, меняется вместе с ней.
 * Порты и группы этого устройства сервер не пишет — они сохранятся вместе с формой. */
export interface EditedDeviceState {
  device_id: string
  /** Сохранённые порты формы (у новых строк нет id — в БД их нет, и в области изменения они быть не могут). */
  ports: Record<string, EditedPortState>
  /** Группы формы по ключу (у сохранённой группы ключ равен id). */
  groups: Record<string, EditedGroupState>
}

// POST, а не GET: состояние формы (десятки портов) не помещается в query.
// port — роль и VLAN порта-инициатора (необязательно): сервер проверит их под целевой режим уже здесь.
export function previewVlanModeCascade(interfaceId: string, mode: VlanMode, edited: EditedDeviceState | null, port?: CascadePortRequest | null) {
  return api.post<VlanModeCascadePlan>(`/interfaces/${encodeURIComponent(interfaceId)}/vlan-mode-cascade/preview`, { mode, edited, ...(port ? { port } : {}) })
}

/** edited и port — те же, что при предпросмотре: иначе сервер посчитает другой план и ответит 409 (edited) или
 * запишет не то, что проверялось (port). С port режим, роль и VLAN записываются одной транзакцией. */
export function applyVlanModeCascade(interfaceId: string, plan: VlanModeCascadePlan, edited: EditedDeviceState | null, port?: CascadePortRequest | null) {
  return api.post<VlanModeCascadeResult>(`/interfaces/${encodeURIComponent(interfaceId)}/vlan-mode-cascade`, {
    mode: plan.target_mode,
    edited,
    ...(port ? { port } : {}),
    plan_hash: plan.hash,
    confirm: true,
  })
}
