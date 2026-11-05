// Количество строк на странице списков (устройства, ВМ, контейнеры, ИС, журнал аудита, подключения, VLAN, справочники).
//
// Для всех списков одна шкала — 10 / 25 / 50 / 100 (код-ревью main, F-09): именно такие значения пользователь ожидает увидеть в
// выборе, а размеры «под высоту строки» (6, 8, 12 и кратные им) выглядели случайными. По умолчанию — 10. Все значения шкалы не
// больше предела серверных списков (журнал аудита — 200).
// Выбор пользователя запоминается по каждому списку отдельно (личная настройка: с учётной записью на сервере,
// без аутентификации в браузере, как цветовая
// схема — stores/theme.ts, см. stores/preferences.ts); пока настройки не загружены или сервер недоступен,
// работает значение по умолчанию. Стор списка читает размер при создании: к этому моменту роутер уже
// дождался загрузки настроек (router/index.ts). Сохранённое значение вне шкалы (выбор из прежних вариантов 6/12/24/48, 8/16/32/64
// и т. п.) читается как «не выбрано», и список открывается с размером по умолчанию.
import { usePreferencesStore } from '../stores/preferences'

export const PAGE_SIZE_OPTIONS: readonly number[] = [10, 25, 50, 100]
export const DEFAULT_PAGE_SIZE: number = PAGE_SIZE_OPTIONS[0]

export function isAllowedPageSize(size: number): boolean {
  return PAGE_SIZE_OPTIONS.includes(size)
}

/** Сохранённый выбор, если он входит в шкалу; иначе размер по умолчанию (значение могло испортиться или остаться
 * от версии с другими вариантами). */
export function loadPageSize(listId: string): number {
  const stored = usePreferencesStore().user.page_sizes?.[listId]
  if (stored !== undefined && Number.isInteger(stored) && isAllowedPageSize(stored)) return stored
  return DEFAULT_PAGE_SIZE
}

export function savePageSize(listId: string, size: number): void {
  void usePreferencesStore().saveUser({ page_sizes: { [listId]: size } })
}

/** Страница после смены размера: та, на которой окажется первая из видимых сейчас записей, —
 * пользователь не теряет место в списке (со страницы 6 по 10 записей, т.е. с 51-й, при 25 на
 * странице попадает на страницу 3, где 51-я — первая, а не на страницу 2 или 6). */
export function pageAfterSizeChange(page: number, oldSize: number, newSize: number): number {
  return Math.floor(((Math.max(1, page) - 1) * oldSize) / newSize) + 1
}
