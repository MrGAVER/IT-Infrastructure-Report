// Заглушка сервера настроек плановых копий (GET/PUT /api/v1/backup/settings) для тестов панели и стора. Повторяет форму ответов
// backend/app/api/backup_settings.py: PUT возвращает настройки после сохранения; параметр, заданный окружением, — 409.
import { vi } from 'vitest'
import type { BackupSettings, BackupSettingsUpdate } from '../../api/types'

export const BASE_BACKUP_SETTINGS: BackupSettings = {
  supported: true,
  unsupported_reason: null,
  interval_hours: 24,
  interval_source: 'default',
  keep: 7,
  keep_source: 'default',
  default_interval_hours: 24,
  default_keep: 7,
  min_interval_hours: 1,
  max_interval_hours: 8784,
  max_keep: 365,
  directory: '/data/backups',
  directory_source: 'default',
  running: true,
  latest: null,
  last_attempt: null,
}

export interface BackupSettingsApiOptions {
  /** Статус GET: не 200 — ответ с { detail }. */
  loadStatus?: number
  /** Статус PUT: не 200 — ответ с { detail }, настройки не меняются. */
  saveStatus?: number
  /** Ответы на прочие адреса (по умолчанию — пустой объект), например GET /auth/users в SettingsView. */
  fallback?: (url: string, init?: RequestInit) => Response
}

export function stubBackupSettingsApi(initial: Partial<BackupSettings> = {}, options: BackupSettingsApiOptions = {}) {
  let settings: BackupSettings = { ...BASE_BACKUP_SETTINGS, ...initial }
  const puts: BackupSettingsUpdate[] = []
  const requests: string[] = []
  const detail = (status: number) =>
    new Response(JSON.stringify({ detail: status === 403 ? 'Настройки резервных копий доступны только администратору.' : 'Сервер недоступен' }), {
      status,
    })

  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      requests.push(`${method} ${url}`)
      if (!url.includes('/backup/settings')) return options.fallback?.(url, init) ?? new Response(JSON.stringify([]))
      if (method === 'GET') {
        return options.loadStatus && options.loadStatus !== 200 ? detail(options.loadStatus) : new Response(JSON.stringify(settings))
      }
      if (options.saveStatus && options.saveStatus !== 200) return detail(options.saveStatus)
      const body = JSON.parse(String(init?.body)) as BackupSettingsUpdate
      puts.push(body)
      if (body.interval_hours !== undefined) {
        const hours = body.interval_hours // null — сбросить к умолчанию
        settings = {
          ...settings,
          interval_hours: hours ?? settings.default_interval_hours,
          interval_source: hours === null ? 'default' : 'settings',
        }
      }
      if (body.keep !== undefined) {
        const keep = body.keep
        settings = { ...settings, keep: keep ?? settings.default_keep, keep_source: keep === null ? 'default' : 'settings' }
      }
      return new Response(JSON.stringify(settings))
    }),
  )
  return { puts, requests, current: () => settings }
}
