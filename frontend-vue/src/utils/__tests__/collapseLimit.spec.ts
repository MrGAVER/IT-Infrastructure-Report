import { describe, it, expect } from 'vitest'
import {
  DEFAULT_COLLAPSE_ROWS,
  MAX_COLLAPSE_ROWS,
  MIN_COLLAPSE_ROWS,
  exceedsCollapseLimit,
  isValidCollapseLimit,
  normalizeCollapseLimit,
} from '../collapseLimit'

describe('порог сворачивания', () => {
  it('значения по умолчанию: порог 10, допустимо 1..1000', () => {
    expect(DEFAULT_COLLAPSE_ROWS).toBe(10)
    expect(MIN_COLLAPSE_ROWS).toBe(1)
    expect(MAX_COLLAPSE_ROWS).toBe(1000)
  })

  it('exceedsCollapseLimit — строго «больше» порога: ровно на пороге блок не сворачивается', () => {
    expect(exceedsCollapseLimit(10, 10)).toBe(false)
    expect(exceedsCollapseLimit(11, 10)).toBe(true)
    expect(exceedsCollapseLimit(0, 10)).toBe(false)
  })

  it('normalizeCollapseLimit: строка и число принимаются, дробное округляется вниз, выход за границы — в границы, мусор — значение по умолчанию', () => {
    expect(normalizeCollapseLimit('15')).toBe(15)
    expect(normalizeCollapseLimit(7.9)).toBe(7)
    expect(normalizeCollapseLimit(0)).toBe(1)
    expect(normalizeCollapseLimit(5000)).toBe(1000)
    for (const bad of ['', '   ', 'abc', null, undefined, NaN, Infinity]) expect(normalizeCollapseLimit(bad)).toBe(10)
  })

  it('isValidCollapseLimit принимает только целые из диапазона — без молчаливой подмены', () => {
    expect(isValidCollapseLimit('10')).toBe(true)
    expect(isValidCollapseLimit(1000)).toBe(true)
    for (const bad of ['', 'abc', '0', '1001', '2.5', -3, null, undefined]) expect(isValidCollapseLimit(bad)).toBe(false)
  })
})
