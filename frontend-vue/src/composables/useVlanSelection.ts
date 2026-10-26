// Выбор VLAN на порту в редакторе портов (DeviceInterfacesEditor.vue): режим access/trunk, VLAN access-порта, «Все VLAN» и
// всплывающее окно набора VLAN trunk-порта (PortVlanPickerModal). Правки строк считают utils/interfaceVlanPatch.ts.
import { computed, ref } from 'vue'
import type { InterfaceDraftRow, VLANDefinition } from '../api/types'
import { accessVlanPatch, allVlansPatch, toggleVlanPatch, vlanModePatch } from '../utils/interfaceVlanPatch'

export interface VlanSelectionDeps {
  rows: () => InterfaceDraftRow[]
  vlanOptions: () => VLANDefinition[]
  updateRow: (index: number, patch: Partial<InterfaceDraftRow>) => void
}

export function useVlanSelection(deps: VlanSelectionDeps) {
  // Индекс строки, чьё окно выбора VLAN открыто; пока окно открыто, форма под ним не редактируется — индекс остаётся верным.
  const vlanPickerIndex = ref<number | null>(null)
  const vlanPickerRow = computed(() => (vlanPickerIndex.value === null ? undefined : deps.rows()[vlanPickerIndex.value]))

  function toggleVlan(index: number, vlanDefId: string, checked: boolean) {
    const row = deps.rows()[index]
    if (row) deps.updateRow(index, toggleVlanPatch(row, vlanDefId, checked))
  }

  function setVlanMode(index: number, mode: 'access' | 'trunk') {
    const row = deps.rows()[index]
    if (row) deps.updateRow(index, vlanModePatch(row, mode, deps.vlanOptions()))
  }

  function setAccessVlan(index: number, vlanDefId: string) {
    deps.updateRow(index, accessVlanPatch(vlanDefId))
  }

  function toggleAllVlans(index: number, checked: boolean) {
    deps.updateRow(index, allVlansPatch(checked, deps.vlanOptions()))
  }

  return { vlanPickerIndex, vlanPickerRow, toggleVlan, setVlanMode, setAccessVlan, toggleAllVlans }
}
