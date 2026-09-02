// Стор для экрана "Информационные системы" (Лист 1).
//
// GET /api/v1/information-systems отдаёт ПЛОСКИЙ МАССИВ (см. backend/app/api/system.py:list_is) —
// третья форма ответа в этом бэкенде наряду с {items,total} (/devices) и
// {items,total,offset,limit} (/resources/{r}). Не перепутать снова, как уже случалось
// с listResource() (см. историю коммитов) — здесь просто api.get<InformationSystem[]>.
import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { InformationSystem } from '../api/types'

const PAGE_SIZE = 8

export const useInformationSystemsStore = defineStore('informationSystems', {
  state: () => ({
    all: [] as InformationSystem[],
    loaded: false,
    loading: false,
    error: null as string | null,
    search: '',
    siemFilter: 'all' as 'all' | 'yes' | 'no',
    page: 1,
  }),
  getters: {
    filtered(state): InformationSystem[] {
      let rows = state.all
      if (state.search.trim()) {
        const q = state.search.trim().toLowerCase()
        rows = rows.filter((s) =>
          [s.name, s.description, s.purpose, s.localization].filter(Boolean).some((v) => String(v).toLowerCase().includes(q)),
        )
      }
      if (state.siemFilter !== 'all') {
        const want = state.siemFilter === 'yes'
        rows = rows.filter((s) => s.siem_enabled === want)
      }
      return rows
    },
    pageCount(): number {
      return Math.max(1, Math.ceil(this.filtered.length / PAGE_SIZE))
    },
    pageItems(): InformationSystem[] {
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
        this.all = await api.get<InformationSystem[]>('/information-systems')
        this.loaded = true
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить информационные системы'
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
