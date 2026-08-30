// Стор для экрана "Шаблоны отчётов". Список обычно небольшой (десятки, не тысячи записей) —
// без пагинации, в отличие от containers.ts/vlanDomains.ts, только поиск по названию/описанию.
import { defineStore } from 'pinia'
import { listReportTemplates } from '../api/reportTemplates'
import type { ReportTemplate } from '../api/types'

export const useReportTemplatesStore = defineStore('reportTemplates', {
  state: () => ({
    all: [] as ReportTemplate[],
    loaded: false,
    loading: false,
    error: null as string | null,
    search: '',
  }),
  getters: {
    filtered(state): ReportTemplate[] {
      if (!state.search.trim()) return state.all
      const q = state.search.trim().toLowerCase()
      return state.all.filter((t) => [t.name, t.description].filter(Boolean).some((v) => String(v).toLowerCase().includes(q)))
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
        this.all = await listReportTemplates()
        this.loaded = true
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить шаблоны отчётов'
      } finally {
        this.loading = false
      }
    },
  },
})
