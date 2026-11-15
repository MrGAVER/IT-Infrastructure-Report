// Заглушка сервера настроек аудита (GET/PUT /api/v1/audit-log/settings) для тестов формы, кнопок и стора.
// Повторяет форму настоящих ответов backend/app/api/audit_log.py: PUT возвращает настройки после сохранения + итог очистки.
import { vi } from 'vitest'
import type { AuditSettings } from '../../api/types'

export const BASE_AUDIT_SETTINGS: AuditSettings = {
  retention_days: 0,
  is_default: true,
  default_retention_days: 0,
  max_retention_days: 3650,
  last_cleanup_at: null,
}

export interface AuditSettingsApiOptions {
  /** Статус GET: не 200 — ответ с { detail }. */
  loadStatus?: number
  /** Статус PUT: не 200 — ответ с { detail }, настройки не меняются. */
  saveStatus?: number
  removedNow?: number
  cleanupFailed?: boolean
}

export function stubAuditSettingsApi(initial: Partial<AuditSettings> = {}, options: AuditSettingsApiOptions = {}) {
  let settings: AuditSettings = { ...BASE_AUDIT_SETTINGS, ...initial }
  const puts: Array<{ retention_days: number | null }> = []
  const requests: string[] = []
  const detail = (status: number) =>
    new Response(JSON.stringify({ detail: status === 403 ? 'Журнал аудита доступен только администратору.' : 'Сервер недоступен' }), { status })

  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      requests.push(`${method} ${url}`)
      if (!url.includes('/audit-log/settings')) return new Response(JSON.stringify({}))
      if (method === 'GET') {
        return options.loadStatus && options.loadStatus !== 200 ? detail(options.loadStatus) : new Response(JSON.stringify(settings))
      }
      if (options.saveStatus && options.saveStatus !== 200) return detail(options.saveStatus)
      const body = JSON.parse(String(init?.body)) as { retention_days: number | null }
      puts.push(body)
      settings =
        body.retention_days === null
          ? { ...settings, retention_days: settings.default_retention_days, is_default: true }
          : { ...settings, retention_days: body.retention_days, is_default: false }
      return new Response(JSON.stringify({ ...settings, removed_now: options.removedNow ?? 0, cleanup_failed: options.cleanupFailed ?? false }))
    }),
  )
  return { puts, requests, current: () => settings }
}
