// Фильтры экрана «Проверка данных»: чистые функции над списком находок (экран читает все находки одним запросом).
import type { ConsistencyFinding, FindingCategory, FindingSeverity } from '../api/consistency'

export interface ConsistencyFilters {
  search: string
  severity: 'all' | FindingSeverity
  category: '' | FindingCategory
  /** Номер листа отчёта; '' — любой. */
  sheet: '' | number
  /** Код правила; '' — любое. */
  rule: string
  /** active — требуют внимания (по умолчанию), approved — одобренные, all — все. */
  approval: 'active' | 'approved' | 'all'
}

export const DEFAULT_FILTERS: Readonly<ConsistencyFilters> = { search: '', severity: 'all', category: '', sheet: '', rule: '', approval: 'active' }

export function hasActiveFilters(filters: ConsistencyFilters): boolean {
  return (Object.keys(DEFAULT_FILTERS) as (keyof ConsistencyFilters)[]).some((key) => {
    const value = filters[key]
    return key === 'search' ? value.toString().trim() !== '' : value !== DEFAULT_FILTERS[key]
  })
}

/** Находки, подходящие под все фильтры сразу. Поиск — по имени объекта и тексту, без учёта регистра и пробелов по краям. */
export function filterFindings(findings: readonly ConsistencyFinding[], filters: ConsistencyFilters): ConsistencyFinding[] {
  const needle = filters.search.trim().toLowerCase()
  return findings.filter(
    (item) =>
      (filters.severity === 'all' || item.severity === filters.severity) &&
      (filters.category === '' || item.category === filters.category) &&
      (filters.sheet === '' || item.sheet === filters.sheet) &&
      (filters.rule === '' || item.rule === filters.rule) &&
      (filters.approval === 'all' || item.approved === (filters.approval === 'approved')) &&
      (needle === '' || item.entity_name.toLowerCase().includes(needle) || item.message.toLowerCase().includes(needle)),
  )
}

/** Номера листов, по которым есть находки, по возрастанию — для выбора «Лист». */
export function sheetsWithFindings(findings: readonly ConsistencyFinding[]): number[] {
  return [...new Set(findings.map((item) => item.sheet).filter((sheet): sheet is number => sheet !== null))].sort((a, b) => a - b)
}

/** Находки, которые требуют внимания (не одобрены), по важности — для счётчиков экрана. */
export function countActive(findings: readonly ConsistencyFinding[]): Record<FindingSeverity, number> & { total: number; approved: number } {
  const counts = { error: 0, warning: 0, info: 0, total: 0, approved: 0 }
  for (const item of findings) {
    if (item.approved) counts.approved += 1
    else {
      counts[item.severity] += 1
      counts.total += 1
    }
  }
  return counts
}

/**
 * Фильтры из параметров ссылки (`/consistency?sheet=2&category=completeness`): так блок «Готовность отчёта» ведёт на нужную выборку.
 * Принимаются только допустимые значения; лишнее и испорченное молча отбрасывается, чтобы ссылка с мусором открывала экран без фильтра,
 * а не пустой список.
 */
export function filtersFromQuery(query: Record<string, unknown>): Partial<ConsistencyFilters> {
  const first = (value: unknown): string => (Array.isArray(value) ? String(value[0] ?? '') : typeof value === 'string' ? value : '')
  const result: Partial<ConsistencyFilters> = {}
  const sheet = first(query.sheet)
  if (/^[1-4]$/.test(sheet)) result.sheet = Number(sheet)
  const category = first(query.category)
  if (category === 'consistency' || category === 'completeness') result.category = category
  const severity = first(query.severity)
  if (severity === 'error' || severity === 'warning' || severity === 'info') result.severity = severity
  const approval = first(query.approval)
  if (approval === 'active' || approval === 'approved' || approval === 'all') result.approval = approval
  const rule = first(query.rule)
  if (/^[a-z0-9_]{1,100}$/.test(rule)) result.rule = rule
  return result
}
