/** Откуда взято действующее значение параметра плановых копий: environment — переменная окружения или infra_registry.toml (в форме не
 * меняется), settings — задано в «Настройки → Резервные копии», default — значение по умолчанию. */
export type BackupSource = 'environment' | 'settings' | 'default'

/** Последняя плановая копия в каталоге копий: имя файла, размер в байтах, момент создания (UTC, ISO). */
export interface BackupLatest {
  name: string
  size_bytes: number
  created_at: string
}

/** Итог последней попытки планировщика с запуска приложения (после перезапуска приложения — null). created — имя новой копии; null без
 * ошибки — копия не понадобилась (база не менялась с прошлой). */
export interface BackupAttempt {
  at: string
  ok: boolean
  created: string | null
  error: string | null
}

/** GET/PUT /api/v1/backup/settings — настройки плановых копий SQLite (backend/app/api/backup_settings.py, схема BackupSettingsOut).
 * Только администратору (при выключенной аутентификации — всем). supported=false — копии средствами приложения не делаются (PostgreSQL):
 * остальные поля справочные. interval_hours: 0 — копии выключены; min_interval_hours — наименьший интервал, который принимает форма
 * (чаще — только переменной окружения). directory меняется только окружением и в форме показывается. running — планировщик работает. */
export interface BackupSettings {
  supported: boolean
  unsupported_reason: string | null
  interval_hours: number
  interval_source: BackupSource
  keep: number
  keep_source: BackupSource
  default_interval_hours: number
  default_keep: number
  min_interval_hours: number
  max_interval_hours: number
  max_keep: number
  directory: string
  directory_source: 'environment' | 'default'
  running: boolean
  latest: BackupLatest | null
  last_attempt: BackupAttempt | null
}

/** Тело PUT /api/v1/backup/settings: поле не передано — не меняется, null — сбросить к умолчанию. */
export interface BackupSettingsUpdate {
  interval_hours?: number | null
  keep?: number | null
}
