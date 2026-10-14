// Перестановка портов в блоке «Список интерфейсов» формы устройства (стрелки вверх/вниз).
// Порядок строк массива — это и есть порядок, заданный пользователем: он уходит на сервер вместе со списком
// портов (PUT /devices/{id}/interfaces → device_interfaces.sort_order) и сохраняется. Чистые функции без Vue —
// чтобы правило перестановки и пересчёт выбранных индексов проверялись без монтирования редактора.

/** Копия списка, в которой элемент `index` поменян местами с соседним в направлении `direction` (-1 — вверх, +1 — вниз).
 * Возвращает null, если двигать некуда (первая строка вверх, последняя вниз) или индекс вне списка. Исходный массив не меняется. */
export function moveRow<T>(rows: readonly T[], index: number, direction: -1 | 1): T[] | null {
  const target = index + direction
  if (!Number.isInteger(index) || index < 0 || index >= rows.length || target < 0 || target >= rows.length) return null
  const result = [...rows]
  ;[result[index], result[target]] = [result[target], result[index]]
  return result
}

/** Индексы строк после обмена местами строк `a` и `b`: состояние, привязанное к позиции в списке (отмеченные галочкой,
 * развёрнутые строки), должно ехать вместе со строкой, а не оставаться на месте и «переходить» к другому порту. */
export function swapIndexes(indexes: ReadonlySet<number>, a: number, b: number): Set<number> {
  return new Set([...indexes].map((i) => (i === a ? b : i === b ? a : i)))
}
