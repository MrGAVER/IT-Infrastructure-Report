// Проверки согласованности и полноты данных — GET /api/v1/integrity/consistency (backend/app/services/consistency/engine.py: run_checks).
// Находка — либо противоречие между записями реестра (category=consistency), либо пробел, из-за которого лист отчёта будет неполным
// (category=completeness, sheet — номер листа 1–4). Проверки только читают: исправляет данные человек в нужном разделе.
import type { RouteLocationRaw } from 'vue-router'
import { api } from './client'

export type FindingSeverity = 'error' | 'warning' | 'info'
export type FindingCategory = 'consistency' | 'completeness'

/** Одобрение: человек признал проблему допустимой. Теряет силу, когда проблема меняется (меняется её отпечаток). */
export interface ConsistencyApproval {
  id: string
  comment: string | null
  /** Логин одобрившего; null — аутентификация была выключена. */
  approved_by: string | null
  /** Момент одобрения (UTC без пояса, как все даты сервера) — для formatServerDateTime. */
  approved_at: string
}

export interface ConsistencyFinding {
  /** Отпечаток состояния проблемы (64 hex): по нему сервер находит проблему при одобрении. */
  fingerprint: string
  approved: boolean
  approval: ConsistencyApproval | null
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
  /** Считается по выбору ДО отбора по одобрению: оба числа видны при любом фильтре. */
  by_approval: { active: number; approved: number }
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

/** Одобрить проблему: сервер сам находит её по отпечатку (404 — проблема исчезла или изменилась). Повтор безопасен. */
export function approveFinding(fingerprint: string, comment: string | null): Promise<{ created: boolean; approval: ConsistencyApproval }> {
  return api.post('/integrity/consistency/approvals', { fingerprint, comment })
}

/** Отозвать одобрение: проблема снова требует внимания. */
export function revokeApproval(approvalId: string): Promise<void> {
  return api.delete<void>(`/integrity/consistency/approvals/${encodeURIComponent(approvalId)}`)
}

/** Предел комментария к одобрению — как на сервере (services/consistency/approvals.py: MAX_COMMENT_LENGTH). */
export const MAX_APPROVAL_COMMENT_LENGTH = 1000

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

/** Типы объектов, у которых есть окно редактирования (устройство, ВМ, контейнер, ИС). */
export type EditableEntityType = 'physical_device' | 'virtual_machine' | 'container' | 'information_system'

const EDITABLE_TYPES: readonly string[] = ['physical_device', 'virtual_machine', 'container', 'information_system']

export function isEditableEntity(entityType: string): entityType is EditableEntityType {
  return EDITABLE_TYPES.includes(entityType)
}

/** Объект проблемы, на который можно нажать: имя для показа и (тип, id) для открытия окна редактирования. */
export interface EntityTarget {
  type: string
  id: string
  name: string
}

/**
 * Объекты находки. Обычно это сам объект (`entity_*`); у находок про повтор адреса и системного имени «объект» — это IP или имя,
 * а проблемные объекты лежат в details (holders / devices) — их и показываем, каждый открывается отдельно.
 */
export function findingTargets(finding: ConsistencyFinding): EntityTarget[] {
  const nested = finding.details.holders ?? finding.details.devices
  if (Array.isArray(nested)) {
    return nested
      .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null && typeof item.entity_id === 'string')
      .map((item) => ({
        // У списка devices (одно системное имя у разных устройств) тип не указан: там всегда устройства.
        type: typeof item.entity_type === 'string' ? item.entity_type : 'physical_device',
        id: item.entity_id as string,
        name: typeof item.name === 'string' ? item.name : (item.entity_id as string),
      }))
  }
  return [{ type: finding.entity_type, id: finding.entity_id, name: finding.entity_name }]
}
