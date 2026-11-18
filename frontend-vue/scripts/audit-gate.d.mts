export type Severity = 'info' | 'low' | 'moderate' | 'high' | 'critical'

export interface AllowRule {
  id: string
  package: string
  reason: string
  /** Последний день действия включительно, YYYY-MM-DD. */
  expires: string
}

export interface Advisory {
  id: string
  package: string
  severity: Severity
  title: string
  url?: string
  rule?: AllowRule
}

export interface AuditReport {
  vulnerabilities?: Record<string, { via?: Array<string | { source?: number; name: string; severity: Severity; title: string; url?: string }> }>
  error?: unknown
}

export interface AuditOutcome {
  failing: Advisory[]
  allowed: Advisory[]
  expired: Advisory[]
  unused: AllowRule[]
}

export const SEVERITY_RANK: Record<Severity, number>
export const ALLOWLIST: readonly AllowRule[]
export function advisoryId(via: { source?: number; url?: string }): string
export function collectAdvisories(report: AuditReport): Advisory[]
export function evaluateAudit(report: AuditReport, options?: { allowlist?: readonly AllowRule[]; level?: Severity; now?: Date }): AuditOutcome
