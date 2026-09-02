// Стор VLAN-доменов — простой generic-ресурс (в отличие от vlans.ts, которому нужна
// группировка через /vlan-dashboard). Используется в VLANDomainsPanel.vue.
import { defineStore } from 'pinia'
import { listResource } from '../api/client'
import type { VLANDomain } from '../api/types'

export const useVLANDomainsStore = defineStore('vlanDomains', {
  state: () => ({
    all: [] as VLANDomain[],
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
        const res = await listResource<VLANDomain>('vlan-domains', { limit: 1000 })
        this.all = res.items
        this.loaded = true
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить VLAN-домены'
      } finally {
        this.loading = false
      }
    },
  },
})
