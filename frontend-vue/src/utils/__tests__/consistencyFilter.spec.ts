import { describe, it, expect } from 'vitest'
import { DEFAULT_FILTERS, countActive, filterFindings, filtersFromQuery, hasActiveFilters, sheetsWithFindings } from '../consistencyFilter'
import type { ConsistencyFilters } from '../consistencyFilter'
import { approvedFinding, finding } from '../../__tests__/consistencyFixtures'

const filters = (patch: Partial<ConsistencyFilters>): ConsistencyFilters => ({ ...DEFAULT_FILTERS, ...patch })

const FINDINGS = [
  finding({ rule: 'invalid_ip', severity: 'error', entity_name: 'vm-1', message: 'vm-1: «10.0.0.1/24» не похоже на IP-адрес.' }),
  finding({ rule: 'vm_without_host', severity: 'warning', category: 'completeness', sheet: 4, entity_name: 'orphan', message: 'orphan: нет хоста.' }),
  finding({
    rule: 'device_identity_incomplete',
    severity: 'warning',
    category: 'completeness',
    sheet: 2,
    entity_name: 'SW-Core',
    message: 'SW-Core: нет модели.',
  }),
  finding({ rule: 'is_without_protocols', severity: 'info', category: 'completeness', sheet: 1, entity_name: 'ИС', message: 'ИС: нет протоколов.' }),
]

describe('filterFindings', () => {
  it('без фильтров возвращает всё', () => {
    expect(filterFindings(FINDINGS, DEFAULT_FILTERS)).toHaveLength(4)
  })

  it('фильтры действуют вместе: важность и категория сужают выборку, а не складываются', () => {
    const result = filterFindings(FINDINGS, filters({ severity: 'warning', category: 'completeness' }))
    expect(result.map((item) => item.entity_name)).toEqual(['orphan', 'SW-Core'])
  })

  it('лист и правило отбирают точно: лист 4 не захватывает лист 1 и наоборот', () => {
    expect(filterFindings(FINDINGS, filters({ sheet: 4 })).map((item) => item.rule)).toEqual(['vm_without_host'])
    expect(filterFindings(FINDINGS, filters({ rule: 'invalid_ip' }))).toHaveLength(1)
  })

  it('поиск — по имени объекта и по тексту, без учёта регистра и пробелов по краям', () => {
    expect(filterFindings(FINDINGS, filters({ search: '  sw-core ' }))).toHaveLength(1)
    expect(filterFindings(FINDINGS, filters({ search: 'ПРОТОКОЛОВ' }))).toHaveLength(1)
    expect(filterFindings(FINDINGS, filters({ search: 'нет такого' }))).toEqual([])
  })

  it('не меняет исходный список', () => {
    const copy = [...FINDINGS]
    filterFindings(FINDINGS, filters({ severity: 'error' }))
    expect(FINDINGS).toEqual(copy)
  })
})

describe('одобрение', () => {
  const mixed = [finding({ entity_name: 'активная' }), approvedFinding({ entity_name: 'одобренная' })]

  it('по умолчанию показываются только требующие внимания', () => {
    expect(filterFindings(mixed, DEFAULT_FILTERS).map((item) => item.entity_name)).toEqual(['активная'])
  })

  it('«Одобренные» и «Все» отбирают как ожидается', () => {
    expect(filterFindings(mixed, filters({ approval: 'approved' })).map((item) => item.entity_name)).toEqual(['одобренная'])
    expect(filterFindings(mixed, filters({ approval: 'all' }))).toHaveLength(2)
  })

  it('значение по умолчанию («требуют внимания») — не фильтр, а любое другое — фильтр', () => {
    expect(hasActiveFilters(filters({ approval: 'active' }))).toBe(false)
    expect(hasActiveFilters(filters({ approval: 'approved' }))).toBe(true)
    expect(hasActiveFilters(filters({ approval: 'all' }))).toBe(true)
  })
})

describe('countActive', () => {
  it('одобренные не входят в счётчики важности, а считаются отдельно', () => {
    const counts = countActive([
      finding({ severity: 'error' }),
      finding({ severity: 'warning' }),
      finding({ severity: 'warning' }),
      approvedFinding({ severity: 'error' }),
    ])
    expect(counts).toEqual({ error: 1, warning: 2, info: 0, total: 3, approved: 1 })
  })

  it('пустой список — нули', () => {
    expect(countActive([])).toEqual({ error: 0, warning: 0, info: 0, total: 0, approved: 0 })
  })
})

describe('hasActiveFilters', () => {
  it('значения по умолчанию и пустой поиск из пробелов — не фильтр', () => {
    expect(hasActiveFilters(DEFAULT_FILTERS)).toBe(false)
    expect(hasActiveFilters(filters({ search: '   ' }))).toBe(false)
  })

  it.each([{ search: 'x' }, { severity: 'error' as const }, { category: 'consistency' as const }, { sheet: 1 }, { rule: 'invalid_ip' }])(
    'любое изменённое поле (%o) — активный фильтр',
    (patch) => {
      expect(hasActiveFilters(filters(patch))).toBe(true)
    },
  )
})

describe('sheetsWithFindings', () => {
  it('номера листов без повторов и пустых, по возрастанию', () => {
    expect(sheetsWithFindings(FINDINGS)).toEqual([1, 2, 4])
  })
})

describe('filtersFromQuery', () => {
  it('допустимые параметры ссылки превращаются в фильтры', () => {
    expect(filtersFromQuery({ sheet: '2', category: 'completeness', severity: 'error', approval: 'all', rule: 'device_location_incomplete' })).toEqual({
      sheet: 2,
      category: 'completeness',
      severity: 'error',
      approval: 'all',
      rule: 'device_location_incomplete',
    })
  })

  it('пустая ссылка — без фильтров', () => {
    expect(filtersFromQuery({})).toEqual({})
  })

  it.each([
    [{ sheet: '5' }],
    [{ sheet: '0' }],
    [{ sheet: '2abc' }],
    [{ sheet: '' }],
    [{ category: 'другое' }],
    [{ severity: 'fatal' }],
    [{ approval: 'maybe' }],
    [{ rule: 'Не-код правила!' }],
    [{ rule: 'x'.repeat(101) }],
    [{ sheet: ['9'] }],
    [{ sheet: 2 }],
  ])('испорченное значение %o отбрасывается, а не превращается в пустую выборку', (query) => {
    expect(filtersFromQuery(query)).toEqual({})
  })

  it('повторяющийся параметр (?sheet=2&sheet=3) — берётся первое значение', () => {
    expect(filtersFromQuery({ sheet: ['2', '3'] })).toEqual({ sheet: 2 })
  })
})
