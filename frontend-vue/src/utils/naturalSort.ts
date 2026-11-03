// Естественная сортировка списков по названию (UI-13 ревью merge/review-2158-executors).
//
// backend отдаёт устройства и информационные системы, отсортированные SQL-ом по строке (ORDER BY name), поэтому «ИС 10» и «ИС 11»
// шли раньше «ИС 2», а «dev-12» раньше «dev-6». Числа внутри названия сравниваются как числа тем же collator'ом, что и справочники
// (RU_COLLATOR в stores/catalogs.ts: кириллица без учёта регистра + numeric), поэтому порядок во всех списках приложения одинаков.
import { RU_COLLATOR } from '../stores/catalogs'

export interface NaturalSortOptions {
  /** Записи без названия (null, undefined, пустая строка или пробелы) идут первыми — как в SQL-сортировке backend
   * (`system_name IS NULL DESC`) для устройств без системного имени. По умолчанию — в конце списка. */
  emptyFirst?: boolean
}

/**
 * Новый массив, отсортированный по ключу естественным порядком. Исходный массив не меняется; сортировка устойчива — записи с
 * одинаковым названием сохраняют порядок, в котором их отдал сервер.
 *
 * @example
 * sortNaturally([{ n: 'ИС 10' }, { n: 'ИС 2' }, { n: null }], (x) => x.n, { emptyFirst: true })
 * // → [{ n: null }, { n: 'ИС 2' }, { n: 'ИС 10' }]
 */
export function sortNaturally<T>(items: readonly T[], getKey: (item: T) => string | null | undefined, options: NaturalSortOptions = {}): T[] {
  const { emptyFirst = false } = options
  // Ключи считаются один раз на запись, а не на каждое сравнение: на списке в тысячи записей это экономит порядка n·log n вызовов.
  const keyed = items.map((item, index) => ({ item, index, key: (getKey(item) ?? '').trim() }))
  keyed.sort((a, b) => {
    const aEmpty = a.key === ''
    const bEmpty = b.key === ''
    if (aEmpty !== bEmpty) return aEmpty === emptyFirst ? -1 : 1
    return RU_COLLATOR.compare(a.key, b.key) || a.index - b.index
  })
  return keyed.map((entry) => entry.item)
}
