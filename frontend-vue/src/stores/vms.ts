// Стор для экрана "Виртуальные машины" (Лист 4).
// GET /api/v1/vms -> {items,total}, как /devices (см. api/types.ts:VMsResponse).
import { defineStore } from 'pinia'
import { api } from '../api/client'
import type { VirtualMachine, VMsResponse } from '../api/types'
import { isAllowedPageSize, loadPageSize, pageAfterSizeChange, pageSizeOptionsFor, savePageSize } from '../utils/pageSize'

const DEFAULT_PAGE_SIZE = 8
const LIST_ID = 'vms'

export const useVMsStore = defineStore('vms', {
  state: () => ({
    all: [] as VirtualMachine[],
    total: 0,
    loaded: false,
    loading: false,
    error: null as string | null,
    search: '',
    page: 1,
    pageSize: loadPageSize(LIST_ID, DEFAULT_PAGE_SIZE),
  }),
  getters: {
    filtered(state): VirtualMachine[] {
      if (!state.search.trim()) return state.all
      const q = state.search.trim().toLowerCase()
      return state.all.filter((vm) => [vm.name, vm.purpose, vm.description].filter(Boolean).some((v) => String(v).toLowerCase().includes(q)))
    },
    pageSizeOptions(): number[] {
      return pageSizeOptionsFor(DEFAULT_PAGE_SIZE)
    },
    pageCount(): number {
      return Math.max(1, Math.ceil(this.filtered.length / this.pageSize))
    },
    pageItems(): VirtualMachine[] {
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
        const res = await api.get<VMsResponse>('/vms')
        this.all = res.items
        this.total = res.total
        this.loaded = true
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить виртуальные машины'
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
