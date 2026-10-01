// Стор для экрана "Журнал аудита" — только чтение (аудиторский след, редактирование
// или удаление записей через UI не предусмотрено и не должно быть, даже если
// технически /resources/audit-log поддерживает generic CRUD).
import { defineStore } from 'pinia'
import { listResource } from '../api/client'
import type { AuditLogEntry } from '../api/types'
import { isAllowedPageSize, loadPageSize, pageAfterSizeChange, pageSizeOptionsFor, savePageSize } from '../utils/pageSize'

const DEFAULT_PAGE_SIZE = 12
const LIST_ID = 'auditLog'

export const ACTION_LABELS: Record<string, string> = {
  CREATE: 'Создание',
  UPDATE: 'Изменение',
  DELETE: 'Удаление',
  SYNC: 'Синхронизация',
}

export const useAuditLogStore = defineStore('auditLog', {
  state: () => ({
    all: [] as AuditLogEntry[],
    total: 0,
    loaded: false,
    loading: false,
    error: null as string | null,
    search: '',
    actionFilter: 'all' as 'all' | keyof typeof ACTION_LABELS,
    entityTypeFilter: '',
    page: 1,
    pageSize: loadPageSize(LIST_ID, DEFAULT_PAGE_SIZE),
  }),
  getters: {
    filtered(state): AuditLogEntry[] {
      let rows = state.all
      if (state.search.trim()) {
        const q = state.search.trim().toLowerCase()
        rows = rows.filter((e) => [e.details, e.entity_id].filter(Boolean).some((v) => String(v).toLowerCase().includes(q)))
      }
      if (state.actionFilter !== 'all') {
        rows = rows.filter((e) => e.action === state.actionFilter)
      }
      if (state.entityTypeFilter) {
        rows = rows.filter((e) => e.entity_type === state.entityTypeFilter)
      }
      return rows
    },
    /** Уникальные entity_type, реально встречающиеся в журнале — для наполнения
     * фильтра, вместо показа всех ~30 типов ресурсов, из которых в логе будет
     * от силы десяток. */
    entityTypesInUse(state): string[] {
      return Array.from(new Set(state.all.map((e) => e.entity_type))).sort()
    },
    pageSizeOptions(): number[] {
      return pageSizeOptionsFor(DEFAULT_PAGE_SIZE)
    },
    pageCount(): number {
      return Math.max(1, Math.ceil(this.filtered.length / this.pageSize))
    },
    pageItems(): AuditLogEntry[] {
      const start = (this.page - 1) * this.pageSize
      return this.filtered.slice(start, start + this.pageSize)
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
        const res = await listResource<AuditLogEntry>('audit-log', { limit: 1000 })
        // Новые записи — сверху; created_at приходит ISO-строкой, лексикографическое
        // сравнение работает корректно без парсинга в Date.
        this.all = [...res.items].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
        this.total = res.total
        this.loaded = true
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить журнал аудита'
      } finally {
        this.loading = false
      }
    },
    setPage(p: number) {
      this.page = Math.min(Math.max(1, p), this.pageCount)
    },
    /** Смена количества строк на странице: остаёмся на странице с тем же первым видимым
     * элементом, выбор запоминается для этого списка. Недопустимое значение игнорируется. */
    setPageSize(size: number) {
      if (size === this.pageSize || !isAllowedPageSize(size, DEFAULT_PAGE_SIZE)) return
      this.page = pageAfterSizeChange(this.page, this.pageSize, size)
      this.pageSize = size
      savePageSize(LIST_ID, size)
    },
    resetPageOnFilterChange() {
      this.page = 1
    },
  },
})
