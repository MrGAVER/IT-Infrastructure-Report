// Общие данные для тестов «Проверки данных»: находка с разумными значениями по умолчанию и отчёт сервера вокруг списка находок.
import type { ConsistencyApproval, ConsistencyFinding, ConsistencyReport, ConsistencyRule } from '../api/consistency'

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
