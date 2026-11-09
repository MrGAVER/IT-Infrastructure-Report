// Постраничный вывод клиентского списка: номер страницы, размер страницы (с запоминанием выбора для списка,
// как у остальных списков — utils/pageSize.ts) и срез текущей страницы. Для экранов, где список уже целиком
// в памяти и собственного стора со страницами нет (VLAN, «Другие справочники»); устройства, ВМ, контейнеры и
// ИС держат то же самое прямо в сторах.
//
// Страница всегда в пределах [1, pageCount]: если список стал короче (поиск, удаление записи, другой справочник),
// показывается последняя существующая страница, а не пустая таблица.
import { computed, ref, toValue, type MaybeRefOrGetter } from 'vue'
import { PAGE_SIZE_OPTIONS, isAllowedPageSize, loadPageSize, pageAfterSizeChange, savePageSize } from '../utils/pageSize'

export interface PagedListOptions {
  /** Идентификатор списка, под которым запоминается выбранный размер страницы (preferences.page_sizes). */
  listId: string
}

export function usePagedList<T>(source: MaybeRefOrGetter<readonly T[]>, options: PagedListOptions) {
  const { listId } = options

  const requestedPage = ref(1)
  const pageSize = ref(loadPageSize(listId))

  const total = computed(() => toValue(source).length)
  const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
  const page = computed(() => Math.min(Math.max(1, requestedPage.value), pageCount.value))
  const pageItems = computed(() => {
    const start = (page.value - 1) * pageSize.value
    return toValue(source).slice(start, start + pageSize.value)
  })
  /** Номера первой и последней записи на странице (1-based) для подписи «Показано 11–20 из 47»; на пустом списке — 0–0. */
  const rangeFrom = computed(() => (pageItems.value.length ? (page.value - 1) * pageSize.value + 1 : 0))
  const rangeTo = computed(() => (pageItems.value.length ? (page.value - 1) * pageSize.value + pageItems.value.length : 0))
  const pageSizeOptions = computed(() => [...PAGE_SIZE_OPTIONS])

  function setPage(next: number) {
    requestedPage.value = Math.min(Math.max(1, Math.trunc(next) || 1), pageCount.value)
  }

  /** Смена размера: остаёмся на странице с тем же первым видимым элементом, выбор запоминается; недопустимое значение игнорируется. */
  function setPageSize(size: number) {
    if (size === pageSize.value || !isAllowedPageSize(size)) return
    requestedPage.value = pageAfterSizeChange(page.value, pageSize.value, size)
    pageSize.value = size
    savePageSize(listId, size)
  }

  /** Вернуться на первую страницу — при смене условий отбора (поиск, другой справочник). */
  function resetPage() {
    requestedPage.value = 1
  }

  return { page, pageSize, pageSizeOptions, pageCount, pageItems, total, rangeFrom, rangeTo, setPage, setPageSize, resetPage }
}
