// Стор для экрана "Шаблоны отчётов". Список обычно небольшой (десятки, не тысячи записей) —
// без пагинации, в отличие от containers.ts/vlanDomains.ts, только поиск по названию/описанию.
import { defineStore } from 'pinia'
import { listReportTemplates } from '../api/reportTemplates'
import type { ReportTemplate } from '../api/types'
import { createLatestRequest } from '../utils/latestRequest'

// B-02: ответ на более ранний reload() не должен затереть более поздний (см. utils/latestRequest.ts).
const latest = createLatestRequest()

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
      const isLatest = latest.begin()
      this.loading = true
      this.error = null
      try {
        const list = await listReportTemplates()
        if (!isLatest()) return // устаревший ответ: finally ничего не тронет
        this.all = list
        this.loaded = true
      } catch (e) {
        if (isLatest()) this.error = e instanceof Error ? e.message : 'Не удалось загрузить шаблоны отчётов'
      } finally {
        if (isLatest()) this.loading = false
      }
    },
  },
})
