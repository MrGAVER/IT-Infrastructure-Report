// Каскадная смена режима порта (access/trunk) — см. backend/app/services/vlan_mode_cascade.py.
// Двухшаговый протокол: preview возвращает план (что изменится, какие VLAN снимутся, предупреждения)
// и его hash; apply принимает тот же hash и confirm=true — если данные изменились между шагами,
// сервер отвечает 409 вместо того, чтобы выполнить не показанный пользователю план.
import { api } from './client'
import type { DeviceInterface } from './types'

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
}

/** Состояние устройства с открытой формой: режимы его портов и групп В ЧЕРНОВИКЕ (id -> режим; у
 * группы пустая строка — группа режимом не управляет). Сервер считает по нему область изменения: порт,
 * у которого в форме уже целевой режим, менять не нужно, даже если в БД режим другой. Порты и группы
 * этого устройства сервер не пишет — они сохранятся вместе с формой. */
export interface EditedDeviceState {
  device_id: string
  ports: Record<string, VlanMode>
  groups: Record<string, VlanMode | ''>
}

// POST, а не GET: состояние формы (десятки портов) не помещается в query.
export function previewVlanModeCascade(interfaceId: string, mode: VlanMode, edited: EditedDeviceState | null) {
  return api.post<VlanModeCascadePlan>(`/interfaces/${encodeURIComponent(interfaceId)}/vlan-mode-cascade/preview`, { mode, edited })
}

/** edited — то же состояние формы, что при предпросмотре: иначе сервер посчитает другой план и ответит 409. */
export function applyVlanModeCascade(interfaceId: string, plan: VlanModeCascadePlan, edited: EditedDeviceState | null) {
  return api.post<VlanModeCascadeResult>(`/interfaces/${encodeURIComponent(interfaceId)}/vlan-mode-cascade`, {
    mode: plan.target_mode,
    edited,
    plan_hash: plan.hash,
    confirm: true,
  })
}
