// Правила автоматического согласования данных порта и согласование по ним — /api/v1/port-sync
// (backend/app/api/port_sync.py).
import { api, LONG_REQUEST_TIMEOUT_MS } from './client'

// Расчёт и применение плана по большому реестру — долгие операции: таймаут по умолчанию (30 с) для них мал.
const LONG_OPTIONS = { timeoutMs: LONG_REQUEST_TIMEOUT_MS }
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

/** Страница плана: offset/limit — какие элементы вернуть; planHash — хеш плана из ответа на первую страницу. */
export interface PortSyncPageRequest {
  offset?: number
  limit?: number
  planHash?: string
}

/**
 * План согласования — ничего не записывает. Без `page` — первая страница (сервер отдаёт до 300 элементов), и
 * считается план целиком. Следующие страницы запрашиваются с planHash первой: сервер берёт их из кэша без
 * пересчёта, а если кэша уже нет и план изменился, отвечает 409 — предпросмотр нужно начать заново.
 *
 * @example
 * const first = await previewPortSync(scope)
 * const next = await previewPortSync(scope, { offset: first.items.length, planHash: first.plan_hash })
 */
export function previewPortSync(scope: PortSyncScope = {}, page: PortSyncPageRequest = {}) {
  const { planHash, ...range } = page
  return api.post<PortSyncPlan>('/port-sync/preview', { ...scope, ...range, ...(planHash ? { plan_hash: planHash } : {}) }, LONG_OPTIONS)
}

/** Применяет план; plan_hash — из предпросмотра, иначе сервер ответит 409. */
export function applyPortSync(scope: PortSyncScope, planHash: string) {
  return api.post<PortSyncApplyResult>('/port-sync/apply', { ...scope, plan_hash: planHash, confirm: true }, LONG_OPTIONS)
}
