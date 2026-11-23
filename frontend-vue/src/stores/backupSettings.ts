// Стор настроек плановых копий (панель «Резервные копии» в «Настройках»). Данные — с сервера (GET/PUT /api/v1/backup/settings), только
// для администратора: viewer получает 403, и панель ему не показывается (auth.canManageBackups). Сохранение пессимистичное: интерфейс
// показывает то, что подтвердил сервер (значения приоритетнее окружения он мог оставить прежними), а не то, что ввёл пользователь.
import { defineStore } from 'pinia'
import { fetchBackupSettings, saveBackupSettings } from '../api/backupSettings'
import { ApiError } from '../api/client'
import type { BackupSettings, BackupSettingsUpdate } from '../api/types'
import { createLatestRequest } from '../utils/latestRequest'

// Ответ на более ранний load() не должен затереть более поздний или уже подтверждённое сохранение (см. utils/latestRequest.ts).
const latest = createLatestRequest()

export const useBackupSettingsStore = defineStore('backupSettings', {
  state: () => ({
    settings: null as BackupSettings | null,
    loading: false,
    saving: false,
    error: null as string | null,
  }),
  actions: {
    /** Перечитывает настройки и статус копий; при ошибке оставляет текст в error (прежние настройки не затираются). */
    async load(): Promise<void> {
      await latest.run(this, {
        fetch: fetchBackupSettings,
        apply: (settings) => {
          this.settings = settings
        },
        errorMessage: (err) => (err instanceof ApiError ? err.message : 'Не удалось загрузить настройки резервных копий'),
      })
    },

    /** Сохраняет изменённые параметры. Ошибку пробрасывает вызывающему: панель показывает её у кнопки. */
    async save(patch: BackupSettingsUpdate): Promise<BackupSettings> {
      this.saving = true
      try {
        const result = await saveBackupSettings(patch)
        // load(), начатый до сохранения, принесёт прежние значения: его ответ отбрасывается, а настройки перечитываются заново.
        const wasLoading = latest.invalidate(this)
        this.settings = result
        if (wasLoading) void this.load()
        return result
      } finally {
        this.saving = false
      }
    },
  },
})
