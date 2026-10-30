import { describe, it, expect } from 'vitest'
import { duplicateVlanRowIndexes, duplicateVlansMessage, sortDeviceVlanRows, sortVlanDefinitions, usedVlanIds, vlanOptionsForRow } from '../deviceVlans'
import type { VLANDefinition } from '../../api/types'

const def = (id: string, vlanId: number, name: string, domainName = ''): VLANDefinition => ({
  id,
  vlan_id: vlanId,
  name,
  description: '',
  domain_id: domainName ? `dom-${domainName}` : null,
  domain_name: domainName,
  devices: [],
})
const definitions = [def('v-30', 30, 'Гости'), def('v-10', 10, 'Мониторинг'), def('v-20', 20, 'Управление'), def('v-20b', 20, 'Управление', 'Филиал')]
const row = (vlan_id: string, extra: Record<string, unknown> = {}) => ({ vlan_id, ip_address: '', ...extra })

describe('sortDeviceVlanRows', () => {
  it('упорядочивает строки по номеру VLAN по возрастанию, пустые строки — в конец', () => {
    const rows = [row('v-30'), row(''), row('v-10'), row('v-20')]
    expect(sortDeviceVlanRows(rows, definitions).map((r) => r.vlan_id)).toEqual(['v-10', 'v-20', 'v-30', ''])
  })

  it('одинаковый номер в разных доменах: сначала без домена, затем по названию домена', () => {
    const rows = [row('v-20b'), row('v-20')]
    expect(sortDeviceVlanRows(rows, definitions).map((r) => r.vlan_id)).toEqual(['v-20', 'v-20b'])
  })

  it('VLAN, которого нет в справочнике, ставится после известных; порядок равных сохраняется (стабильная сортировка)', () => {
    const rows = [row('ghost-1'), row('v-20'), row('ghost-2'), row('')]
    expect(sortDeviceVlanRows(rows, definitions).map((r) => r.vlan_id)).toEqual(['v-20', 'ghost-1', 'ghost-2', ''])
  })

  it('не мутирует входной массив', () => {
    const rows = [row('v-30'), row('v-10')]
    sortDeviceVlanRows(rows, definitions)
    expect(rows.map((r) => r.vlan_id)).toEqual(['v-30', 'v-10'])
  })

  it('сохраняет прочие поля строки (id, IP) при перестановке', () => {
    const rows = [row('v-30', { id: 'dv-3', ip_address: '10.0.30.1' }), row('v-10', { id: 'dv-1' })]
    expect(sortDeviceVlanRows(rows, definitions)[1]).toEqual({ vlan_id: 'v-30', id: 'dv-3', ip_address: '10.0.30.1' })
  })
})

describe('sortVlanDefinitions', () => {
  it('сортирует список выбора по номеру и не мутирует исходный массив', () => {
    const copy = [...definitions]
    expect(sortVlanDefinitions(definitions).map((d) => d.id)).toEqual(['v-10', 'v-20', 'v-20b', 'v-30'])
    expect(definitions).toEqual(copy)
  })
})

describe('отсев уже добавленных VLAN', () => {
  it('usedVlanIds игнорирует пустые строки', () => {
    expect([...usedVlanIds([row('v-10'), row(''), row('v-20')])].sort()).toEqual(['v-10', 'v-20'])
  })

  it('vlanOptionsForRow скрывает VLAN из других строк, но оставляет собственный выбор строки', () => {
    const used = usedVlanIds([row('v-10'), row('v-20')])
    expect(vlanOptionsForRow(definitions, used, 'v-10').map((d) => d.id)).toEqual(['v-30', 'v-10', 'v-20b'])
    expect(vlanOptionsForRow(definitions, used, '').map((d) => d.id)).toEqual(['v-30', 'v-20b'])
  })
})

describe('повторы VLAN', () => {
  it('duplicateVlanRowIndexes возвращает все строки с повторяющимся VLAN и игнорирует пустые', () => {
    const rows = [row('v-10'), row(''), row('v-20'), row('v-10'), row('')]
    expect([...duplicateVlanRowIndexes(rows)].sort()).toEqual([0, 3])
  })

  it('duplicateVlansMessage перечисляет номера повторяющихся VLAN по возрастанию, без дублей; пусто, если повторов нет', () => {
    expect(duplicateVlansMessage([row('v-10'), row('v-20')], definitions)).toBe('')
    const message = duplicateVlansMessage([row('v-30'), row('v-10'), row('v-30'), row('v-10'), row('v-10')], definitions)
    expect(message).toBe('VLAN 10, 30 указан несколько раз — каждый VLAN можно добавить устройству только один раз.')
  })
})
