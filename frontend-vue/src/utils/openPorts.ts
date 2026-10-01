// Чистые функции над черновыми строками открытых портов (OpenPortDraftRow). Номер порта в
// строке не хранится — он выводится из выбранной записи справочника (protocol_catalog_id →
// ProtocolPortCatalogEntry.port, см. OpenPortListEditor.vue), поэтому и сортировка, и поиск
// повторов принимают каталог параметром. Вынесено из компонента ради тестов без монтирования
// и чтобы форма (проверка при сохранении) и редактор (подсветка строк) использовали одно правило.
import type { OpenPortDraftRow, ProtocolPortCatalogEntry } from '../api/types'

function portIndex(catalog: readonly ProtocolPortCatalogEntry[]): Map<string, number> {
  return new Map(catalog.map((entry) => [entry.id, entry.port]))
}

/** Копия списка, отсортированная по номеру порта по возрастанию. Строки без выбранной (или не
 * найденной в каталоге) записи справочника — в конце, чтобы только что добавленная пустая строка
 * оставалась внизу списка. Сортировка стабильна (Array.prototype.sort), исходный массив не меняется. */
export function sortOpenPortRows(rows: readonly OpenPortDraftRow[], catalog: readonly ProtocolPortCatalogEntry[]): OpenPortDraftRow[] {
  const ports = portIndex(catalog)
  const portOf = (row: OpenPortDraftRow): number => ports.get(row.protocol_catalog_id) ?? Number.POSITIVE_INFINITY
  return [...rows].sort((a, b) => {
    const pa = portOf(a)
    const pb = portOf(b)
    // Явное сравнение вместо pa - pb: Infinity - Infinity даёт NaN.
    return pa === pb ? 0 : pa < pb ? -1 : 1
  })
}

/** Индексы строк, чей номер порта встречается в списке более одного раза. Повтор определяется
 * именно по номеру порта: разные записи справочника с одним портом (80/HTTP и 80/HTTP-Proxy) и
 * один порт с разным транспортом (TCP и UDP) — тоже повтор. Строки без записи справочника не учитываются. */
export function duplicateRowIndexes(rows: readonly OpenPortDraftRow[], catalog: readonly ProtocolPortCatalogEntry[]): Set<number> {
  const ports = portIndex(catalog)
  const byPort = new Map<number, number[]>()
  rows.forEach((row, index) => {
    const port = ports.get(row.protocol_catalog_id)
    if (port === undefined) return
    const indexes = byPort.get(port)
    if (indexes) indexes.push(index)
    else byPort.set(port, [index])
  })
  const result = new Set<number>()
  for (const indexes of byPort.values()) {
    if (indexes.length > 1) indexes.forEach((i) => result.add(i))
  }
  return result
}

/** Повторяющиеся номера портов (каждый один раз), по возрастанию — для текста ошибки. */
export function duplicatePortNumbers(rows: readonly OpenPortDraftRow[], catalog: readonly ProtocolPortCatalogEntry[]): number[] {
  const ports = portIndex(catalog)
  const numbers = new Set<number>()
  for (const i of duplicateRowIndexes(rows, catalog)) {
    const port = ports.get(rows[i].protocol_catalog_id)
    if (port !== undefined) numbers.add(port)
  }
  return [...numbers].sort((a, b) => a - b)
}
