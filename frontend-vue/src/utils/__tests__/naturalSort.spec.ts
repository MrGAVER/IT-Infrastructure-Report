import { describe, expect, it } from 'vitest'
import { sortNaturally } from '../naturalSort'

// UI-13 (ревью merge/review-2158-executors): «ИС 1, ИС 10, ИС 11 … ИС 2», «… 0, 12, 18, 24, 6» — сервер сортирует по строке.

const names = (items: { n: string | null }[]) => items.map((i) => i.n)
const rows = (...values: (string | null)[]) => values.map((n) => ({ n }))
const key = (item: { n: string | null }) => item.n

describe('sortNaturally', () => {
  it('числа внутри названия сравниваются как числа: «ИС 2» раньше «ИС 10»', () => {
    const sorted = sortNaturally(rows('ИС 10', 'ИС 2', 'ИС 1', 'ИС 11', 'ИС 0'), key)

    expect(names(sorted)).toEqual(['ИС 0', 'ИС 1', 'ИС 2', 'ИС 10', 'ИС 11'])
  })

  it('имена вида dev-6 / dev-12 / sw-core-…-0 упорядочиваются по префиксу, затем по числу', () => {
    const sorted = sortNaturally(rows('dev-12', 'sw-core-rack-12-unit-40-0', 'dev-6', 'dev-1', 'sw-core-rack-12-unit-40-18'), key)

    expect(names(sorted)).toEqual(['dev-1', 'dev-6', 'dev-12', 'sw-core-rack-12-unit-40-0', 'sw-core-rack-12-unit-40-18'])
  })

  it('регистр и кириллица: сравнение без учёта регистра, «ё» рядом с «е»', () => {
    const sorted = sortNaturally(rows('Яндекс', 'алфавит', 'Ёлка', 'Бета'), key)

    expect(names(sorted)).toEqual(['алфавит', 'Бета', 'Ёлка', 'Яндекс'])
  })

  it('записи без названия: по умолчанию в конце, с emptyFirst — в начале (как system_name IS NULL DESC на сервере)', () => {
    const input = rows('b-2', null, 'b-10', '   ', 'a-1')

    expect(names(sortNaturally(input, key))).toEqual(['a-1', 'b-2', 'b-10', null, '   '])
    expect(names(sortNaturally(input, key, { emptyFirst: true }))).toEqual([null, '   ', 'a-1', 'b-2', 'b-10'])
  })

  it('устойчива: записи с одинаковым названием сохраняют серверный порядок', () => {
    const input = [
      { n: 'sw-1', id: 'c' },
      { n: 'sw-1', id: 'a' },
      { n: 'sw-1', id: 'b' },
    ]

    expect(sortNaturally(input, key).map((i) => i.id)).toEqual(['c', 'a', 'b'])
  })

  it('не меняет исходный массив и корректно работает на пустом списке', () => {
    const input = rows('ИС 10', 'ИС 2')
    const copy = [...input]

    sortNaturally(input, key)

    expect(input).toEqual(copy)
    expect(sortNaturally([], key)).toEqual([])
  })
})
