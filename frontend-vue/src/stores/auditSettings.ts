// Стор настроек аудита (форма «Настройки аудита», срок хранения журнала). Данные — с сервера
// (GET/PUT /api/v1/audit-log/settings), только для администратора: viewer получает 403, и форма даже не открывается
// (кнопки скрыты по auth.canViewAuditLog). Сохранение пессимистичное: срок меняет данные необратимо (старые записи
// удаляются), поэтому интерфейс показывает то, что подтвердил сервер, а не то, что пользователь ввёл.
import { defineStore } from 'pinia'
import { fetchAuditSettings, saveAuditSettings } from '../api/auditSettings'
import { ApiError } from '../api/client'
import type { AuditSettings, AuditSettingsSaveResult } from '../api/types'
import { createLatestRequest } from '../utils/latestRequest'

// Ответ на более ранний load() не должен затереть более поздний или уже подтверждённое сохранение (см. utils/latestRequest.ts).
const latest = createLatestRequest()

export const useAuditSettingsStore = defineStore('auditSettings', {
  state: () => ({
    settings: null as AuditSettings | null,
    loading: false,
    saving: false,
    error: null as string | null,
  }),
  actions: {
    /** Перечитывает настройки с сервера; при ошибке оставляет её текст в error (прежние настройки не затираются). */
    async load(): Promise<void> {
      await latest.run(this, {
        fetch: fetchAuditSettings,
        apply: (settings) => {
          this.settings = settings
        },
        errorMessage: (err) => (err instanceof ApiError ? err.message : 'Не удалось загрузить настройки аудита'),
      })
    },

    /** Сохраняет срок хранения (null — сбросить к умолчанию). Ошибку пробрасывает вызывающему: форма показывает её у кнопки. */
    async save(retentionDays: number | null): Promise<AuditSettingsSaveResult> {
      this.saving = true
      try {
        const result = await saveAuditSettings(retentionDays)
        // load(), начатый до сохранения, принесёт прежний срок: его ответ отбрасывается, а настройки перечитываются заново.
        const wasLoading = latest.invalidate(this)
        this.settings = {
          retention_days: result.retention_days,
          is_default: result.is_default,
          default_retention_days: result.default_retention_days,
          max_retention_days: result.max_retention_days,
          last_cleanup_at: result.last_cleanup_at,
        }
        if (wasLoading) void this.load()
        return result
      } finally {
        this.saving = false
      }
    },
  },
})
