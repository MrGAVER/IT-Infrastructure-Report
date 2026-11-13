// Стор таблицы дашборда «Подключения» (Лист 3): постраничная выборка с сервера.
//
// Поиск, фильтры (активность, статус сверки ролей портов) и пагинация выполняются на сервере —
// GET /api/v1/connections. Раньше таблица читала все подключения одним запросом (до 1000) и
// фильтровала в браузере: записи сверх тысячи не попадали ни в таблицу, ни в счётчики, а статус
// сверки считался на клиенте по неполным данным. Теперь клиент держит только одну страницу, а
// счётчики (`summary`) приходят по всему реестру независимо от фильтров.
//
// Общий кэш подключений (stores/connections.ts) остаётся для карты занятых портов и схемы; после
// любого изменения обновляются оба — см. refreshAfterChange().
import { defineStore } from 'pinia'
import { fetchConnectionsPage } from '../api/connectionsPage'
import { approveMatchingPortConfig, approvePortConfig, revokePortConfigApproval } from '../api/portConfig'
import type { ApprovePortConfigResult } from '../api/portConfig'
import type { Connection, ConnectionsSummary, PortConfigStatus } from '../api/types'
import { useConnectionsStore } from './connections'
import { PAGE_SIZE_OPTIONS, isAllowedPageSize, loadPageSize, pageAfterSizeChange, savePageSize } from '../utils/pageSize'

const LIST_ID = 'connections'

export type ActiveFilter = 'all' | 'yes' | 'no'
export type PortConfigFilter = 'all' | PortConfigStatus

const EMPTY_SUMMARY: ConnectionsSummary = { total: 0, active: 0, inactive: 0, mismatch: 0, approved: 0 }

// Номер последнего отправленного запроса страницы: пользователь печатает быстрее, чем отвечает
// сервер, и ответ на более ранний запрос не должен затереть ответ на более поздний.
let latestRequest = 0

export const useConnectionsDashboardStore = defineStore('connectionsDashboard', {
  state: () => ({
    items: [] as Connection[],
    /** Сколько подключений под текущими поиском и фильтрами (а не на странице). */
    total: 0,
    /** Итоги по всему реестру — не зависят от поиска и фильтров. */
    summary: { ...EMPTY_SUMMARY } as ConnectionsSummary,
    page: 1,
    pageSize: loadPageSize(LIST_ID),
    search: '',
    activeFilter: 'all' as ActiveFilter,
    portConfigFilter: 'all' as PortConfigFilter,
    loaded: false,
    loading: false,
    error: null as string | null,
  }),
  getters: {
    pageCount: (state): number => Math.max(1, Math.ceil(state.total / state.pageSize)),
    pageSizeOptions: (): number[] => [...PAGE_SIZE_OPTIONS],
    /** Условия выборки в виде, общем для списка и для «одобрить все найденные». */
    isActiveParam: (state): boolean | undefined => (state.activeFilter === 'all' ? undefined : state.activeFilter === 'yes'),
    searchParam: (state): string | undefined => state.search.trim() || undefined,
  },
  actions: {
    /** Загружает текущую страницу с текущими условиями. Устаревший ответ (пришёл после более
     * позднего запроса) отбрасывается. Если страница вышла за конец (удалили последнюю запись
     * страницы, сузили фильтр), переходим на последнюю существующую. */
    async load(): Promise<void> {
      const request = ++latestRequest
      this.loading = true
      this.error = null
      try {
        const res = await fetchConnectionsPage({
          q: this.searchParam,
          is_active: this.isActiveParam,
          port_config_status: this.portConfigFilter === 'all' ? undefined : this.portConfigFilter,
          offset: (this.page - 1) * this.pageSize,
          limit: this.pageSize,
        })
        if (request !== latestRequest) return
        if (res.items.length === 0 && res.total > 0 && this.page > 1) {
          this.page = Math.max(1, Math.ceil(res.total / this.pageSize))
          return this.load()
        }
        this.items = res.items
        this.total = res.total
        this.summary = res.summary
        this.loaded = true
      } catch (e) {
        if (request === latestRequest) this.error = e instanceof Error ? e.message : 'Не удалось загрузить подключения'
      } finally {
        if (request === latestRequest) this.loading = false
      }
    },
    /** Снимает поиск и оба фильтра (кнопка «Сбросить фильтры» в пустой таблице, F-04). Только меняет условия: страницу
     * с сервера перечитывает экран — его наблюдатели за поиском и фильтрами, как при любом другом их изменении. */
    resetFilters() {
      this.search = ''
      this.activeFilter = 'all'
      this.portConfigFilter = 'all'
    },
    /** Смена поиска или фильтра — всегда с первой страницы. */
    applyFilters(): Promise<void> {
      this.page = 1
      return this.load()
    },
    /** Смена количества строк: остаёмся на странице с тем же первым видимым подключением, выбор
     * запоминается. Недопустимое значение игнорируется. */
    setPageSize(size: number): Promise<void> {
      if (size === this.pageSize || !isAllowedPageSize(size)) return Promise.resolve()
      this.page = pageAfterSizeChange(this.page, this.pageSize, size)
      this.pageSize = size
      savePageSize(LIST_ID, size)
      return this.load()
    },
    setPage(p: number): Promise<void> {
      this.page = Math.min(Math.max(1, p), this.pageCount)
      return this.load()
    },
    /** После любого изменения подключений (форма, схема, удаление, порты, одобрение) — перечитать
     * и страницу, и общий кэш: в кэше свои копии записей (в т.ч. статус сверки для формы, открытой
     * со схемы), и без обновления они разошлись бы с сервером. */
    async refreshAfterChange(): Promise<void> {
      await Promise.all([this.load(), useConnectionsStore().reload()])
    },
    async approve(ids: string[]): Promise<ApprovePortConfigResult> {
      const result = await approvePortConfig(ids)
      await this.refreshAfterChange()
      return result
    },
    /** Одобряет ВСЕ подключения с расхождением под текущими поиском и фильтром активности — не
     * только показанную страницу. */
    async approveMatching(): Promise<ApprovePortConfigResult> {
      const result = await approveMatchingPortConfig({ q: this.searchParam ?? null, is_active: this.isActiveParam ?? null })
      await this.refreshAfterChange()
      return result
    },
    /** Возвращает актуальную запись — окно проверки показывает её, даже если после отзыва строка
     * уже не подходит под фильтр «Одобренные» и с текущей страницы пропала. */
    async revokeApproval(id: string): Promise<Connection> {
      const updated = await revokePortConfigApproval(id)
      await this.refreshAfterChange()
      return updated
    },
  },
})
