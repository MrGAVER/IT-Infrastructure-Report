import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import type { InterfaceDraftRow } from '../../api/types'
import { makeRow, makeVlan } from '../../utils/__tests__/interfaceRowFixture'
import { useVlanSelection } from '../useVlanSelection'

const vlans = [makeVlan('v10', 10), makeVlan('v20', 20)]

function setup(initial: InterfaceDraftRow[]) {
  const rows = ref(initial)
  const selection = useVlanSelection({
    rows: () => rows.value,
    vlanOptions: () => vlans,
    updateRow: (index, patch) => {
      rows.value = rows.value.map((r, i) => (i === index ? { ...r, ...patch } : r))
    },
  })
  return { rows, ...selection }
}

describe('useVlanSelection', () => {
  it('setVlanMode: trunk ставит «Все VLAN», access оставляет один VLAN', () => {
    const { rows, setVlanMode } = setup([makeRow()])
    setVlanMode(0, 'trunk')
    expect(rows.value[0]).toMatchObject({ vlan_mode: 'trunk', all_vlans: true, vlan_ids: ['v10', 'v20'] })
    setVlanMode(0, 'access')
    expect(rows.value[0]).toMatchObject({ vlan_mode: 'access', all_vlans: false, vlan_ids: ['v10'] })
  })

  it('toggleVlan снимает «Все VLAN», toggleAllVlans и setAccessVlan задают набор', () => {
    const { rows, toggleVlan, toggleAllVlans, setAccessVlan } = setup([makeRow({ vlan_mode: 'trunk', all_vlans: true, vlan_ids: ['v10', 'v20'] })])
    toggleVlan(0, 'v10', false)
    expect(rows.value[0]).toMatchObject({ all_vlans: false, vlan_ids: ['v20'] })
    toggleAllVlans(0, true)
    expect(rows.value[0]).toMatchObject({ all_vlans: true, vlan_ids: ['v10', 'v20'] })
    setAccessVlan(0, 'v20')
    expect(rows.value[0].vlan_ids).toEqual(['v20'])
  })

  it('правки несуществующей строки игнорируются', () => {
    const { rows, setVlanMode, toggleVlan } = setup([makeRow()])
    setVlanMode(3, 'trunk')
    toggleVlan(3, 'v10', true)
    expect(rows.value).toEqual([makeRow()])
  })

  it('строка окна выбора VLAN следует за индексом и пропадает при закрытии', () => {
    const { vlanPickerIndex, vlanPickerRow } = setup([makeRow({ name: 'A' }), makeRow({ name: 'B' })])
    expect(vlanPickerRow.value).toBeUndefined()
    vlanPickerIndex.value = 1
    expect(vlanPickerRow.value?.name).toBe('B')
    vlanPickerIndex.value = null
    expect(vlanPickerRow.value).toBeUndefined()
  })
})
