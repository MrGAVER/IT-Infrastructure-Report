import { describe, expect, it } from 'vitest'
import { conflictSummary, conflictTitle, connectionSummary, duplicatePortsText, staleSubinterfaceText, trunkVlanSummary, trunkVlanTitle, vlanCellSummary } from '../interfaceRowView'
import { makeConflict, makeRow, makeVlan } from './interfaceRowFixture'

const vlans = [makeVlan('v10', 10, 'Гостевой', 'Филиал'), makeVlan('v20', 20, 'Серверы')]

describe('vlanCellSummary', () => {
  it('access без выбранного VLAN — просто «Access», без «0 VLAN»', () => {
    expect(vlanCellSummary(makeRow({ vlan_mode: 'access' }), vlans)).toBe('Access')
  })

  it('access с VLAN показывает его подпись', () => {
    expect(vlanCellSummary(makeRow({ vlan_mode: 'access', vlan_ids: ['v10'] }), vlans)).toBe('Access: 10 — Гостевой [Филиал]')
  })

  it('access с VLAN, которого нет среди доступных, — снова «Access»', () => {
    expect(vlanCellSummary(makeRow({ vlan_mode: 'access', vlan_ids: ['v99'] }), vlans)).toBe('Access')
  })

  it('trunk различает «Все VLAN» и ручной выбор', () => {
    expect(vlanCellSummary(makeRow({ vlan_mode: 'trunk', all_vlans: true, vlan_ids: ['v10', 'v20'] }), vlans)).toBe('Trunk · все VLAN (2)')
    expect(vlanCellSummary(makeRow({ vlan_mode: 'trunk', vlan_ids: ['v10'] }), vlans)).toBe('Trunk · 1 VLAN')
  })
})

describe('trunkVlanSummary / trunkVlanTitle', () => {
  it('считает только VLAN устройства: чужой идентификатор в vlan_ids в сводку не попадает', () => {
    const row = makeRow({ vlan_mode: 'trunk', vlan_ids: ['v10', 'v-чужой'] })
    expect(trunkVlanSummary(row, vlans)).toBe('Выбрано VLAN: 1 из 2')
  })

  it('подсказка перечисляет выбранные VLAN построчно, а при пустом выборе так и говорит', () => {
    expect(trunkVlanTitle(makeRow({ vlan_ids: ['v10', 'v20'] }), vlans)).toBe('10 — Гостевой [Филиал]\n20 — Серверы')
    expect(trunkVlanTitle(makeRow(), vlans)).toBe('VLAN не выбраны')
  })
})

describe('conflictSummary / conflictTitle', () => {
  const conflict = makeConflict({ other: { is_management: false, is_data_transfer: false, vlan_mode: 'trunk', all_vlans: true } })

  it('для каждого вида расхождения — свой текст с устройством и портом соседа', () => {
    expect(conflictSummary(conflict, 'flags')).toContain('sw-02 · Gi0/9')
    expect(conflictSummary(conflict, 'flags')).toContain('другое назначение')
    expect(conflictSummary(conflict, 'vlan_mode')).toContain('другой режим порта')
  })

  it('«Все VLAN»: говорит, стоит признак у соседа или нет', () => {
    expect(conflictSummary(conflict, 'all_vlans')).toContain('стоит «Все VLAN»')
    const without = makeConflict({ other: { ...conflict.other, all_vlans: false } })
    expect(conflictSummary(without, 'all_vlans')).toContain('не стоит «Все VLAN»')
  })

  it('у каждого вида расхождения свой заголовок окна', () => {
    expect(new Set([conflictTitle('flags'), conflictTitle('vlan_mode'), conflictTitle('all_vlans')]).size).toBe(3)
  })
})

describe('staleSubinterfaceText', () => {
  const sub = { key: 's1', name: 'Gi0/1.99', vlan_id: 'v99', is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [] }

  it('пусто, пока все подинтерфейсы на доступных VLAN', () => {
    const row = makeRow({ vlan_ids: ['v10'], subinterfaces: [{ ...sub, vlan_id: 'v10' }] })
    expect(staleSubinterfaceText(row, new Set(['v10']))).toBe('')
  })

  it('называет подинтерфейс на недоступном VLAN, а безымянный — «без имени»', () => {
    const row = makeRow({ vlan_ids: ['v10'], subinterfaces: [sub, { ...sub, key: 's2', name: '  ' }] })
    const text = staleSubinterfaceText(row, new Set(['v10']))
    expect(text).toContain('«Gi0/1.99»')
    expect(text).toContain('«без имени»')
  })
})

describe('duplicatePortsText', () => {
  it('перечисляет повторяющиеся номера через запятую', () => {
    expect(duplicatePortsText([22, 443])).toBe('Повторяются номера открытых портов: 22, 443')
  })
})

describe('connectionSummary', () => {
  const peer = { peer_device_id: 'dev-2', peer_interface_id: 'if-9', connection_type_id: '', description: '', peer_device_name: 'sw-02', peer_interface_name: 'Gi0/9' }

  it('без подключения — пустая строка', () => {
    expect(connectionSummary(makeRow(), [], 'dev-1')).toBe('')
  })

  it('подключение без выбранного порта', () => {
    const row = makeRow({ connection: { ...peer, peer_interface_id: '' } })
    expect(connectionSummary(row, [row], 'dev-1')).toBe('↔ порт не выбран')
  })

  it('сосед на другом устройстве — по именам из черновика, при их отсутствии «?»', () => {
    const row = makeRow({ connection: peer })
    expect(connectionSummary(row, [row], 'dev-1')).toBe('↔ sw-02 · Gi0/9')
    const unnamed = makeRow({ connection: { ...peer, peer_device_name: undefined, peer_interface_name: undefined } })
    expect(connectionSummary(unnamed, [unnamed], 'dev-1')).toBe('↔ ? · ?')
  })

  it('сосед — другая строка этого же устройства (по id порта или ключу строки)', () => {
    const target = makeRow({ id: 'if-2', name: 'Gi0/2' })
    const row = makeRow({ connection: { ...peer, peer_device_id: 'dev-1', peer_interface_id: 'if-2' } })
    expect(connectionSummary(row, [row, target], 'dev-1')).toBe('↔ это устройство · Gi0/2')
    const byKey = makeRow({ connection: { ...peer, peer_interface_id: '', peer_row_key: 'k1' } })
    expect(connectionSummary(byKey, [byKey, makeRow({ key: 'k1', name: '' })], null)).toBe('↔ это устройство · без имени')
  })

  it('у ещё не созданного устройства (deviceId = null) соседом-собой считается SELF_DEVICE', () => {
    const row = makeRow({ connection: { ...peer, peer_device_id: '__self__', peer_interface_id: 'if-2' } })
    expect(connectionSummary(row, [row], null)).toBe('↔ это устройство · ?')
  })
})
