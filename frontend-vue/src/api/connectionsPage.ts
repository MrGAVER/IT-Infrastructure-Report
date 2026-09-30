// Страница подключений для дашборда — GET /api/v1/connections (backend/app/api/port_config.py).
import { api } from './client'
import type { ConnectionsPage, PortConfigStatus } from './types'

export interface ConnectionsPageParams {
  q?: string
  is_active?: boolean
  port_config_status?: PortConfigStatus
  offset: number
  limit: number
}

export function fetchConnectionsPage(params: ConnectionsPageParams) {
  const qs = new URLSearchParams()
  if (params.q) qs.set('q', params.q)
  if (params.is_active !== undefined) qs.set('is_active', String(params.is_active))
  if (params.port_config_status) qs.set('port_config_status', params.port_config_status)
  qs.set('offset', String(params.offset))
  qs.set('limit', String(params.limit))
  return api.get<ConnectionsPage>(`/connections?${qs.toString()}`)
}
