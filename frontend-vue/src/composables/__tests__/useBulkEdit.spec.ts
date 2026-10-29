import { beforeEach, describe, expect, it } from 'vitest'
import { ref } from 'vue'
import type { InterfaceDraftRow } from '../../api/types'
import { makeRow, makeVlan } from '../../utils/__tests__/interfaceRowFixture'
import { useBulkEdit } from '../useBulkEdit'
import { useRowUiState } from '../useRowUiState'
import { useToast } from '../useToast'

const vlans = [makeVlan('v10', 10), makeVlan('v20', 20)]

function setup(initial: InterfaceDraftRow[], locked = false) {
  const rows = ref(initial)
  const ui = useRowUiState(() => rows.value.length)
  const bulk = useBulkEdit(
    {
      rows: () => rows.value,
      setRows: (next) => {
        rows.value = next
      },
      vlanOptions: () => vlans,
      rowManaged: () => ({ vlan: locked, ip: false, openPorts: false, subinterfaces: false }),
    },
    ui,
  )
  return { rows, ui, bulk }
}

describe('useBulkEdit', () => {
  beforeEach(() => {
    useToast().toasts.splice(0)
  })

  it('без отмеченных строк — ошибка и список не меняется', () => {
    const { rows, bulk } = setup([makeRow()])
    bulk.bulkTypeId.value = 't-1'
    bulk.applyBulkEdit()
    expect(useToast().toasts.at(-1)).toMatchObject({ type: 'error' })
    expect(rows.value[0].interface_type_id).toBe('')
    expect(bulk.bulkTypeId.value).toBe('t-1')
  })

  it('применяет значения панели к отмеченным строкам и полностью сбрасывает панель и выбор', () => {
    const { rows, ui, bulk } = setup([makeRow({ id: 'a' }), makeRow({ id: 'b' })])
    ui.toggleSelect(1, true)
    bulk.bulkTypeId.value = 't-1'
    bulk.bulkSpeedId.value = 's-1'
    bulk.bulkManagement.value = 'true'
    bulk.bulkVlanMode.value = 'trunk'
    bulk.toggleBulkVlan('v10', true)
    bulk.bulkVlanPickerOpen.value = true
    bulk.applyBulkEdit()
    expect(rows.value[0].interface_type_id).toBe('')
    expect(rows.value[1]).toMatchObject({ interface_type_id: 't-1', speed_id: 's-1', is_management: true, vlan_mode: 'trunk', vlan_ids: ['v10'] })
    expect(ui.selectedIndices.value.size).toBe(0)
    expect([bulk.bulkTypeId.value, bulk.bulkSpeedId.value, bulk.bulkManagement.value, bulk.bulkVlanMode.value]).toEqual(['', '', '', ''])
    expect(bulk.bulkVlanIds.value.size).toBe(0)
    expect(bulk.bulkVlanPickerOpen.value).toBe(false)
  })

  it('сводка VLAN панели: ничего не выбрано, выбрано N, «Все VLAN»', () => {
    const { bulk } = setup([makeRow()])
    expect(bulk.bulkVlanSummary.value).toBe('— выбрать VLAN —')
    bulk.toggleBulkVlan('v10', true)
    expect(bulk.bulkVlanSummary.value).toBe('Выбрано VLAN: 1')
    bulk.toggleBulkAllVlans(true)
    expect(bulk.bulkVlanSummary.value).toBe('Все VLAN')
    expect([...bulk.bulkVlanIds.value]).toEqual(['v10', 'v20'])
  })

  it('ручной выбор VLAN снимает «Все VLAN» панели, снятие галочки очищает набор', () => {
    const { bulk } = setup([makeRow()])
    bulk.toggleBulkAllVlans(true)
    bulk.toggleBulkVlan('v10', false)
    expect(bulk.bulkAllVlans.value).toBe(false)
    bulk.toggleBulkAllVlans(true)
    bulk.toggleBulkAllVlans(false)
    expect(bulk.bulkVlanIds.value.size).toBe(0)
  })

  it('порт из группы, задающей VLAN, не получает режим и VLAN панели', () => {
    const { rows, ui, bulk } = setup([makeRow({ vlan_mode: 'access', vlan_ids: ['v20'] })], true)
    ui.toggleSelect(0, true)
    bulk.bulkVlanMode.value = 'trunk'
    bulk.toggleBulkVlan('v10', true)
    bulk.applyBulkEdit()
    expect(rows.value[0]).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v20'] })
  })
})
