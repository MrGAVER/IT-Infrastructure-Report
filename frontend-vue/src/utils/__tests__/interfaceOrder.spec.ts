import { describe, expect, it } from 'vitest'
import { moveRow, swapIndexes } from '../interfaceOrder'

describe('moveRow', () => {
  it('поднимает строку на одну позицию вверх и не меняет исходный массив', () => {
    const rows = ['a', 'b', 'c']
    expect(moveRow(rows, 2, -1)).toEqual(['a', 'c', 'b'])
    expect(rows).toEqual(['a', 'b', 'c'])
  })

  it('опускает строку на одну позицию вниз', () => {
    expect(moveRow(['a', 'b', 'c'], 0, 1)).toEqual(['b', 'a', 'c'])
  })

  it('на границах списка двигать некуда — null', () => {
    expect(moveRow(['a', 'b'], 0, -1)).toBeNull()
    expect(moveRow(['a', 'b'], 1, 1)).toBeNull()
    expect(moveRow(['a'], 0, 1)).toBeNull()
  })

  it('индекс вне списка и нецелый индекс — null', () => {
    expect(moveRow(['a', 'b'], 5, -1)).toBeNull()
    expect(moveRow(['a', 'b'], -1, 1)).toBeNull()
    expect(moveRow(['a', 'b'], 0.5, 1)).toBeNull()
  })
})

describe('swapIndexes', () => {
  it('переносит индексы обмениваемых строк, остальные не трогает', () => {
    expect([...swapIndexes(new Set([0, 3]), 0, 1)].sort()).toEqual([1, 3])
    expect([...swapIndexes(new Set([1, 2]), 1, 2)].sort()).toEqual([1, 2])
    expect([...swapIndexes(new Set([4]), 0, 1)]).toEqual([4])
  })

  it('пустое множество остаётся пустым', () => {
    expect(swapIndexes(new Set(), 0, 1).size).toBe(0)
  })
})
