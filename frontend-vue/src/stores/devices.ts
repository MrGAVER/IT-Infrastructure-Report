// Стор устройств для экрана "Инвентаризация физических устройств" (Лист 2).
//
// GET /api/v1/devices не поддерживает серверную фильтрацию/пагинацию (отдаёт всё
// сразу, см. backend/app/api/listings.py:list_devices) — тот же подход, что и в
// прежнем vanilla-фронтенде, удалённом в 2.60.0 (кеш на limit=1000): грузим один раз,
// дальше фильтруем/сортируем/пагинируем на клиенте. Это осознанный компромисс,
// адекватный для объёма реестра одной организации, а не публичного SaaS.
import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { Device, DevicesResponse } from '../api/types'
import { useCatalogsStore } from './catalogs'
import { isAllowedPageSize, loadPageSize, pageAfterSizeChange, pageSizeOptionsFor, savePageSize } from '../utils/pageSize'
import { sortNaturally } from '../utils/naturalSort'

const DEFAULT_PAGE_SIZE = 6
const LIST_ID = 'devices'

/** Пункт 2 правки "инвентаризация физических устройств": строка таблицы — либо одиночное
 * устройство, либо СВЁРНУТАЯ группа участников одного стека (см. groupedFiltered ниже). */
export type DeviceRow = { kind: 'device'; device: Device } | { kind: 'stack'; stackId: string; stackName: string; members: Device[] }

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
    pageSize: loadPageSize(LIST_ID, DEFAULT_PAGE_SIZE),
  }),
  getters: {
    filtered(state): Device[] {
      const catalogs = useCatalogsStore()
      let rows = state.all

      if (state.search.trim()) {
        const q = state.search.trim().toLowerCase()
        rows = rows.filter((d) =>
          [d.system_name, d.serial_number, d.management_ips, d.description].filter(Boolean).some((v) => String(v).toLowerCase().includes(q)),
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
    /** Участники одного стека схлопываются в ОДНУ строку 'stack' — в позиции первого попадания
     * в filtered (т.е. там, где стоял бы алфавитно самый ранний участник по system_name, раз
     * backend отдаёт /devices уже отсортированным им), остальные участники того же стека из
     * потока пропускаются (уже представлены через members). Одиночные устройства идут как
     * раньше, по одной строке 'device'. Пагинация (pageCount/pageItems ниже) считается ИМЕННО
     * по этим строкам, а не по числу "сырых" устройств: стек из 4 физических коммутаторов
     * занимает один пагинационный слот, а не четыре (см. п.2 правки "инвентаризация физических
     * устройств") — иначе часть страниц показывала бы заметно меньше 6 видимых строк только
     * потому, что крупный стек "съел" большую часть слотов на свёрнутый заголовок.
     */
    groupedFiltered(): DeviceRow[] {
      const rows: DeviceRow[] = []
      const seenStacks = new Set<string>()
      for (const d of this.filtered) {
        if (!d.stack_id) {
          rows.push({ kind: 'device', device: d })
          continue
        }
        if (seenStacks.has(d.stack_id)) continue
        seenStacks.add(d.stack_id)
        const members = this.filtered
          .filter((m: Device) => m.stack_id === d.stack_id)
          .sort((a: Device, b: Device) => (a.stack_position ?? 0) - (b.stack_position ?? 0))
        rows.push({ kind: 'stack', stackId: d.stack_id, stackName: d.stack_name ?? '', members })
      }
      return rows
    },
    pageSizeOptions(): number[] {
      return pageSizeOptionsFor(DEFAULT_PAGE_SIZE)
    },
    pageCount(): number {
      return Math.max(1, Math.ceil(this.groupedFiltered.length / this.pageSize))
    },
    pageItems(): DeviceRow[] {
      const start = (this.page - 1) * this.pageSize
      return this.groupedFiltered.slice(start, start + this.pageSize)
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
        // backend сортирует по строке («dev-12» раньше «dev-6»), поэтому порядок один раз приводится к естественному при записи —
        // не на каждое изменение фильтра. Устройства без системного имени, как и на сервере, идут первыми (UI-13).
        this.all = sortNaturally(res.items, (d) => d.system_name, { emptyFirst: true })
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
    /** Смена количества строк на странице: остаёмся на странице с тем же первым видимым
     * элементом, выбор запоминается для этого списка. Недопустимое значение игнорируется. */
    setPageSize(size: number) {
      if (size === this.pageSize || !isAllowedPageSize(size, DEFAULT_PAGE_SIZE)) return
      this.page = pageAfterSizeChange(this.page, this.pageSize, size)
      this.pageSize = size
      savePageSize(LIST_ID, size)
    },
    resetPageOnFilterChange() {
      this.page = 1
    },
  },
})
