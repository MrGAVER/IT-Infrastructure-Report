import { describe, it, expect } from 'vitest'
import { filterBySearch, matchesSearchTokens, normalizeSearchText, searchTokens } from '../textSearch'

describe('textSearch', () => {
  it('нормализует регистр, «ё» и пробелы по краям', () => {
    expect(normalizeSearchText('  ЁлкА  ')).toBe('елка')
  })

  it('делит запрос на слова; пустой и пробельный запрос дают пустой список', () => {
    expect(searchTokens('  Cisco   ядро ')).toEqual(['cisco', 'ядро'])
    expect(searchTokens('')).toEqual([])
    expect(searchTokens('   ')).toEqual([])
  })

  it('запись подходит, только если каждое слово найдено хотя бы в одном тексте', () => {
    const tokens = searchTokens('cisco ядр')
    expect(matchesSearchTokens(tokens, ['Стек ядра', 'Cisco Catalyst'])).toBe(true)
    expect(matchesSearchTokens(tokens, ['Стек ядра', 'Huawei'])).toBe(false)
  })

  it('игнорирует пустые значения и не падает на null/undefined', () => {
    expect(matchesSearchTokens(['а'], [null, undefined, '', 'Аудит'])).toBe(true)
    expect(matchesSearchTokens(['а'], [null, undefined, ''])).toBe(false)
  })

  it('«ё» и «е» не различаются в запросе и в тексте', () => {
    expect(matchesSearchTokens(searchTokens('берёзка'), ['Березка'])).toBe(true)
    expect(matchesSearchTokens(searchTokens('березка'), ['Берёзка'])).toBe(true)
  })

  it('filterBySearch: пустой запрос возвращает тот же массив, непустой — отфильтрованный', () => {
    const items = [{ n: 'Сервер' }, { n: 'Коммутатор' }]
    expect(filterBySearch(items, '  ', (i) => [i.n])).toBe(items)
    expect(filterBySearch(items, 'ком', (i) => [i.n])).toEqual([{ n: 'Коммутатор' }])
    expect(filterBySearch(items, 'нет такого', (i) => [i.n])).toEqual([])
  })
})
