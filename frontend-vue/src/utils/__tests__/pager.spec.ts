import { describe, it, expect } from 'vitest'
import { pagerItems } from '../pager'

describe('pagerItems', () => {
  it('немного страниц — все подряд', () => {
    expect(pagerItems(1, 1)).toEqual([1])
    expect(pagerItems(2, 5)).toEqual([1, 2, 3, 4, 5])
  })

  it('нет страниц — пусто', () => {
    expect(pagerItems(1, 0)).toEqual([])
  })

  it('много страниц: первая, последняя и соседи текущей, между ними многоточие', () => {
    expect(pagerItems(1, 100)).toEqual([1, 2, '…', 100])
    expect(pagerItems(50, 100)).toEqual([1, '…', 49, 50, 51, '…', 100])
    expect(pagerItems(100, 100)).toEqual([1, '…', 99, 100])
  })

  it('пропуск в одну страницу показывается самой страницей, а не многоточием', () => {
    expect(pagerItems(4, 100)).toEqual([1, 2, 3, 4, 5, '…', 100])
    expect(pagerItems(97, 100)).toEqual([1, '…', 96, 97, 98, 99, 100])
  })

  it('число элементов не зависит от общего числа страниц', () => {
    expect(pagerItems(5000, 10000).length).toBeLessThanOrEqual(7)
  })
})
