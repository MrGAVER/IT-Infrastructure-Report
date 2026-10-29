import { describe, expect, it } from 'vitest'
import { accessVlanPatch, allVlansPatch, toggleVlanPatch, vlanModePatch } from '../interfaceVlanPatch'
import { makeVlan } from './interfaceRowFixture'

const vlans = [makeVlan('v10', 10), makeVlan('v20', 20)]

describe('toggleVlanPatch', () => {
  it('добавляет и убирает VLAN, не мутируя исходный набор', () => {
    const row = { vlan_ids: ['v10'] }
    expect(toggleVlanPatch(row, 'v20', true).vlan_ids).toEqual(['v10', 'v20'])
    expect(toggleVlanPatch(row, 'v10', false).vlan_ids).toEqual([])
    expect(row.vlan_ids).toEqual(['v10'])
  })

  it('ручной выбор всегда снимает признак «Все VLAN» — даже если выбраны все', () => {
    expect(toggleVlanPatch({ vlan_ids: ['v10'] }, 'v20', true)).toMatchObject({ all_vlans: false })
  })
})

describe('vlanModePatch', () => {
  it('в access остаётся только первый отмеченный VLAN, признак «Все VLAN» снимается', () => {
    expect(vlanModePatch({ vlan_ids: ['v20', 'v10'] }, 'access', vlans)).toEqual({ vlan_mode: 'access', vlan_ids: ['v20'], all_vlans: false })
    expect(vlanModePatch({ vlan_ids: [] }, 'access', vlans)).toEqual({ vlan_mode: 'access', vlan_ids: [], all_vlans: false })
  })

  it('в trunk сразу ставится «Все VLAN»: vlan_ids зеркалит все VLAN устройства', () => {
    expect(vlanModePatch({ vlan_ids: [] }, 'trunk', vlans)).toEqual({ vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], all_vlans: true })
  })

  it('у устройства без VLAN в trunk признак не ставится', () => {
    expect(vlanModePatch({ vlan_ids: [] }, 'trunk', [])).toEqual({ vlan_mode: 'trunk', vlan_ids: [], all_vlans: false })
  })
})

describe('accessVlanPatch / allVlansPatch', () => {
  it('access: пустое значение снимает VLAN, непустое задаёт единственный', () => {
    expect(accessVlanPatch('v10')).toEqual({ vlan_ids: ['v10'] })
    expect(accessVlanPatch('')).toEqual({ vlan_ids: [] })
  })

  it('«Все VLAN»: включение отмечает все VLAN устройства, выключение очищает набор', () => {
    expect(allVlansPatch(true, vlans)).toEqual({ all_vlans: true, vlan_ids: ['v10', 'v20'] })
    expect(allVlansPatch(false, vlans)).toEqual({ all_vlans: false, vlan_ids: [] })
  })
})
