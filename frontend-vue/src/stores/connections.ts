// Стор для экрана "Подключения" (Лист 3).
// GET /resources/connections идёт через общий {items,total,offset,limit} (см.
// listResource в api/client.ts), но enrich_connections() на бэкенде уже добавляет
// резолвленные *_name поля, роли портов и статус сверки их конфигураций (port_config_status) —
// в отличие от /devices, здесь не нужен отдельный каталог-стор для отображения таблицы.
import { defineStore } from 'pinia'
import { listResource } from '../api/client'
import { approvePortConfig, revokePortConfigApproval } from '../api/portConfig'
import type { ApprovePortConfigResult } from '../api/portConfig'
import type { Connection, PortConfigStatus } from '../api/types'
import { roleLabel } from '../utils/portConfig'

const PAGE_SIZE = 8

export type PortConfigFilter = 'all' | PortConfigStatus

export const useConnectionsStore = defineStore('connections', {
  state: () => ({
    all: [] as Connection[],
    total: 0,
    loaded: false,
    loading: false,
    error: null as string | null,
    search: '',
    activeFilter: 'all' as 'all' | 'yes' | 'no',
    /** 'all' — без фильтра; 'mismatch' / 'approved' — только подключения с этим статусом сверки
     * портов; 'ok' — только с совпадающими ролями. */
    portConfigFilter: 'all' as PortConfigFilter,
    page: 1,
  }),
  getters: {
    /** Поиск идёт и по подписям ролей портов ("управление", "передача данных"): так находятся
     * подключения, где хотя бы один порт настроен определённым образом. */
    filtered(state): Connection[] {
      let rows = state.all
      if (state.search.trim()) {
        const q = state.search.trim().toLowerCase()
        rows = rows.filter((c) =>
          [
            c.source_device_name,
            c.source_interface_name,
            c.destination_device_name,
            c.destination_interface_name,
            c.connection_type_name,
            roleLabel(c.source_port_role),
            roleLabel(c.destination_port_role),
          ]
            .filter(Boolean)
            .some((v) => String(v).toLowerCase().includes(q)),
        )
      }
      if (state.activeFilter !== 'all') {
        const want = state.activeFilter === 'yes'
        rows = rows.filter((c) => c.is_active === want)
      }
      if (state.portConfigFilter !== 'all') {
        rows = rows.filter((c) => c.port_config_status === state.portConfigFilter)
      }
      return rows
    },
    pageCount(): number {
      return Math.max(1, Math.ceil(this.filtered.length / PAGE_SIZE))
    },
    pageItems(): Connection[] {
      const start = (this.page - 1) * PAGE_SIZE
      return this.filtered.slice(start, start + PAGE_SIZE)
    },
    /** Счётчики считаются по ВСЕМ подключениям, а не по отфильтрованным: они показывают, сколько
     * расхождений в реестре вообще, независимо от строки поиска и других фильтров. */
    mismatchCount(state): number {
      return state.all.filter((c) => c.port_config_status === 'mismatch').length
    },
    approvedCount(state): number {
      return state.all.filter((c) => c.port_config_status === 'approved').length
    },
    /** id интерфейсов, уже занятых активным подключением — источник и назначение —
     * используется формой, чтобы не давать выбрать заведомо занятый порт (сервер
     * это и так отклонит 409-м, см. validate_connection, но лучше не доводить). */
    occupiedInterfaceIds(state): Set<string> {
      const ids = new Set<string>()
      for (const c of state.all) {
        if (!c.is_active) continue
        ids.add(c.source_interface_id)
        ids.add(c.destination_interface_id)
      }
      return ids
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
        const res = await listResource<Connection>('connections', { limit: 1000 })
        this.all = res.items
        this.total = res.total
        this.loaded = true
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Не удалось загрузить подключения'
      } finally {
        this.loading = false
      }
    },
    /** Подставляет обновлённые сервером строки в уже загруженный список — без полной перезагрузки
     * (после одобрения/отзыва меняется только статус пары строк, а не весь реестр). */
    applyUpdated(items: Connection[]) {
      const byId = new Map(items.map((c) => [c.id, c]))
      this.all = this.all.map((c) => byId.get(c.id) ?? c)
    },
    async approve(ids: string[]): Promise<ApprovePortConfigResult> {
      const result = await approvePortConfig(ids)
      this.applyUpdated(result.items)
      return result
    },
    async revokeApproval(id: string): Promise<void> {
      this.applyUpdated([await revokePortConfigApproval(id)])
    },
    setPage(p: number) {
      this.page = Math.min(Math.max(1, p), this.pageCount)
    },
    resetPageOnFilterChange() {
      this.page = 1
    },
  },
})
