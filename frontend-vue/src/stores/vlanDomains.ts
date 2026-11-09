// Стор VLAN-доменов — простой generic-ресурс (в отличие от vlans.ts, которому нужна
// группировка через /vlan-dashboard). Используется в VLANDomainsPanel.vue.
import { defineStore } from 'pinia'
import { listAllResource } from '../api/client'
import { warnIfTruncated } from '../composables/useTruncationWarning'
import type { VLANDomain } from '../api/types'

export const useVLANDomainsStore = defineStore('vlanDomains', {
  state: () => ({
    all: [] as VLANDomain[],
    total: 0,
    truncated: false,
    // Загружено не всё (потолок listAllResource): экраны, показывающие этот список целиком, выводят постоянное DataLoadNotice,
    // а не только исчезающее через 10 с предупреждение warnIfTruncated.
    loaded: false,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async ensureLoaded() {
      if (this.loaded || this.loading) return
      await this.reload()
    },
    async reload() {
      this.loading = true
      this.error = null
      try {
        const res = await listAllResource<VLANDomain>('vlan-domains')
        this.all = res.items
        this.total = res.total
        this.truncated = res.truncated === true
        this.loaded = true
        warnIfTruncated(res, 'VLAN-доменов')
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить VLAN-домены'
      } finally {
        this.loading = false
      }
    },
  },
})
