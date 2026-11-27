// Стор для экрана "VLAN". Отображение группирует по vlan_id через специализированный
// /api/v1/vlan-dashboard (один и тот же VLAN ID может иметь разные определения в
// разных доменах — см. api/types/vlans.ts:VLANDashboardGroup). CRUD отдельных определений —
// через общий /resources/vlans, как везде.
import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { VLANDashboardGroup, VLANDashboardResponse, VLANDefinition } from '../api/types'
import { createLatestRequest } from '../utils/latestRequest'

// Ответ на более ранний reload() не должен затереть более поздний (см. utils/latestRequest.ts).
const latest = createLatestRequest()

export const useVLANsStore = defineStore('vlans', {
  state: () => ({
    groups: [] as VLANDashboardGroup[],
    loaded: false,
    loading: false,
    error: null as string | null,
    search: '',
  }),
  getters: {
    filtered(state): VLANDashboardGroup[] {
      if (!state.search.trim()) return state.groups
      const q = state.search.trim().toLowerCase()
      return state.groups
        .map((g) => ({
          ...g,
          definitions: g.definitions.filter(
            (d) =>
              String(d.vlan_id).includes(q) ||
              d.name.toLowerCase().includes(q) ||
              d.domain_name.toLowerCase().includes(q) ||
              d.devices.some((dev) => dev.device_name.toLowerCase().includes(q)),
          ),
        }))
        .filter((g) => g.definitions.length)
    },
    definitionCount(state): number {
      return state.groups.reduce((sum, g) => sum + g.definitions.length, 0)
    },
    conflictingVlanIds(state): number[] {
      // Один и тот же vlan_id с разными именами в разных доменах — не ошибка сама по
      // себе (для этого и есть домены), но стоит показать как "требует внимания".
      return state.groups.filter((g) => new Set(g.definitions.map((d) => d.name)).size > 1).map((g) => g.vlan_id)
    },
    // Плоский список всех определений VLAN, без группировки по vlan_id — нужен для
    // выпадающих списков (DeviceVlanListEditor.vue, панель массового назначения на
    // VLANsView.vue), где группировка неважна, а нужен просто "любой VLAN".
    allDefinitions(state): VLANDefinition[] {
      return state.groups.flatMap((g) => g.definitions)
    },
  },
  actions: {
    /** Кнопка «Сбросить фильтры» пустого списка: единственный фильтр экрана — поиск. */
    resetFilters() {
      this.search = ''
    },
    async ensureLoaded() {
      await latest.ensure(this, () => this.reload())
    },
    async reload() {
      await latest.run(this, {
        fetch: () => api.get<VLANDashboardResponse>('/vlan-dashboard'),
        apply: (res) => {
          this.groups = res.items
          this.loaded = true
        },
        errorMessage: 'Не удалось загрузить VLAN',
      })
    },
  },
})
