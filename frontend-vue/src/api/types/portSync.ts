// Правила автоматического согласования данных порта. Часть типов API, см. ./index.ts.

import type { PortRole, VlanMode } from './connections'

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
