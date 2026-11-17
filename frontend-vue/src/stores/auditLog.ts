// Стор экрана «Журнал аудита» — постраничная выборка с сервера, только чтение (аудиторский след:
// редактирование или удаление записей через UI не предусмотрено и не должно быть, даже если
// технически /resources/audit-log поддерживает generic CRUD).
//
// Поиск, фильтры (действие, раздел), порядок «новые сверху» и пагинация выполняются на сервере —
// GET /api/v1/audit-log. Раньше экран читал последние 1000 записей и фильтровал их в браузере:
// журнал только растёт, поэтому всё старше тысячи последних записей было недоступно ни в
// таблице, ни в поиске, ни в счётчиках. Теперь клиент держит одну страницу, а счётчики
// (`summary`) и список разделов (`entityTypes`) приходят по всему журналу независимо от фильтров.
import { defineStore } from 'pinia'
import { fetchAuditLogPage } from '../api/auditLogPage'
import type { AuditLogEntry, AuditLogSummary } from '../api/types'
import { PAGE_SIZE_OPTIONS, isAllowedPageSize, loadPageSize, pageAfterSizeChange, savePageSize } from '../utils/pageSize'
import { createLatestRequest } from '../utils/latestRequest'

const LIST_ID = 'auditLog'

export const ACTION_LABELS: Record<string, string> = {
  CREATE: 'Создание',
  UPDATE: 'Изменение',
  DELETE: 'Удаление',
  SYNC: 'Синхронизация',
}

const EMPTY_SUMMARY: AuditLogSummary = { total: 0, by_action: {} }

// Номер последнего отправленного запроса страницы: пользователь печатает быстрее, чем отвечает
// сервер, и ответ на более ранний запрос не должен затереть ответ на более поздний.
const latest = createLatestRequest()

export const useAuditLogStore = defineStore('auditLog', {
  state: () => ({
    /** Записи текущей страницы. */
    items: [] as AuditLogEntry[],
    /** Сколько записей под текущими поиском и фильтрами (а не на странице). */
    total: 0,
    /** Итоги по всему журналу — не зависят от поиска и фильтров. */
    summary: { ...EMPTY_SUMMARY, by_action: {} } as AuditLogSummary,
    /** Разделы, реально встречающиеся в журнале, — для фильтра «Раздел». */
    entityTypes: [] as string[],
    loaded: false,
    loading: false,
    error: null as string | null,
    search: '',
    actionFilter: 'all' as 'all' | keyof typeof ACTION_LABELS,
    entityTypeFilter: '',
    page: 1,
    pageSize: loadPageSize(LIST_ID),
  }),
  getters: {
    pageSizeOptions: (): number[] => [...PAGE_SIZE_OPTIONS],
    pageCount: (state): number => Math.max(1, Math.ceil(state.total / state.pageSize)),
    /** Число записей журнала с данным действием — по всему журналу. */
    countByAction:
      (state) =>
      (action: string): number =>
        state.summary.by_action[action] ?? 0,
  },
  actions: {
    /** Загружает текущую страницу с текущими условиями. Устаревший ответ (пришёл после более
     * позднего запроса) отбрасывается. Если страница вышла за конец (журнал сузили фильтром),
     * переходим на последнюю существующую. */
    async load(): Promise<void> {
      await latest.run(this, {
        fetch: () =>
          fetchAuditLogPage({
            q: this.search.trim() || undefined,
            action: this.actionFilter === 'all' ? undefined : this.actionFilter,
            entity_type: this.entityTypeFilter || undefined,
            offset: (this.page - 1) * this.pageSize,
            limit: this.pageSize,
          }),
        apply: (res) => {
          if (res.items.length === 0 && res.total > 0 && this.page > 1) {
            this.page = Math.max(1, Math.ceil(res.total / this.pageSize))
            return this.load()
          }
          this.items = res.items
          this.total = res.total
          this.summary = res.summary
          this.entityTypes = res.entity_types
          this.loaded = true
        },
        errorMessage: 'Не удалось загрузить журнал аудита',
      })
    },
    /** Кнопка «Обновить»: перечитать текущую страницу (в журнале могли появиться новые записи). */
    reload(): Promise<void> {
      return this.load()
    },
    /** Кнопка «Сбросить фильтры» пустого списка: поиск и оба фильтра — в исходное. Загрузку не запускает: экран следит за этими полями
     * (поиск — с задержкой, фильтры — сразу) и перечитывает страницу сам. */
    resetFilters(): void {
      this.search = ''
      this.actionFilter = 'all'
      this.entityTypeFilter = ''
    },
    /** Смена поиска или фильтра — всегда с первой страницы. */
    applyFilters(): Promise<void> {
      this.page = 1
      return this.load()
    },
    setPage(p: number): Promise<void> {
      this.page = Math.min(Math.max(1, p), this.pageCount)
      return this.load()
    },
    /** Смена количества строк: остаёмся на странице с тем же первым видимым элементом, выбор
     * запоминается для этого списка. Недопустимое значение игнорируется. */
    setPageSize(size: number): Promise<void> {
      if (size === this.pageSize || !isAllowedPageSize(size)) return Promise.resolve()
      this.page = pageAfterSizeChange(this.page, this.pageSize, size)
      this.pageSize = size
      savePageSize(LIST_ID, size)
      return this.load()
    },
  },
})
