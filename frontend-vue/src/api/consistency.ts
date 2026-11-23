// Проверки согласованности и полноты данных — GET /api/v1/integrity/consistency (backend/app/services/consistency/engine.py: run_checks).
// Находка — либо противоречие между записями реестра (category=consistency), либо пробел, из-за которого лист отчёта будет неполным
// (category=completeness, sheet — номер листа 1–4). Проверки только читают: исправляет данные человек в нужном разделе.
import type { RouteLocationRaw } from 'vue-router'
import { api } from './client'

export type FindingSeverity = 'error' | 'warning' | 'info'
export type FindingCategory = 'consistency' | 'completeness'

export interface ConsistencyFinding {
  rule: string
  severity: FindingSeverity
  category: FindingCategory
  /** Лист отчёта (1–4) для проверок полноты; у противоречий без привязки к листу — null. */
  sheet: number | null
  /** Тип объекта (physical_device, virtual_machine, container, information_system, ip_address) — по нему строится ссылка на раздел. */
  entity_type: string
  entity_id: string
  entity_name: string
  message: string
  details: Record<string, unknown>
}

export interface ConsistencySummary {
  by_severity: Partial<Record<FindingSeverity, number>>
  by_category: Partial<Record<FindingCategory, number>>
  by_sheet: Record<string, number>
  by_rule: Record<string, number>
}

export interface ConsistencyReport {
  ok: boolean
  /** Число находок до разбиения на страницы. */
  total: number
  /** Сколько находок вернул сервер на этой странице. */
  returned: number
  /** Сервер вернул не все находки: их больше предела одного запроса. */
  truncated: boolean
  summary: ConsistencySummary
  findings: ConsistencyFinding[]
}

export interface ConsistencyRule {
  code: string
  title: string
  severity: FindingSeverity
  category: FindingCategory
  sheet: number | null
}

/** Предел сервера на одну страницу находок (backend/app/api/consistency.py: limit ≤ 5000). Экран читает всё одним запросом и
 * фильтрует у себя: фильтры мгновенные, а счётчики сверху не прыгают при выборе фильтра. */
export const CONSISTENCY_LIMIT = 5000

export function fetchConsistency(): Promise<ConsistencyReport> {
  return api.get<ConsistencyReport>(`/integrity/consistency?limit=${CONSISTENCY_LIMIT}`)
}

export function fetchConsistencyRules(): Promise<ConsistencyRule[]> {
  return api.get<{ rules: ConsistencyRule[] }>('/integrity/consistency/rules').then((body) => body.rules)
}

export const SEVERITY_LABELS: Record<FindingSeverity, string> = { error: 'Ошибка', warning: 'Предупреждение', info: 'Сведения' }
export const CATEGORY_LABELS: Record<FindingCategory, string> = { consistency: 'Противоречие', completeness: 'Пробел в данных' }
export const SHEET_LABELS: Record<number, string> = {
  1: 'Лист 1 — информационные системы',
  2: 'Лист 2 — физические устройства',
  3: 'Лист 3 — подключения',
  4: 'Лист 4 — виртуальные машины',
}

interface EntitySection {
  to: RouteLocationRaw
  label: string
}

const ENTITY_SECTIONS: Record<string, EntitySection> = {
  physical_device: { to: '/devices', label: 'Инвентаризация устройств' },
  virtual_machine: { to: '/vms', label: 'Виртуальные машины' },
  container: { to: '/containers', label: 'Контейнеры' },
  information_system: { to: '/information-systems', label: 'Информационные системы' },
}

/** Раздел, где исправляют объект находки; null — у объекта нет своего раздела (например, IP-адрес). */
export function entitySection(entityType: string): EntitySection | null {
  return ENTITY_SECTIONS[entityType] ?? null
}
