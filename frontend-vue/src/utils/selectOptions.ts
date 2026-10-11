import { RU_COLLATOR } from '../stores/catalogs'

/**
 * Сортирует опции выпадающего списка (SearchableSelect и т.п.) по подписи — единое правило
 * «выпадающие списки отсортированы» для всех мест, где порядок источника не годится (например,
 * devicesStore.all приходит в порядке ответа API, а справочники отсортированы в сторе по полям,
 * не совпадающим с показываемой подписью).
 *
 * Сравнение — общий RU_COLLATOR (регистр не важен, числа натурально: «srv-2» раньше «srv-10»,
 * кириллица раньше латиницы). Равные подписи различаются по value, чтобы результат не зависел от
 * порядка во входных данных. Возвращает НОВЫЙ массив (вход не мутируется); дополнительные поля
 * опций (group, searchText) сохраняются как есть.
 *
 * @example
 * const options = sortOptionsByLabel(devices.map((d) => ({ value: d.id, label: d.system_name || d.serial_number })))
 */
export function sortOptionsByLabel<T extends { value: string; label: string }>(options: readonly T[]): T[] {
  return [...options].sort((a, b) => RU_COLLATOR.compare(a.label, b.label) || (a.value < b.value ? -1 : a.value > b.value ? 1 : 0))
}
