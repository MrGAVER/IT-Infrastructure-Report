// Правила автоматического согласования данных порта и согласование по ним — /api/v1/port-sync
// (backend/app/api/port_sync.py).
import { api } from './client'
import type { PortSyncApplyResult, PortSyncPlan, PortSyncRule, PortSyncRuleInput } from './types'

export function fetchPortSyncRules() {
  return api.get<{ items: PortSyncRule[]; total: number }>('/port-sync/rules')
}

export function createPortSyncRule(input: PortSyncRuleInput) {
  return api.post<PortSyncRule>('/port-sync/rules', input)
}

/** Частичное обновление: переданные поля заменяют текущие (так работает и переключатель «включено»). */
export function updatePortSyncRule(id: string, patch: Partial<PortSyncRuleInput>) {
  return api.put<PortSyncRule>(`/port-sync/rules/${id}`, patch)
}

export function deletePortSyncRule(id: string) {
  return api.delete<null>(`/port-sync/rules/${id}`)
}

export function resetPortSyncRule(id: string) {
  return api.post<PortSyncRule>(`/port-sync/rules/${id}/reset`, {})
}

/** ids — ВСЕ правила в нужном порядке проверки. */
export function reorderPortSyncRules(ids: string[]) {
  return api.post<{ items: PortSyncRule[]; total: number }>('/port-sync/rules/reorder', { ids })
}

export interface PortSyncScope {
  /** Без списка — все активные подключения с неодобренным расхождением. */
  connection_ids?: string[]
  /** Проверить только это правило (даже отключённое). */
  rule_id?: string
}

/** План согласования — ничего не записывает. */
export function previewPortSync(scope: PortSyncScope = {}) {
  return api.post<PortSyncPlan>('/port-sync/preview', scope)
}

/** Применяет план; plan_hash — из предпросмотра, иначе сервер ответит 409. */
export function applyPortSync(scope: PortSyncScope, planHash: string) {
  return api.post<PortSyncApplyResult>('/port-sync/apply', { ...scope, plan_hash: planHash, confirm: true })
}
