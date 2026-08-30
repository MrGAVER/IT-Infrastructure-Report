import { describe, it, expect } from 'vitest'
import { entityLabel, flattenEntityPaths, indexEntitiesByKey } from '../reportEntityPaths'
import type { ReportEntityMeta } from '../../api/types'

const entities: ReportEntityMeta[] = [
  {
    key: 'devices',
    label: 'Физические устройства',
    fields: [
      { name: 'system_name', label: 'Системное имя', type: 'String', is_foreign_key: false },
      { name: 'building_id', label: 'building_id', type: 'String', is_foreign_key: true },
    ],
    to_one: [{ name: 'building', target: 'buildings' }],
    to_many: [{ name: 'interfaces', target: 'interfaces' }],
  },
  {
    key: 'buildings',
    label: 'Здания',
    fields: [{ name: 'name', label: 'Наименование', type: 'String', is_foreign_key: false }],
    to_one: [{ name: 'unit', target: 'structural-units' }], // для проверки ограничения maxHops — 2-hop путь
    to_many: [],
  },
  {
    key: 'structural-units',
    label: 'Структурные единицы',
    fields: [{ name: 'name', label: 'Наименование', type: 'String', is_foreign_key: false }],
    to_one: [],
    to_many: [],
  },
  {
    key: 'interfaces',
    label: 'Интерфейсы',
    fields: [{ name: 'name', label: 'Наименование', type: 'String', is_foreign_key: false }],
    to_one: [],
    to_many: [{ name: 'ips', target: 'interface-ips' }],
  },
  {
    key: 'interface-ips',
    label: 'IP интерфейсов',
    fields: [{ name: 'ip_address', label: 'IP-адрес', type: 'String', is_foreign_key: false }],
    to_one: [],
    to_many: [],
  },
]
const byKey = indexEntitiesByKey(entities)

describe('indexEntitiesByKey / entityLabel', () => {
  it('строит индекс по key и резолвит подпись', () => {
    expect(entityLabel(byKey, 'devices')).toBe('Физические устройства')
  })

  it('неизвестный ключ — fallback на сам ключ (как rbLabel в vanilla)', () => {
    expect(entityLabel(byKey, 'unknown-entity')).toBe('unknown-entity')
  })
})

describe('flattenEntityPaths', () => {
  it('поля самой сущности — hops=0, without связей', () => {
    const paths = flattenEntityPaths(byKey, 'devices')
    const own = paths.filter((p) => p.hops === 0)
    expect(own.map((p) => p.path)).toEqual(['system_name', 'building_id'])
    expect(own.every((p) => !p.many)).toBe(true)
  })

  it('связь "к одному" (to_one) даёт путь через точку, подпись через " → "', () => {
    const paths = flattenEntityPaths(byKey, 'devices')
    const viaOne = paths.find((p) => p.path === 'building.name')
    expect(viaOne).toBeTruthy()
    expect(viaOne!.hops).toBe(1)
    expect(viaOne!.label).toBe('Здания → Наименование')
    expect(viaOne!.many).toBe(false)
  })

  it('две связи "к одному" подряд дают путь глубиной 2 (в пределах maxHops по умолчанию)', () => {
    const paths = flattenEntityPaths(byKey, 'devices')
    const viaTwo = paths.find((p) => p.path === 'building.unit.name')
    expect(viaTwo).toBeTruthy()
    expect(viaTwo!.hops).toBe(2)
    expect(viaTwo!.label).toBe('Здания → Структурные единицы → Наименование')
  })

  it('связь "ко многим" (to_many) добавляет "[]" в путь и помечает many=true', () => {
    const paths = flattenEntityPaths(byKey, 'devices')
    const viaMany = paths.find((p) => p.path === 'interfaces[].name')
    expect(viaMany).toBeTruthy()
    expect(viaMany!.many).toBe(true)
    expect(viaMany!.label).toBe('Интерфейсы (список) → Наименование')
  })

  it('не более одной связи "ко многим" на путь — после первой [] дальнейшие to_many не разворачиваются', () => {
    // interfaces[].ips[]... — второй to_many (ips) от interfaces НЕ должен попасть в результат,
    // т.к. manyUsed уже true после первого перехода через interfaces[].
    const paths = flattenEntityPaths(byKey, 'devices')
    expect(paths.some((p) => p.path.includes('ips'))).toBe(false)
  })

  it('maxHops=1 включает прямые связи (hops=1), но не двухшаговые (hops=2)', () => {
    const paths = flattenEntityPaths(byKey, 'devices', 1)
    expect(paths.every((p) => p.hops <= 1)).toBe(true)
    expect(paths.some((p) => p.path === 'building.name')).toBe(true) // hops=1 — остаётся
    expect(paths.some((p) => p.path === 'interfaces[].name')).toBe(true) // hops=1 через to_many — тоже остаётся
    expect(paths.some((p) => p.path === 'building.unit.name')).toBe(false) // hops=2 — обрезано
  })

  it('неизвестная сущность — пустой список без падения', () => {
    expect(flattenEntityPaths(byKey, 'no-such-entity')).toEqual([])
  })

  it('не дублирует одинаковые пути (seen-дедупликация)', () => {
    const paths = flattenEntityPaths(byKey, 'devices')
    const uniquePaths = new Set(paths.map((p) => p.path))
    expect(uniquePaths.size).toBe(paths.length)
  })
})
