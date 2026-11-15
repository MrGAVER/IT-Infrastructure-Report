import { describe, it, expect } from 'vitest'
import { describeRetention, parseRetentionDays } from '../auditRetention'

describe('describeRetention', () => {
  it('0 — «не ограничен», остальное — число дней', () => {
    expect(describeRetention(0)).toBe('не ограничен')
    expect(describeRetention(90)).toBe('90 дн.')
  })
})

describe('parseRetentionDays', () => {
  it.each([
    ['0', 0],
    ['1', 1],
    ['  90 ', 90],
    ['3650', 3650],
    [30, 30],
  ])('%j — срок %i', (raw, days) => {
    expect(parseRetentionDays(raw, 3650)).toEqual({ ok: true, days })
  })

  it.each(['', '   ', '-1', '3.5', '1e2', 'abc', '30 дней', '٣٠'])('%j — ошибка ввода', (raw) => {
    expect(parseRetentionDays(raw, 3650).ok).toBe(false)
  })

  it('больше верхней границы — ошибка с этой границей в тексте; ровно граница допустима', () => {
    const over = parseRetentionDays('3651', 3650)
    expect(over).toEqual({ ok: false, error: 'Срок хранения не может быть больше 3650 дн.' })
    expect(parseRetentionDays('3650', 3650).ok).toBe(true)
  })

  it('граница берётся из ответа сервера, а не зашита', () => {
    expect(parseRetentionDays('400', 365).ok).toBe(false)
  })
})
