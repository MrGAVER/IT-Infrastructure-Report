// Настройки плановых копий SQLite — GET/PUT /api/v1/backup/settings (backend/app/api/backup_settings.py). Роль проверяет сервер:
// администратору — чтение и запись, viewer — 403 на оба (при включённой аутентификации).
import { api } from './client'
import type { BackupSettings, BackupSettingsUpdate } from './types'

export function fetchBackupSettings() {
  return api.get<BackupSettings>('/backup/settings')
}

/** Поле не передано — не меняется, null — сбросить к значению по умолчанию. Параметр, заданный окружением, сервер отклоняет (409). */
export function saveBackupSettings(patch: BackupSettingsUpdate) {
  return api.put<BackupSettings>('/backup/settings', patch)
}
