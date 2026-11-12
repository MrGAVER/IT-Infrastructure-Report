// Двоичная куча по числовому ключу (B-08: вынесена из diagramEdgeRouting.ts, чтобы проверяться отдельно). Нужна поиску пути A*: он держит
// в куче тысячи состояний, а сортировка массива на каждом шаге была бы квадратичной.
//
// Ключ — приоритет (меньше — раньше), значение — целое число (номер состояния); при равных ключах порядок выдачи не гарантируется.

/** Двоичная куча по ключу: A* держит в ней тысячи состояний, а сортировка массива на каждом шаге была бы квадратичной. */
export class MinHeap {
  private keys: number[] = []
  private values: number[] = []

  get size(): number {
    return this.keys.length
  }

  push(key: number, value: number): void {
    const keys = this.keys
    const values = this.values
    let i = keys.length
    keys.push(key)
    values.push(value)
    while (i > 0) {
      const parent = (i - 1) >> 1
      if (keys[parent] <= key) break
      keys[i] = keys[parent]
      values[i] = values[parent]
      i = parent
    }
    keys[i] = key
    values[i] = value
  }

  /** Ключ ближайшего элемента, не извлекая его; `undefined`, если куча пуста. */
  peekKey(): number | undefined {
    return this.keys[0]
  }

  /**
   * Извлекает значение с наименьшим ключом; `undefined`, если куча пуста — как у `Array.prototype.pop`.
   *
   * ИБ-04 (ревью merge/review-r3-executors): раньше тип возврата был `number`, а на пустой куче метод молча отдавал `undefined` (`values[0]`) и
   * портил массивы (`keys.pop()` на пустом массиве). Цикл A* проверял `size`, поэтому на деле это не проявлялось, но класс вынесен как
   * самостоятельный, и любой другой вызывающий получил бы `undefined` под видом числа. Теперь тип честный, и компилятор требует проверки.
   */
  pop(): number | undefined {
    const keys = this.keys
    const values = this.values
    if (keys.length === 0) return undefined
    const top = values[0]
    const lastKey = keys.pop() as number
    const lastValue = values.pop() as number
    const n = keys.length
    if (n > 0) {
      let i = 0
      for (;;) {
        let child = 2 * i + 1
        if (child >= n) break
        if (child + 1 < n && keys[child + 1] < keys[child]) child++
        if (keys[child] >= lastKey) break
        keys[i] = keys[child]
        values[i] = values[child]
        i = child
      }
      keys[i] = lastKey
      values[i] = lastValue
    }
    return top
  }
}
