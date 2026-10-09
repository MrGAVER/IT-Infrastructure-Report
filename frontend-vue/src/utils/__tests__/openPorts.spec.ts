import { describe, it, expect } from 'vitest'
import { duplicatePortNumbers, duplicateRowIndexes, sortOpenPortRows } from '../openPorts'
import type { ISProtocolDraftRow, OpenPortDraftRow, ProtocolPortCatalogEntry } from '../../api/types'

const catalog: ProtocolPortCatalogEntry[] = [
  { id: 'c-ssh', port: 22, protocol_type: 'SSH', description: null },
  { id: 'c-dns', port: 53, protocol_type: 'DNS', description: null },
  { id: 'c-http', port: 80, protocol_type: 'HTTP', description: null },
  { id: 'c-http-alt', port: 80, protocol_type: 'HTTP-Proxy', description: null },
  { id: 'c-https', port: 443, protocol_type: 'HTTPS', description: null },
]

const row = (protocol_catalog_id: string, extra: Partial<OpenPortDraftRow> = {}): OpenPortDraftRow => ({
  protocol_catalog_id,
  transport_protocol: 'TCP',
  description: '',
  ...extra,
})

describe('sortOpenPortRows', () => {
  it('сортирует по номеру порта по возрастанию (числовое, а не строковое сравнение)', () => {
    const rows = [row('c-https'), row('c-ssh'), row('c-dns')]
    expect(sortOpenPortRows(rows, catalog).map((r) => r.protocol_catalog_id)).toEqual(['c-ssh', 'c-dns', 'c-https'])
  })

  it('строки без выбранной записи справочника уходят в конец, их взаимный порядок сохраняется', () => {
    const rows = [row('', { description: 'a' }), row('c-https'), row('', { description: 'b' }), row('c-ssh')]
    expect(sortOpenPortRows(rows, catalog).map((r) => r.protocol_catalog_id || r.description)).toEqual(['c-ssh', 'c-https', 'a', 'b'])
  })

  it('запись справочника, которой нет в переданном каталоге, считается невыбранной (не падает)', () => {
    const rows = [row('c-unknown'), row('c-ssh')]
    expect(sortOpenPortRows(rows, catalog).map((r) => r.protocol_catalog_id)).toEqual(['c-ssh', 'c-unknown'])
  })

  it('стабильна для одинаковых портов и не мутирует исходный массив', () => {
    const rows = [row('c-http-alt'), row('c-http')]
    const sorted = sortOpenPortRows(rows, catalog)
    expect(sorted.map((r) => r.protocol_catalog_id)).toEqual(['c-http-alt', 'c-http'])
    expect(sorted).not.toBe(rows)
    expect(rows.map((r) => r.protocol_catalog_id)).toEqual(['c-http-alt', 'c-http'])
  })
})

describe('duplicatePortNumbers / duplicateRowIndexes', () => {
  it('нет повторов — пустой результат', () => {
    const rows = [row('c-ssh'), row('c-https'), row('')]
    expect(duplicatePortNumbers(rows, catalog)).toEqual([])
    expect(duplicateRowIndexes(rows, catalog).size).toBe(0)
  })

  it('повтор определяется по НОМЕРУ порта, а не по id записи справочника', () => {
    // 80/HTTP и 80/HTTP-Proxy — разные записи справочника, но один и тот же порт.
    const rows = [row('c-http'), row('c-ssh'), row('c-http-alt')]
    expect(duplicatePortNumbers(rows, catalog)).toEqual([80])
    expect([...duplicateRowIndexes(rows, catalog)].sort()).toEqual([0, 2])
  })

  it('один порт с разным транспортом (TCP и UDP) — тоже повтор', () => {
    const rows = [row('c-dns', { transport_protocol: 'TCP' }), row('c-dns', { transport_protocol: 'UDP' })]
    expect(duplicatePortNumbers(rows, catalog)).toEqual([53])
  })

  it('пустые строки (запись не выбрана) повторами не считаются', () => {
    expect(duplicatePortNumbers([row(''), row('')], catalog)).toEqual([])
  })

  it('возвращает номера отсортированными и без дублей самих номеров', () => {
    const rows = [row('c-https'), row('c-ssh'), row('c-https'), row('c-ssh'), row('c-https')]
    expect(duplicatePortNumbers(rows, catalog)).toEqual([22, 443])
  })
})

describe('те же функции над строками протоколов ИС (ISProtocolDraftRow — без транспорта)', () => {
  const proto = (protocol_catalog_id: string, description = ''): ISProtocolDraftRow => ({ protocol_catalog_id, description })

  it('сортировка сохраняет тип строки и упорядочивает по номеру порта, пустая строка — в конец', () => {
    const sorted: ISProtocolDraftRow[] = sortOpenPortRows([proto('c-https', 'b'), proto(''), proto('c-ssh', 'a')], catalog)
    expect(sorted.map((r) => r.description || r.protocol_catalog_id || '—')).toEqual(['a', 'b', '—'])
  })

  it('повторы по номеру порта находятся так же, как у открытых портов ВМ', () => {
    const rows = [proto('c-http'), proto('c-ssh'), proto('c-http-alt')]
    expect(duplicatePortNumbers(rows, catalog)).toEqual([80])
    expect([...duplicateRowIndexes(rows, catalog)].sort()).toEqual([0, 2])
  })
})
