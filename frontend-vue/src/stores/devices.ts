// Стор устройств для экрана "Инвентаризация физических устройств" (Лист 2).
//
// GET /api/v1/devices не поддерживает серверную фильтрацию/пагинацию (отдаёт всё
// сразу, см. backend/app/api/system.py:list_devices) — тот же подход, что и в
// текущем vanilla-фронтенде (кеш на limit=1000 в core.js): грузим один раз,
// дальше фильтруем/сортируем/пагинируем на клиенте. Это осознанный компромисс,
// адекватный для объёма реестра одной организации, а не публичного SaaS.
import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { Device, DevicesResponse } from '../api/types'
import { useCatalogsStore } from './catalogs'

const PAGE_SIZE = 6

export const useDevicesStore = defineStore('devices', {
  state: () => ({
    all: [] as Device[],
    total: 0,
    loaded: false,
    loading: false,
    error: null as string | null,
    // фильтры
    search: '',
    buildingId: '' as string,
    deviceTypeId: '' as string,
    siemFilter: 'all' as 'all' | 'yes' | 'no',
    structuralUnitIds: [] as string[],
    page: 1,
  }),
  getters: {
    filtered(state): Device[] {
      const catalogs = useCatalogsStore()
      let rows = state.all

      if (state.search.trim()) {
        const q = state.search.trim().toLowerCase()
        rows = rows.filter((d) =>
          [d.system_name, d.serial_number, d.management_ips, d.description]
            .filter(Boolean)
            .some((v) => String(v).toLowerCase().includes(q)),
        )
      }
      if (state.buildingId) {
        rows = rows.filter((d) => d.building_id === state.buildingId)
      }
      if (state.deviceTypeId) {
        rows = rows.filter((d) => d.device_type_id === state.deviceTypeId)
      }
      if (state.siemFilter !== 'all') {
        const want = state.siemFilter === 'yes'
        rows = rows.filter((d) => d.siem_enabled === want)
      }
      if (state.structuralUnitIds.length) {
        // Устройство относится к единице через своё здание (building.structural_unit_id).
        // Выбор родительской единицы включает все дочерние — тот же принцип
        // parent→child expansion, что в backend/app/reporting.py (см. память проекта).
        const wanted = new Set<string>()
        for (const id of state.structuralUnitIds) {
          for (const x of catalogs.unitAndDescendantIds(id)) wanted.add(x)
        }
        rows = rows.filter((d) => {
          const building = d.building_id ? catalogs.indexOf('buildings').get(d.building_id) : null
          const unitId = building?.structural_unit_id as string | undefined
          return unitId ? wanted.has(unitId) : false
        })
      }
      return rows
    },
    pageCount(): number {
      return Math.max(1, Math.ceil(this.filtered.length / PAGE_SIZE))
    },
    pageItems(): Device[] {
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
        const res = await api.get<DevicesResponse>('/devices')
        this.all = res.items
        this.total = res.total
        this.loaded = true
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить устройства'
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
