// Стор для экрана "Контейнеры". В отличие от vms.ts/devices.ts нет отдельного дашборд-
// эндпоинта — контейнеры простой generic-ресурс, поэтому listResource('containers', ...),
// как в vlanDomains.ts.
import { defineStore } from 'pinia'
import { listAllResource } from '../api/client'
import { warnIfTruncated } from '../composables/useTruncationWarning'
import type { Container } from '../api/types'
import { PAGE_SIZE_OPTIONS, isAllowedPageSize, loadPageSize, pageAfterSizeChange, savePageSize } from '../utils/pageSize'

const LIST_ID = 'containers'

export const useContainersStore = defineStore('containers', {
  state: () => ({
    all: [] as Container[],
    total: 0,
    truncated: false,
    // Загружено не всё (потолок listAllResource): экраны, показывающие этот список целиком, выводят постоянное DataLoadNotice,
    // а не только исчезающее через 10 с предупреждение warnIfTruncated.
    loaded: false,
    loading: false,
    error: null as string | null,
    search: '',
    page: 1,
    pageSize: loadPageSize(LIST_ID),
  }),
  getters: {
    filtered(state): Container[] {
      if (!state.search.trim()) return state.all
      const q = state.search.trim().toLowerCase()
      return state.all.filter((c) => [c.name, c.runtime, c.purpose].filter(Boolean).some((v) => String(v).toLowerCase().includes(q)))
    },
    pageSizeOptions(): number[] {
      return [...PAGE_SIZE_OPTIONS]
    },
    pageCount(): number {
      return Math.max(1, Math.ceil(this.filtered.length / this.pageSize))
    },
    pageItems(): Container[] {
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
        const res = await listAllResource<Container>('containers')
        this.all = res.items
        this.total = res.total
        this.truncated = res.truncated === true
        this.loaded = true
        warnIfTruncated(res, 'контейнеров')
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить контейнеры'
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
      if (size === this.pageSize || !isAllowedPageSize(size)) return
      this.page = pageAfterSizeChange(this.page, this.pageSize, size)
      this.pageSize = size
      savePageSize(LIST_ID, size)
    },
    resetPageOnFilterChange() {
      this.page = 1
    },
    /** Снимает поиск (кнопка «Сбросить фильтры» в пустой таблице, F-04). */
    resetFilters() {
      this.search = ''
      this.page = 1
    },
  },
})
