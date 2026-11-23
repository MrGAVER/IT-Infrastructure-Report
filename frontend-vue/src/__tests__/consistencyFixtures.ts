// Общие данные для тестов «Проверки данных»: находка с разумными значениями по умолчанию и отчёт сервера вокруг списка находок.
import type { ConsistencyFinding, ConsistencyReport, ConsistencyRule } from '../api/consistency'

export function finding(patch: Partial<ConsistencyFinding> = {}): ConsistencyFinding {
  return {
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

export function reportOf(findings: ConsistencyFinding[], patch: Partial<ConsistencyReport> = {}): ConsistencyReport {
  const by_severity: ConsistencyReport['summary']['by_severity'] = {}
  for (const item of findings) by_severity[item.severity] = (by_severity[item.severity] ?? 0) + 1
  return {
    ok: findings.length === 0,
    total: findings.length,
    returned: findings.length,
    truncated: false,
    summary: { by_severity, by_category: {}, by_sheet: {}, by_rule: {} },
    findings,
    ...patch,
  }
}

export const RULES: ConsistencyRule[] = [
  { code: 'duplicate_ip', title: 'Один IP-адрес у разных объектов', severity: 'warning', category: 'consistency', sheet: null },
  { code: 'vm_without_host', title: 'Виртуальная машина не привязана к устройству', severity: 'warning', category: 'completeness', sheet: 4 },
]
