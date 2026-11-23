import { describe, it, expect } from 'vitest'
import { DEFAULT_FILTERS, filterFindings, hasActiveFilters, sheetsWithFindings } from '../consistencyFilter'
import type { ConsistencyFilters } from '../consistencyFilter'
import { finding } from '../../__tests__/consistencyFixtures'

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
