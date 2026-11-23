import { describe, expect, it } from 'vitest'
import { describeInterval, formatFileSize, parseIntervalHours, parseKeepCount } from '../backupSettings'

const LIMITS = { min: 1, max: 8784 }

describe('parseIntervalHours', () => {
  it.each([
    ['24', 24],
    ['0', 0],
    ['1', 1],
    ['1,5', 1.5],
    ['1.5', 1.5],
    [' 6 ', 6],
    [8784, 8784],
  ])('принимает «%s»', (raw, value) => {
    expect(parseIntervalHours(raw, LIMITS)).toEqual({ ok: true, value })
  })

  it.each([
    ['', 'Укажите интервал'],
    ['  ', 'Укажите интервал'],
    ['-1', 'число часов'],
    ['1e2', 'число часов'],
    ['часто', 'число часов'],
    ['1.2.3', 'число часов'],
    ['0.5', 'не меньше 1 ч'],
    ['8785', 'не может быть больше 8784'],
  ])('отклоняет «%s» с понятной ошибкой', (raw, text) => {
    const parsed = parseIntervalHours(raw, LIMITS)

    expect(parsed.ok).toBe(false)
    expect(!parsed.ok && parsed.error).toContain(text)
  })
})

describe('parseKeepCount', () => {
  it.each([
    ['1', 1],
    ['7', 7],
    [' 365 ', 365],
    [14, 14],
  ])('принимает «%s»', (raw, value) => {
    expect(parseKeepCount(raw, 365)).toEqual({ ok: true, value })
  })

  it.each([
    ['', 'Укажите'],
    ['0', 'не меньше одной'],
    ['366', 'не больше 365'],
    ['7.5', 'целое число'],
    ['-3', 'целое число'],
    ['семь', 'целое число'],
  ])('отклоняет «%s»', (raw, text) => {
    const parsed = parseKeepCount(raw, 365)

    expect(parsed.ok).toBe(false)
    expect(!parsed.ok && parsed.error).toContain(text)
  })
})

describe('подписи', () => {
  it('describeInterval: 0 — выключены, дробные — с запятой', () => {
    expect(describeInterval(0)).toBe('выключены')
    expect(describeInterval(24)).toBe('каждые 24 ч')
    expect(describeInterval(1.5)).toBe('каждые 1,5 ч')
  })

  it('formatFileSize: байты, килобайты, мегабайты', () => {
    expect(formatFileSize(512)).toBe('512 Б')
    expect(formatFileSize(1536)).toBe('1,5 КБ')
    expect(formatFileSize(12.3 * 1024 * 1024)).toBe('12,3 МБ')
  })
})
