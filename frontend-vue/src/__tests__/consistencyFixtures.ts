// Общие данные для тестов «Проверки данных»: находка с разумными значениями по умолчанию и отчёт сервера вокруг списка находок.
import type { ConsistencyApproval, ConsistencyFinding, ConsistencyReport, ConsistencyRule, ReportReadiness, SheetReadiness } from '../api/consistency'

let counter = 0

/** Отпечатки у находок разные (по ним экран находит строку при одобрении): 64 hex-символа, как у сервера. */
export function finding(patch: Partial<ConsistencyFinding> = {}): ConsistencyFinding {
  counter += 1
  return {
    fingerprint: counter.toString(16).padStart(64, '0'),
    approved: false,
    approval: null,
    rule: 'duplicate_ip',
    severity: 'warning',
    category: 'consistency',
    sheet: null,
    entity_type: 'ip_address',
    entity_id: '10.0.0.5',
    entity_name: '10.0.0.5',
    message: 'IP-адрес 10.0.0.5 назначен разным объектам: srv-1, srv-2.',
    details: {},
    ...patch,
  }
}

export function approvalOf(patch: Partial<ConsistencyApproval> = {}): ConsistencyApproval {
  return { id: 'appr-1', comment: null, approved_by: 'anna', approved_at: '2026-11-23T10:00:00', ...patch }
}

/** Находка, уже одобренная человеком. */
export function approvedFinding(patch: Partial<ConsistencyFinding> = {}, approval: Partial<ConsistencyApproval> = {}): ConsistencyFinding {
  return finding({ approved: true, approval: approvalOf(approval), ...patch })
}

export function reportOf(findings: ConsistencyFinding[], patch: Partial<ConsistencyReport> = {}): ConsistencyReport {
  const by_severity: ConsistencyReport['summary']['by_severity'] = {}
  for (const item of findings) by_severity[item.severity] = (by_severity[item.severity] ?? 0) + 1
  const approved = findings.filter((item) => item.approved).length
  return {
    ok: findings.every((item) => item.approved),
    total: findings.length,
    returned: findings.length,
    truncated: false,
    summary: { by_severity, by_category: {}, by_sheet: {}, by_rule: {}, by_approval: { active: findings.length - approved, approved } },
    findings,
    ...patch,
  }
}

export const RULES: ConsistencyRule[] = [
  { code: 'duplicate_ip', title: 'Один IP-адрес у разных объектов', severity: 'warning', category: 'consistency', sheet: null },
  { code: 'vm_without_host', title: 'Виртуальная машина не привязана к устройству', severity: 'warning', category: 'completeness', sheet: 4 },
]

/** Строка блока «Готовность отчёта»: проверенный лист с 3 готовыми объектами из 4 и одной проблемой. */
export function sheetReadiness(patch: Partial<SheetReadiness> = {}): SheetReadiness {
  return {
    sheet: 2,
    title: 'Физические устройства',
    total: 4,
    checked: true,
    affected: 1,
    ready: 3,
    percent: 75,
    problems: 1,
    approved: 0,
    top_rules: [],
    ...patch,
  }
}

export function readinessOf(sheets: SheetReadiness[], unassigned = 0): ReportReadiness {
  return { sheets, unassigned }
}

/** Четыре листа отчёта в состоянии «почти готово»; лист 3, как на сервере, не проверяется. */
export const READINESS: ReportReadiness = readinessOf(
  [
    sheetReadiness({ sheet: 1, title: 'Информационные системы', total: 12, affected: 3, ready: 9, percent: 75, problems: 5 }),
    sheetReadiness({
      sheet: 2,
      total: 34,
      affected: 2,
      ready: 32,
      percent: 94,
      problems: 3,
      top_rules: [{ rule: 'device_location_incomplete', title: 'У устройства не указано здание или помещение', count: 2 }],
    }),
    sheetReadiness({ sheet: 3, title: 'Подключения', total: 91, checked: false, affected: null, ready: null, percent: null, problems: 0 }),
    sheetReadiness({ sheet: 4, title: 'Виртуальные машины и контейнеры', total: 134, affected: 0, ready: 134, percent: 100, problems: 0 }),
  ],
  2,
)
