import { describe, it, expect } from 'vitest'
import { deviceCountLabel, pluralRu } from '../plural'

describe('pluralRu / deviceCountLabel', () => {
  it.each([
    [0, '0 устройств'],
    [1, '1 устройство'],
    [2, '2 устройства'],
    [4, '4 устройства'],
    [5, '5 устройств'],
    [11, '11 устройств'],
    [12, '12 устройств'],
    [14, '14 устройств'],
    [21, '21 устройство'],
    [22, '22 устройства'],
    [111, '111 устройств'],
    [112, '112 устройств'],
  ])('%i → «%s»', (n, expected) => {
    expect(deviceCountLabel(n)).toBe(expected)
  })

  it('формы подставляются в том порядке, в котором переданы', () => {
    expect(pluralRu(3, ['стек', 'стека', 'стеков'])).toBe('стека')
  })
})
