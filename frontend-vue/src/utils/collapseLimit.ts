// Порог сворачивания длинных списков в формах (блоки «VLAN устройства» и «Открытые порты»). Один общий порог,
// который пользователь задаёт в «Настройках» (stores/formPreferences.ts). Вынесено из utils/deviceVlans.ts,
// когда у порога появился второй потребитель.

/** Порог по умолчанию: блок сворачивается, когда в нём БОЛЬШЕ стольких строк. */
export const DEFAULT_COLLAPSE_ROWS = 10
export const MIN_COLLAPSE_ROWS = 1
export const MAX_COLLAPSE_ROWS = 1000

function toNumber(value: unknown): number {
  return typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : NaN
}

/**
 * Приводит значение порога к допустимому целому (MIN..MAX). Нечисловое и пустое заменяется значением по
 * умолчанию, дробное округляется вниз, выход за границы — в границы: испорченное значение в хранилище не
 * должно ломать форму.
 *
 * @example
 * normalizeCollapseLimit('15')  // 15
 * normalizeCollapseLimit('abc') // 10
 * normalizeCollapseLimit(0)     // 1
 */
export function normalizeCollapseLimit(value: unknown): number {
  const parsed = toNumber(value)
  if (!Number.isFinite(parsed)) return DEFAULT_COLLAPSE_ROWS
  return Math.min(MAX_COLLAPSE_ROWS, Math.max(MIN_COLLAPSE_ROWS, Math.floor(parsed)))
}

/** Явная проверка для поля ввода: подходит ли значение БЕЗ молчаливой подмены (в отличие от normalize). */
export function isValidCollapseLimit(value: unknown): boolean {
  const parsed = toNumber(value)
  return Number.isInteger(parsed) && parsed >= MIN_COLLAPSE_ROWS && parsed <= MAX_COLLAPSE_ROWS
}

/** Свёрнут ли блок по умолчанию: строк строго больше порога. */
export function exceedsCollapseLimit(rowCount: number, limit: number): boolean {
  return rowCount > limit
}
