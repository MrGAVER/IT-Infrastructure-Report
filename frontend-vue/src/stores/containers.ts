// Стор для экрана "Контейнеры". В отличие от vms.ts/devices.ts нет отдельного дашборд-
// эндпоинта — контейнеры простой generic-ресурс, поэтому listResource('containers', ...),
// как в vlanDomains.ts.
import { defineStore } from 'pinia'
import { listResource } from '../api/client'
import type { Container } from '../api/types'

const PAGE_SIZE = 8

export const useContainersStore = defineStore('containers', {
  state: () => ({
    all: [] as Container[],
    loaded: false,
    loading: false,
    error: null as string | null,
    search: '',
    page: 1,
  }),
  getters: {
    filtered(state): Container[] {
      if (!state.search.trim()) return state.all
      const q = state.search.trim().toLowerCase()
      return state.all.filter((c) => [c.name, c.runtime, c.purpose].filter(Boolean).some((v) => String(v).toLowerCase().includes(q)))
    },
    pageCount(): number {
      return Math.max(1, Math.ceil(this.filtered.length / PAGE_SIZE))
    },
    pageItems(): Container[] {
      const start = (this.page - 1) * PAGE_SIZE
      return this.filtered.slice(start, start + PAGE_SIZE)
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
        const res = await listResource<Container>('containers', { limit: 1000 })
        this.all = res.items
        this.loaded = true
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить контейнеры'
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
