// Разбор и форматирование даты-времени, пришедшей с бэкенда.
//
// Бэкенд хранит время как naive UTC (backend/app/services/serialization.py): часть полей отдаётся
// со смещением (`2026-10-19T18:08:54+00:00`), часть — без него (`2026-10-19T18:08:54.336386`).
// По спецификации ECMAScript дата-время БЕЗ смещения трактуется `new Date()` как ЛОКАЛЬНОЕ время
// браузера: `TZ=Europe/Minsk new Date('2026-10-19T18:08:54')` даёт 15:08:54Z, то есть журнал
// аудита и сессии показывали бы время со сдвигом на пояс пользователя. Поэтому все даты с сервера
// разбираются только через этот модуль — он устойчив к обоим форматам, до и после выравнивания
// формата на сервере.

/** Строка заканчивается смещением пояса: `Z`, `+00:00` или `+0000` (знак и две цифры часов обязательны). */
const HAS_TZ = /(?:Z|[+-]\d{2}:?\d{2})$/i
/** Чистая дата без времени (`2026-10-19`): `new Date()` уже трактует её как UTC-полночь. */
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/
/** Разделитель «пробел» вместо `T` (`2026-10-19 18:08:54`) — не гарантирован спецификацией ECMAScript. */
const SPACE_SEPARATED = /^(\d{4}-\d{2}-\d{2}) (?=\d)/

const DATE_TIME_FORMAT: Intl.DateTimeFormatOptions = {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
}

/**
 * ISO-строка с сервера → `Date`.
 *
 * Значение без смещения — это UTC (так хранит бэкенд), поэтому к нему добавляется `Z`.
 * Строки со смещением и чистые даты (`YYYY-MM-DD`) разбираются как есть.
 * Для нераспознаваемой строки возвращается `Invalid Date` (проверяйте `Number.isNaN(d.getTime())`).
 *
 * @example
 *   parseServerDate('2026-10-19T18:08:54').toISOString()       // '2026-10-19T18:08:54.000Z' в любом поясе
 *   parseServerDate('2026-10-19T18:08:54+00:00').toISOString() // тот же момент
 */
export function parseServerDate(iso: string): Date {
  const value = iso.trim().replace(SPACE_SEPARATED, '$1T')
  if (DATE_ONLY.test(value) || HAS_TZ.test(value)) return new Date(value)
  return new Date(`${value}Z`)
}

/**
 * Дата и время для таблиц: `19.10.2026, 21:08` (в поясе браузера).
 * Пустое значение → «—»; нераспознанная строка возвращается как есть, чтобы не терять данные.
 */
export function formatServerDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  if (DATE_ONLY.test(iso.trim())) return formatServerDate(iso)
  const d = parseServerDate(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('ru-RU', DATE_TIME_FORMAT)
}

/**
 * Только дата: `19.10.2026`. Для чистых дат (`YYYY-MM-DD`) используется UTC, иначе в поясах
 * западнее Гринвича календарный день сдвигался бы на предыдущий.
 */
export function formatServerDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const value = iso.trim()
  const d = parseServerDate(value)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('ru-RU', DATE_ONLY.test(value) ? { timeZone: 'UTC' } : undefined)
}
