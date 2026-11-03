// Стор для экрана "Информационные системы" (Лист 1).
//
// GET /api/v1/information-systems отдаёт ПЛОСКИЙ МАССИВ (см. backend/app/api/listings.py:list_information_systems) —
// третья форма ответа в этом бэкенде наряду с {items,total} (/devices) и
// {items,total,offset,limit} (/resources/{r}). Не перепутать снова, как уже случалось
// с listResource() (см. историю коммитов) — здесь просто api.get<InformationSystem[]>.
import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { InformationSystem } from '../api/types'
import { isAllowedPageSize, loadPageSize, pageAfterSizeChange, pageSizeOptionsFor, savePageSize } from '../utils/pageSize'
import { sortNaturally } from '../utils/naturalSort'

const DEFAULT_PAGE_SIZE = 8
const LIST_ID = 'informationSystems'

export const useInformationSystemsStore = defineStore('informationSystems', {
  state: () => ({
    all: [] as InformationSystem[],
    loaded: false,
    loading: false,
    error: null as string | null,
    search: '',
    siemFilter: 'all' as 'all' | 'yes' | 'no',
    page: 1,
    pageSize: loadPageSize(LIST_ID, DEFAULT_PAGE_SIZE),
  }),
  getters: {
    filtered(state): InformationSystem[] {
      let rows = state.all
      if (state.search.trim()) {
        const q = state.search.trim().toLowerCase()
        // IP-адреса — те же строки, что в столбце «IP-адреса» (у адресов ВМ с префиксом, «192.168.5.10/24»): по подстроке
        // находится и адрес целиком, и его начало («10.1.»), и запись с префиксом.
        rows = rows.filter((s) =>
          [s.name, s.description, s.purpose, s.localization, ...(s.ip_addresses ?? [])].filter(Boolean).some((v) => String(v).toLowerCase().includes(q)),
        )
      }
      if (state.siemFilter !== 'all') {
        const want = state.siemFilter === 'yes'
        rows = rows.filter((s) => s.siem_enabled === want)
      }
      return rows
    },
    pageSizeOptions(): number[] {
      return pageSizeOptionsFor(DEFAULT_PAGE_SIZE)
    },
    pageCount(): number {
      return Math.max(1, Math.ceil(this.filtered.length / this.pageSize))
    },
    pageItems(): InformationSystem[] {
      const start = (this.page - 1) * this.pageSize
      return this.filtered.slice(start, start + this.pageSize)
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
        // backend сортирует по строке («ИС 10» раньше «ИС 2»): порядок приводится к естественному один раз при записи (UI-13).
        this.all = sortNaturally(await api.get<InformationSystem[]>('/information-systems'), (s) => s.name)
        this.loaded = true
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить информационные системы'
      } finally {
        this.loading = false
      }
    },
    /** Помечает загруженный список устаревшим: при следующем открытии экрана ИС он загрузится заново. Нужен, когда
     * данные, от которых зависит строка ИС, правятся на другом экране: столбец «IP-адреса» берёт адреса связанных ВМ
     * (после сохранения ВМ см. VMsView.vue). Сам список при этом не очищается и не перезапрашивается сразу. */
    invalidate() {
      this.loaded = false
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
