import { describe, expect, it } from 'vitest'
import {
  applyTemplate,
  clearReferencesTo,
  DEFAULT_NAME_TEMPLATE,
  emptyInterfaceRow,
  generateNewRows,
  portNamePatch,
  replaceWithGenerated,
  resolveStartNumber,
} from '../interfaceRowDraft'
import { makeRow, makeVlan } from './interfaceRowFixture'

describe('emptyInterfaceRow', () => {
  it('новый порт — access, без VLAN и подинтерфейсов («не трогали»)', () => {
    const row = emptyInterfaceRow(false)
    expect(row).toMatchObject({ name: '', vlan_mode: 'access', vlan_ids: [], all_vlans: false, ips: [], open_ports: [] })
    expect('subinterfaces' in row).toBe(false)
    expect('key' in row).toBe(false)
  })

  it('со withKey каждая строка получает свой ключ — на неё может сослаться подключение другого порта', () => {
    const a = emptyInterfaceRow(true)
    const b = emptyInterfaceRow(true)
    expect(a.key).toBeTruthy()
    expect(a.key).not.toBe(b.key)
  })
})

describe('applyTemplate', () => {
  it('подставляет {n} и {n0} (с ведущим нулём), в том числе несколько раз', () => {
    expect(applyTemplate('eth{n}', 3)).toBe('eth3')
    expect(applyTemplate('Gi0/{n0}', 7)).toBe('Gi0/07')
    expect(applyTemplate('{n}-{n}', 12)).toBe('12-12')
  })
})

describe('resolveStartNumber', () => {
  it('пустое поле — умолчание, а не 0', () => {
    expect(resolveStartNumber('', 5)).toBe(5)
    expect(resolveStartNumber(null, 5)).toBe(5)
    expect(resolveStartNumber(undefined, 5)).toBe(5)
  })

  it('число и строка с числом принимаются, включая 0', () => {
    expect(resolveStartNumber(9, 1)).toBe(9)
    expect(resolveStartNumber('12', 1)).toBe(12)
    expect(resolveStartNumber('0', 1)).toBe(0)
  })

  it('не число — умолчание', () => {
    expect(resolveStartNumber('abc', 4)).toBe(4)
    expect(resolveStartNumber(Number.NaN, 4)).toBe(4)
  })
})

describe('portNamePatch', () => {
  const vlans = [makeVlan('v10', 10)]
  const sub = { key: 's1', name: 'Gi0/0.10', vlan_id: 'v10', is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [] }

  it('без подинтерфейсов — только имя, ключ subinterfaces не появляется', () => {
    const patch = portNamePatch(makeRow({ name: 'Gi0/0' }), 'Gi0/1', vlans)
    expect(patch).toEqual({ name: 'Gi0/1' })
  })

  it('автоимя подинтерфейса следует за именем порта, а введённое вручную остаётся', () => {
    const row = makeRow({ name: 'Gi0/0', subinterfaces: [sub, { ...sub, key: 's2', name: 'wan-uplink' }] })
    const patch = portNamePatch(row, 'Gi0/1', vlans)
    expect(patch.name).toBe('Gi0/1')
    expect(patch.subinterfaces?.map((s) => s.name)).toEqual(['Gi0/1.10', 'wan-uplink'])
  })

  it('если пересчитывать нечего, подинтерфейсы не попадают в патч', () => {
    const row = makeRow({ name: 'Gi0/0', subinterfaces: [{ ...sub, name: 'wan-uplink' }] })
    expect(portNamePatch(row, 'Gi0/1', vlans)).toEqual({ name: 'Gi0/1' })
  })
})

describe('replaceWithGenerated', () => {
  const settings = { count: 3, startNumber: 1, nameTemplate: 'eth{n}', typeId: '', speedId: '' }
  const empty = () => emptyInterfaceRow(false)

  it('существующие строки по индексу сохраняют id, IP и VLAN, меняется только имя', () => {
    const existing = [
      makeRow({ id: 'if-1', name: 'old', vlan_ids: ['v10'], interface_type_id: 't-1', ips: [{ ip_address: '10.0.0.1', prefix_length: '24', purpose: '' }] }),
    ]
    const rows = replaceWithGenerated(existing, settings, [], empty)
    expect(rows).toHaveLength(3)
    expect(rows[0]).toMatchObject({ id: 'if-1', name: 'eth1', vlan_ids: ['v10'], interface_type_id: 't-1' })
    expect(rows[0].ips).toHaveLength(1)
    expect(rows.slice(1).map((r) => r.name)).toEqual(['eth2', 'eth3'])
  })

  it('пустые тип и скорость не затирают значения существующих строк, заданные — перезаписывают', () => {
    const existing = [makeRow({ interface_type_id: 't-1', speed_id: 's-1' })]
    expect(replaceWithGenerated(existing, settings, [], empty)[0]).toMatchObject({ interface_type_id: 't-1', speed_id: 's-1' })
    expect(replaceWithGenerated(existing, { ...settings, typeId: 't-2', speedId: 's-2' }, [], empty)[0]).toMatchObject({
      interface_type_id: 't-2',
      speed_id: 's-2',
    })
  })

  it('количество меньше числа строк — лишние отбрасываются; 0 — список пуст; пустой шаблон — eth{n}', () => {
    const existing = [makeRow(), makeRow(), makeRow()]
    expect(replaceWithGenerated(existing, { ...settings, count: 1 }, [], empty)).toHaveLength(1)
    expect(replaceWithGenerated(existing, { ...settings, count: 0 }, [], empty)).toEqual([])
    expect(replaceWithGenerated([], { ...settings, count: 1, nameTemplate: '' }, [], empty)[0].name).toBe(applyTemplate(DEFAULT_NAME_TEMPLATE, 1))
  })
})

describe('generateNewRows', () => {
  it('создаёт только новые строки с типом и скоростью по умолчанию, нумерация с startNumber', () => {
    const rows = generateNewRows({ count: 2, startNumber: 5, nameTemplate: 'Gi0/{n0}', typeId: 't-1', speedId: 's-1' }, () => emptyInterfaceRow(false))
    expect(rows.map((r) => r.name)).toEqual(['Gi0/05', 'Gi0/06'])
    expect(rows.every((r) => r.interface_type_id === 't-1' && r.speed_id === 's-1' && !r.id)).toBe(true)
  })
})

describe('clearReferencesTo', () => {
  const connection = { peer_device_id: '__self__', peer_interface_id: 'if-2', connection_type_id: 'c-1', description: '' }

  it('подключение, ссылавшееся на удалённую строку, теряет соседа, остальное сохраняется', () => {
    const rows = [makeRow({ id: 'if-1', connection })]
    const cleaned = clearReferencesTo(rows, [makeRow({ id: 'if-2' })])
    expect(cleaned[0].connection).toMatchObject({ peer_interface_id: '', connection_type_id: 'c-1' })
  })

  it('ссылка по ключу строки (peer_row_key) тоже снимается', () => {
    const rows = [makeRow({ id: 'if-1', connection: { ...connection, peer_interface_id: '', peer_row_key: 'k1' } })]
    const cleaned = clearReferencesTo(rows, [makeRow({ key: 'k1' })])
    expect(cleaned[0].connection?.peer_row_key).toBeUndefined()
  })

  it('если удалённые строки никто не упоминает — тот же массив, а у удалённых без ссылки ничего не меняется', () => {
    const rows = [makeRow({ id: 'if-1', connection })]
    expect(clearReferencesTo(rows, [makeRow({ id: 'if-7' })])[0]).toBe(rows[0])
    expect(clearReferencesTo(rows, [makeRow()])).toBe(rows)
  })
})
