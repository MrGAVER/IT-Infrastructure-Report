// Журнал аудита. Часть типов API, см. ./index.ts.

/** Запись журнала аудита (GET /api/v1/audit-log). Автор действия — actor_*: имя пользователя известно,
 * только если аутентификация была включена; адрес клиента — всегда, кроме записей, сделанных до
 * появления этих полей (у них все три равны null). */
export interface AuditLogEntry {
  id: string
  entity_type: string
  entity_id: string
  action: 'CREATE' | 'UPDATE' | 'DELETE' | 'SYNC' | string
  details: string | null
  created_at: string
  actor_id: string | null
  actor_username: string | null
  actor_ip: string | null
}

/** Счётчики журнала по ВСЕМУ журналу — не зависят от поиска и фильтров. by_action: число записей
 * по каждому действию (CREATE, UPDATE, DELETE, SYNC, LOGIN…); действия без записей отсутствуют. */
export interface AuditLogSummary {
  total: number
  by_action: Record<string, number>
}

/** GET /api/v1/audit-log — страница журнала: поиск, фильтры и порядок «новые сверху» считает
 * сервер. total — под теми же условиями, что и items; summary и entity_types — по всему журналу
 * (entity_types — разделы, реально встречающиеся в журнале, для фильтра «Раздел»). */
export interface AuditLogPage {
  items: AuditLogEntry[]
  total: number
  offset: number
  limit: number
  summary: AuditLogSummary
  entity_types: string[]
}

/** GET /api/v1/audit-log/settings — настройки аудита (backend/app/services/audit_retention.py). Доступны только
 * администратору (при выключенной аутентификации — всем, как и сам журнал).
 * retention_days — действующий срок хранения записей в днях, 0 — не удалять; is_default — срок не задан в форме и
 * действует значение по умолчанию сервера (default_retention_days); max_retention_days — верхняя граница, которую
 * принимает сервер; last_cleanup_at — когда очистка по сроку последний раз дошла до конца (UTC, ISO) или null. */
export interface AuditSettings {
  retention_days: number
  is_default: boolean
  default_retention_days: number
  max_retention_days: number
  last_cleanup_at: string | null
}

/** Ответ PUT /api/v1/audit-log/settings: настройки после сохранения + итог немедленной очистки по новому сроку.
 * removed_now — сколько записей удалено сразу; cleanup_failed — срок сохранён, но очистка не удалась (повторится). */
export interface AuditSettingsSaveResult extends AuditSettings {
  removed_now: number
  cleanup_failed: boolean
}
