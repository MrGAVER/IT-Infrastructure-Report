// Количество строк на странице списков (устройства, ВМ, контейнеры, ИС, журнал аудита, подключения).
//
// У каждого списка свой размер по умолчанию (в таблицах разная высота строки), поэтому варианты
// выбора строятся от него: x1, x2, x4, x8 — и текущее значение по умолчанию всегда есть в списке.
// Выбор пользователя запоминается по каждому списку отдельно в localStorage (как цветовая схема —
// stores/theme.ts); если хранилище недоступно, работает значение по умолчанию.
const STORAGE_PREFIX = 'itr.pageSize.'
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
  try {
    const stored = Number(localStorage.getItem(STORAGE_PREFIX + listId))
    if (Number.isInteger(stored) && isAllowedPageSize(stored, defaultSize)) return stored
  } catch {
    /* localStorage недоступен (приватный режим и т.п.) — используем значение по умолчанию */
  }
  return defaultSize
}

export function savePageSize(listId: string, size: number): void {
  try {
    localStorage.setItem(STORAGE_PREFIX + listId, String(size))
  } catch {
    /* сохранить не удалось — не критично, просто не переживёт перезагрузку */
  }
}

/** Страница после смены размера: та, на которой окажется первая из видимых сейчас записей, —
 * пользователь не теряет место в списке (со страницы 3 по 8 записей, т.е. с 17-й, при 16 на
 * странице попадает на страницу 2, где 17-я — первая, а не на страницу 1 или 3). */
export function pageAfterSizeChange(page: number, oldSize: number, newSize: number): number {
  return Math.floor(((Math.max(1, page) - 1) * oldSize) / newSize) + 1
}
