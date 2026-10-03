// Страница журнала аудита — GET /api/v1/audit-log (backend/app/api/audit_log.py).
import { api } from './client'
import type { AuditLogPage } from './types'

export interface AuditLogPageParams {
  q?: string
  action?: string
  entity_type?: string
  offset: number
  limit: number
}

export function fetchAuditLogPage(params: AuditLogPageParams) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.action) qs.set('action', params.action)
  if (params.entity_type) qs.set('entity_type', params.entity_type)
  qs.set('offset', String(params.offset))
  qs.set('limit', String(params.limit))
  return api.get<AuditLogPage>(`/audit-log?${qs.toString()}`)
}
