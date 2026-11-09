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
