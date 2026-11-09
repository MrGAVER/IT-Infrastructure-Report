// Общий кэш подключений: карта занятых портов, схема «Визуальный режим», предупреждения о
// конфликтах портов в формах устройства. Читает GET /resources/connections одним запросом
// (до 1000 записей, как и каталоги — см. stores/catalogs.ts).
//
// Таблица дашборда «Подключения» этот кэш НЕ использует: она постраничная, с поиском, фильтрами и
// статусом сверки ролей портов на сервере — см. stores/connectionsDashboard.ts.
import { defineStore } from 'pinia'
import { listAllResource } from '../api/client'
import { warnIfTruncated } from '../composables/useTruncationWarning'
import type { Connection } from '../api/types'

export const useConnectionsStore = defineStore('connections', {
  state: () => ({
    all: [] as Connection[],
    total: 0,
    truncated: false,
    // Загружено не всё (потолок listAllResource): экраны, показывающие этот список целиком, выводят постоянное DataLoadNotice,
    // а не только исчезающее через 10 с предупреждение warnIfTruncated.
    loaded: false,
    loading: false,
    error: null as string | null,
  }),
  getters: {
    /** id интерфейсов, уже занятых активным подключением — источник и назначение —
     * используется формой, чтобы не давать выбрать заведомо занятый порт (сервер
     * это и так отклонит 409-м, см. validate_connection, но лучше не доводить). */
    occupiedInterfaceIds(state): Set<string> {
      const ids = new Set<string>()
      for (const c of state.all) {
        if (!c.is_active) continue
        ids.add(c.source_interface_id)
        ids.add(c.destination_interface_id)
      }
      return ids
    },
  },
  actions: {
    async ensureLoaded() {
      if (this.loaded || this.loading) return
      await this.reload()
    },
    async reload() {
      this.loading = true
      this.error = null
      try {
        const res = await listAllResource<Connection>('connections')
        this.all = res.items
        this.total = res.total
        this.truncated = res.truncated === true
        this.loaded = true
        warnIfTruncated(res, 'подключений')
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить подключения'
      } finally {
        this.loading = false
      }
    },
  },
})
