import { describe, it, expect } from 'vitest'
import { sortOptionsByLabel } from '../selectOptions'

const opt = (value: string, label: string) => ({ value, label })

describe('sortOptionsByLabel', () => {
  it('сортирует по подписи без учёта регистра, кириллица раньше латиницы (как RU_COLLATOR во всём приложении)', () => {
    const result = sortOptionsByLabel([opt('1', 'windows'), opt('2', 'Астра'), opt('3', 'Alpine'), opt('4', 'альт')])
    expect(result.map((o) => o.label)).toEqual(['альт', 'Астра', 'Alpine', 'windows'])
  })

  it('числа в подписях сравниваются натурально: srv-2 раньше srv-10', () => {
    const result = sortOptionsByLabel([opt('a', 'srv-10'), opt('b', 'srv-2'), opt('c', 'srv-1')])
    expect(result.map((o) => o.label)).toEqual(['srv-1', 'srv-2', 'srv-10'])
  })

  it('равные подписи упорядочиваются по value — результат не зависит от порядка во входных данных', () => {
    const forward = sortOptionsByLabel([opt('b', 'srv'), opt('a', 'srv'), opt('c', 'SRV')])
    const backward = sortOptionsByLabel([opt('c', 'SRV'), opt('a', 'srv'), opt('b', 'srv')])
    expect(forward.map((o) => o.value)).toEqual(['a', 'b', 'c'])
    expect(backward.map((o) => o.value)).toEqual(['a', 'b', 'c'])
  })

  it('не меняет исходный массив и сохраняет дополнительные поля опций (group, searchText)', () => {
    const source = [
      { value: '2', label: 'Б', group: 'Г1', searchText: 'x' },
      { value: '1', label: 'А', group: 'Г2' },
    ]
    const snapshot = JSON.parse(JSON.stringify(source))
    const result = sortOptionsByLabel(source)
    expect(source).toEqual(snapshot)
    expect(result).toEqual([
      { value: '1', label: 'А', group: 'Г2' },
      { value: '2', label: 'Б', group: 'Г1', searchText: 'x' },
    ])
  })

  it('пустой список — пустой результат', () => {
    expect(sortOptionsByLabel([])).toEqual([])
  })
})
