// B-08: MinHeap вынесена из diagramEdgeRouting.ts в отдельный модуль и впервые проверяется напрямую (раньше — только косвенно, через
// результаты поиска пути): от порядка выдачи зависит, найдёт ли A* кратчайший маршрут.
import { describe, expect, it } from 'vitest'
import { MinHeap } from '../minHeap'

/** Воспроизводимый псевдослучайный генератор (LCG): тест не должен зависеть от Math.random. */
function lcg(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    return state / 2 ** 32
  }
}

function drain(heap: MinHeap): number[] {
  const result: number[] = []
  for (let value = heap.pop(); value !== undefined; value = heap.pop()) result.push(value)
  return result
}

describe('MinHeap', () => {
  it('выдаёт значения в порядке возрастания ключей, независимо от порядка добавления', () => {
    const heap = new MinHeap()
    for (const [key, value] of [
      [5, 50],
      [1, 10],
      [4, 40],
      [2, 20],
      [3, 30],
    ] as const) {
      heap.push(key, value)
    }

    expect(drain(heap)).toEqual([10, 20, 30, 40, 50])
  })

  it('size растёт на push, убывает на pop; пустая куча имеет размер 0', () => {
    const heap = new MinHeap()
    expect(heap.size).toBe(0)

    heap.push(2, 7)
    heap.push(1, 8)
    expect(heap.size).toBe(2)
    expect(heap.pop()).toBe(8)
    expect(heap.size).toBe(1)
    expect(heap.pop()).toBe(7)
    expect(heap.size).toBe(0)
  })

  it('ИБ-04: пустая куча отдаёт undefined на pop и peekKey и не портит внутреннее состояние', () => {
    const heap = new MinHeap()
    expect(heap.pop()).toBeUndefined()
    expect(heap.peekKey()).toBeUndefined()
    expect(heap.size).toBe(0)

    // После лишнего pop куча работает как новая: раньше keys.pop() на пустом массиве и values[0] оставляли её в неопределённом состоянии.
    heap.push(5, 50)
    heap.push(1, 10)
    expect(heap.size).toBe(2)
    expect(drain(heap)).toEqual([10, 50])
    expect(heap.pop()).toBeUndefined()
    expect(heap.size).toBe(0)
  })

  it('ИБ-04: peekKey показывает наименьший ключ, не извлекая элемент', () => {
    const heap = new MinHeap()
    heap.push(7, 70)
    heap.push(3, 30)
    heap.push(9, 90)
    expect(heap.peekKey()).toBe(3)
    expect(heap.size).toBe(3)
    expect(heap.pop()).toBe(30)
    expect(heap.peekKey()).toBe(7)
  })

  it('равные ключи не теряются: каждое значение выдаётся ровно один раз', () => {
    const heap = new MinHeap()
    for (const value of [1, 2, 3, 4]) heap.push(10, value)
    heap.push(5, 99)

    const drained = drain(heap)

    expect(drained[0]).toBe(99)
    expect(drained.slice(1).sort()).toEqual([1, 2, 3, 4])
  })

  it('отрицательные и дробные ключи упорядочиваются как числа, а не как строки', () => {
    const heap = new MinHeap()
    heap.push(10, 1)
    heap.push(-3.5, 2)
    heap.push(2, 3)
    heap.push(-10, 4)
    heap.push(0.25, 5)

    expect(drain(heap)).toEqual([4, 2, 5, 3, 1])
  })

  it('чередование push и pop (как у A*: раскрытая вершина добавляет новые) сохраняет порядок', () => {
    const heap = new MinHeap()
    heap.push(5, 5)
    heap.push(3, 3)
    expect(heap.pop()).toBe(3)
    heap.push(1, 1)
    heap.push(4, 4)
    expect(heap.pop()).toBe(1)
    expect(heap.pop()).toBe(4)
    heap.push(2, 2)
    expect(heap.pop()).toBe(2)
    expect(heap.pop()).toBe(5)
    expect(heap.size).toBe(0)
  })

  it('5 000 случайных ключей выходят отсортированными (значение = ключ)', () => {
    const next = lcg(20260610)
    const heap = new MinHeap()
    const keys: number[] = []
    for (let i = 0; i < 5000; i++) {
      const key = Math.floor(next() * 1000) // много повторов
      keys.push(key)
      heap.push(key, key)
    }

    expect(drain(heap)).toEqual(keys.sort((a, b) => a - b))
  })
})
