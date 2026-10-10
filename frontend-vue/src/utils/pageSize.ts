// Количество строк на странице списков (устройства, ВМ, контейнеры, ИС, журнал аудита, подключения).
//
// У каждого списка свой размер по умолчанию (в таблицах разная высота строки), поэтому варианты
// выбора строятся от него: x1, x2, x4, x8 — и текущее значение по умолчанию всегда есть в списке.
// Выбор пользователя запоминается по каждому списку отдельно на сервере (личная настройка, как цветовая
// схема — stores/theme.ts, см. stores/preferences.ts); пока настройки не загружены или сервер недоступен,
// работает значение по умолчанию. Стор списка читает размер при создании: к этому моменту роутер уже
// дождался загрузки настроек (router/index.ts).
import { usePreferencesStore } from '../stores/preferences'

const MULTIPLIERS = [1, 2, 4, 8] as const

export function pageSizeOptionsFor(defaultSize: number): number[] {
  return MULTIPLIERS.map((m) => defaultSize * m)
}

export function isAllowedPageSize(size: number, defaultSize: number): boolean {
  return pageSizeOptionsFor(defaultSize).includes(size)
}

/** Сохранённый выбор, если он всё ещё допустим для списка; иначе размер по умолчанию (значение
 * могло испортиться или остаться от версии с другими вариантами). */
export function loadPageSize(listId: string, defaultSize: number): number {
  const stored = usePreferencesStore().user.page_sizes?.[listId]
  if (stored !== undefined && Number.isInteger(stored) && isAllowedPageSize(stored, defaultSize)) return stored
  return defaultSize
}

export function savePageSize(listId: string, size: number): void {
  void usePreferencesStore().saveUser({ page_sizes: { [listId]: size } })
}

/** Страница после смены размера: та, на которой окажется первая из видимых сейчас записей, —
 * пользователь не теряет место в списке (со страницы 3 по 8 записей, т.е. с 17-й, при 16 на
 * странице попадает на страницу 2, где 17-я — первая, а не на страницу 1 или 3). */
export function pageAfterSizeChange(page: number, oldSize: number, newSize: number): number {
  return Math.floor(((Math.max(1, page) - 1) * oldSize) / newSize) + 1
}
