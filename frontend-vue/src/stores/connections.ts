// Стор для экрана "Подключения" (Лист 3).
// GET /resources/connections идёт через общий {items,total,offset,limit} (см.
// listResource в api/client.ts), но enrich_connections() на бэкенде уже добавляет
// резолвленные *_name поля — в отличие от /devices, здесь не нужен отдельный
// каталог-стор для отображения таблицы.
import { defineStore } from 'pinia'
import { listResource } from '../api/client'
import type { Connection } from '../api/types'

const PAGE_SIZE = 8

export const useConnectionsStore = defineStore('connections', {
  state: () => ({
    all: [] as Connection[],
    total: 0,
    loaded: false,
    loading: false,
    error: null as string | null,
    search: '',
    activeFilter: 'all' as 'all' | 'yes' | 'no',
    page: 1,
  }),
  getters: {
    filtered(state): Connection[] {
      let rows = state.all
      if (state.search.trim()) {
        const q = state.search.trim().toLowerCase()
        rows = rows.filter((c) =>
          [c.source_device_name, c.source_interface_name, c.destination_device_name, c.destination_interface_name, c.purpose]
            .filter(Boolean)
            .some((v) => String(v).toLowerCase().includes(q)),
        )
      }
      if (state.activeFilter !== 'all') {
        const want = state.activeFilter === 'yes'
        rows = rows.filter((c) => c.is_active === want)
      }
      return rows
    },
    pageCount(): number {
      return Math.max(1, Math.ceil(this.filtered.length / PAGE_SIZE))
    },
    pageItems(): Connection[] {
      const start = (this.page - 1) * PAGE_SIZE
      return this.filtered.slice(start, start + PAGE_SIZE)
    },
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
        const res = await listResource<Connection>('connections', { limit: 1000 })
        this.all = res.items
        this.total = res.total
        this.loaded = true
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить подключения'
      } finally {
        this.loading = false
      }
    },
    setPage(p: number) {
      this.page = Math.min(Math.max(1, p), this.pageCount)
    },
    resetPageOnFilterChange() {
      this.page = 1
    },
  },
})
