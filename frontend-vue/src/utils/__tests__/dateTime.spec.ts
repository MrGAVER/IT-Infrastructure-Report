import { describe, it, expect } from 'vitest'
import { formatServerDate, formatServerDateTime, parseServerDate } from '../dateTime'

// Набор намеренно написан так, чтобы проходить в любом поясе, но падать при разборе
// `new Date(строка_без_смещения)` везде, кроме UTC: запускайте также с TZ=Europe/Minsk и TZ=UTC.
const DATE_TIME = { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' } as const

describe('parseServerDate', () => {
  it('строка без смещения — это UTC: тот же момент, что и с +00:00 и с Z', () => {
    const naive = parseServerDate('2026-10-19T18:08:54')
    expect(naive.toISOString()).toBe('2026-10-19T18:08:54.000Z')
    expect(parseServerDate('2026-10-19T18:08:54+00:00').getTime()).toBe(naive.getTime())
    expect(parseServerDate('2026-10-19T18:08:54Z').getTime()).toBe(naive.getTime())
  })

  it('микросекунды без смещения (формат серверной сериализации) тоже считаются UTC', () => {
    expect(parseServerDate('2026-10-19T18:08:54.336386').toISOString()).toBe('2026-10-19T18:08:54.336Z')
  })

  it('смещение, отличное от нуля, учитывается и не затирается', () => {
    expect(parseServerDate('2026-10-19T21:08:54+03:00').toISOString()).toBe('2026-10-19T18:08:54.000Z')
    expect(parseServerDate('2026-10-19T15:08:54-0300').toISOString()).toBe('2026-10-19T18:08:54.000Z')
  })

  it('чистая дата YYYY-MM-DD не сдвигается: это UTC-полночь', () => {
    expect(parseServerDate('2026-10-19').toISOString()).toBe('2026-10-19T00:00:00.000Z')
  })

  it('разделитель «пробел» вместо T обрабатывается как UTC', () => {
    expect(parseServerDate('2026-10-19 18:08:54').toISOString()).toBe('2026-10-19T18:08:54.000Z')
  })

  it('мусор даёт Invalid Date, а не исключение', () => {
    expect(Number.isNaN(parseServerDate('вчера').getTime())).toBe(true)
  })
})

describe('formatServerDateTime', () => {
  it('значения без смещения и с +00:00 показываются одинаково и равны UTC-моменту в локальном поясе', () => {
    const expected = new Date(Date.UTC(2026, 9, 19, 18, 8, 54)).toLocaleString('ru-RU', DATE_TIME)
    expect(formatServerDateTime('2026-10-19T18:08:54')).toBe(expected)
    expect(formatServerDateTime('2026-10-19T18:08:54.336386')).toBe(expected)
    expect(formatServerDateTime('2026-10-19T18:08:54+00:00')).toBe(expected)
  })

  it('пусто → «—»; нераспознанная строка возвращается как есть', () => {
    expect(formatServerDateTime(null)).toBe('—')
    expect(formatServerDateTime(undefined)).toBe('—')
    expect(formatServerDateTime('')).toBe('—')
    expect(formatServerDateTime('не дата')).toBe('не дата')
  })

  it('чистая дата показывается как дата, без «00:00» и без сдвига дня', () => {
    expect(formatServerDateTime('2026-10-19')).toBe('19.10.2026')
  })
})

describe('formatServerDate', () => {
  it('чистая дата не сдвигается на предыдущий день в поясах западнее Гринвича', () => {
    expect(formatServerDate('2026-10-19')).toBe('19.10.2026')
  })

  it('дата из значения без смещения считается по UTC-моменту в локальном поясе', () => {
    const expected = new Date(Date.UTC(2026, 9, 19, 18, 8, 54)).toLocaleDateString('ru-RU')
    expect(formatServerDate('2026-10-19T18:08:54')).toBe(expected)
    expect(formatServerDate('2026-10-19T18:08:54+00:00')).toBe(expected)
  })

  it('пусто → «—»; нераспознанная строка возвращается как есть', () => {
    expect(formatServerDate(null)).toBe('—')
    expect(formatServerDate('не дата')).toBe('не дата')
  })
})
