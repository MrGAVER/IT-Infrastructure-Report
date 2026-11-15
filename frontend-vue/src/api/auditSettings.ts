// Настройки аудита — GET/PUT /api/v1/audit-log/settings (backend/app/api/audit_log.py). Роль проверяет сервер:
// администратору — чтение и запись, viewer — 403 на оба (при включённой аутентификации).
import { api } from './client'
import type { AuditSettings, AuditSettingsSaveResult } from './types'

export function fetchAuditSettings() {
  return api.get<AuditSettings>('/audit-log/settings')
}

/** retentionDays: 0 — не удалять; null — сбросить к значению по умолчанию. Сервер сразу очищает журнал по новому сроку. */
export function saveAuditSettings(retentionDays: number | null) {
  return api.put<AuditSettingsSaveResult>('/audit-log/settings', { retention_days: retentionDays })
}
