// Стор VLAN-доменов — простой generic-ресурс (в отличие от vlans.ts, которому нужна
// группировка через /vlan-dashboard). Используется в VLANDomainsPanel.vue.
import { defineStore } from 'pinia'
import { listAllResource } from '../api/client'
import { warnIfTruncated } from '../composables/useTruncationWarning'
import type { VLANDomain } from '../api/types'
import { createLatestRequest } from '../utils/latestRequest'

// Ответ на более ранний reload() не должен затереть более поздний (см. utils/latestRequest.ts).
const latest = createLatestRequest()

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
      await latest.ensure(this, () => this.reload())
    },
    async reload() {
      await latest.run(this, {
        fetch: () => listAllResource<VLANDomain>('vlan-domains'),
        apply: (res) => {
          this.all = res.items
          this.total = res.total
          this.truncated = res.truncated === true
          this.loaded = true
          warnIfTruncated(res, 'VLAN-доменов')
        },
        errorMessage: 'Не удалось загрузить VLAN-домены',
      })
    },
  },
})
