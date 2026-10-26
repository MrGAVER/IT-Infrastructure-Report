import { describe, expect, it } from 'vitest'
import { applyBulkEditToRows, type BulkEditValues } from '../interfaceBulkEdit'
import { makeRow, makeVlan } from './interfaceRowFixture'

const vlans = [makeVlan('v10', 10), makeVlan('v20', 20), makeVlan('v30', 30)]
const none: BulkEditValues = { typeId: '', speedId: '', management: '', dataTransfer: '', vlanMode: '', vlanIds: [], allVlans: false }
const unlocked = () => false

describe('applyBulkEditToRows', () => {
  it('меняет только отмеченные строки, остальные возвращает тем же объектом', () => {
    const rows = [makeRow({ name: 'a' }), makeRow({ name: 'b' })]
    const result = applyBulkEditToRows(rows, new Set([1]), { ...none, typeId: 't-1' }, vlans, unlocked)
    expect(result[0]).toBe(rows[0])
    expect(result[1].interface_type_id).toBe('t-1')
    expect(rows[1].interface_type_id).toBe('')
  })

  it('пустые значения панели («не менять») ничего не затирают', () => {
    const rows = [makeRow({ interface_type_id: 't-1', speed_id: 's-1', is_management: true, is_data_transfer: true })]
    expect(applyBulkEditToRows(rows, new Set([0]), none, vlans, unlocked)[0]).toMatchObject({
      interface_type_id: 't-1',
      speed_id: 's-1',
      is_management: true,
      is_data_transfer: true,
    })
  })

  it("'true' и 'false' включают и выключают флажки назначения", () => {
    const rows = [makeRow({ is_management: true, is_data_transfer: false })]
    const result = applyBulkEditToRows(rows, new Set([0]), { ...none, management: 'false', dataTransfer: 'true' }, vlans, unlocked)
    expect(result[0]).toMatchObject({ is_management: false, is_data_transfer: true })
  })

  it('VLAN добавляются К уже стоящим на trunk-порту, без дублей', () => {
    const rows = [makeRow({ vlan_mode: 'trunk', vlan_ids: ['v10'] })]
    const result = applyBulkEditToRows(rows, new Set([0]), { ...none, vlanIds: new Set(['v10', 'v20']) }, vlans, unlocked)
    expect(result[0].vlan_ids).toEqual(['v10', 'v20'])
  })

  it('переключение в access оставляет не больше одного VLAN и снимает «Все VLAN»', () => {
    const rows = [makeRow({ vlan_mode: 'trunk', all_vlans: true, vlan_ids: ['v10', 'v20', 'v30'] })]
    const result = applyBulkEditToRows(rows, new Set([0]), { ...none, vlanMode: 'access' }, vlans, unlocked)
    expect(result[0]).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'], all_vlans: false })
  })

  it('«Все VLAN» панели ставит признак trunk-портам (vlan_ids зеркалит все VLAN), а access-порт остаётся без него', () => {
    const rows = [makeRow({ vlan_mode: 'trunk' }), makeRow({ vlan_mode: 'access' })]
    const result = applyBulkEditToRows(rows, new Set([0, 1]), { ...none, allVlans: true }, vlans, unlocked)
    expect(result[0]).toMatchObject({ vlan_mode: 'trunk', all_vlans: true, vlan_ids: ['v10', 'v20', 'v30'] })
    expect(result[1]).toMatchObject({ vlan_mode: 'access', all_vlans: false })
  })

  it('признак «Все VLAN» держится, пока порт остаётся в trunk и набор не менялся', () => {
    const rows = [makeRow({ vlan_mode: 'trunk', all_vlans: true, vlan_ids: ['v10', 'v20', 'v30'] })]
    const result = applyBulkEditToRows(rows, new Set([0]), { ...none, typeId: 't-1' }, vlans, unlocked)
    expect(result[0]).toMatchObject({ all_vlans: true, vlan_ids: ['v10', 'v20', 'v30'] })
  })

  it('режим и VLAN порта из группы, задающей их, не меняются, а тип и скорость — меняются', () => {
    const rows = [makeRow({ vlan_mode: 'access', vlan_ids: ['v10'] })]
    const values = { ...none, typeId: 't-2', vlanMode: 'trunk', vlanIds: ['v20'], allVlans: true }
    const result = applyBulkEditToRows(rows, new Set([0]), values, vlans, () => true)
    expect(result[0]).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'], all_vlans: false, interface_type_id: 't-2' })
  })
})
