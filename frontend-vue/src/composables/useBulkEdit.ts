// Массовое редактирование отмеченных портов (строка «Массовое редактирование» таблицы редактора портов): накопленные в панели
// значения применяются ко всем отмеченным строкам разом (utils/interfaceBulkEdit.ts).
import { computed, ref } from 'vue'
import type { InterfaceDraftRow, VLANDefinition } from '../api/types'
import type { ManagedFields } from '../utils/interfaceGroups'
import { applyBulkEditToRows } from '../utils/interfaceBulkEdit'
import { useOverlayDismiss } from './useOverlayDismiss'
import { useToast } from './useToast'
import type { RowUiState } from './useRowUiState'

export interface BulkEditDeps {
  rows: () => InterfaceDraftRow[]
  setRows: (rows: InterfaceDraftRow[]) => void
  vlanOptions: () => VLANDefinition[]
  rowManaged: (row: InterfaceDraftRow) => ManagedFields
}

export function useBulkEdit(deps: BulkEditDeps, ui: RowUiState) {
  const { notify } = useToast()

  const bulkTypeId = ref('')
  const bulkSpeedId = ref('')
  const bulkManagement = ref('') // '' — не менять, 'true'/'false' — включить/выключить
  const bulkDataTransfer = ref('')
  const bulkVlanMode = ref('') // '' — не менять, 'access'/'trunk' — режим порта (п.1.4.3.2)
  const bulkVlanIds = ref<Set<string>>(new Set())
  // «Все VLAN» панели — тот же признак, что у порта (all_vlans), а не вывод из набора bulkVlanIds: ставится кликом по чекбоксу и
  // снимается любым ручным выбором VLAN.
  const bulkAllVlans = ref(false)
  // Список VLAN во всплывающем окне, а не в ячейке: при большом числе VLAN инлайновый список «растягивал» всю строку панели
  // (а с ней — всю таблицу). Сама ячейка показывает только краткую сводку.
  const bulkVlanPickerOpen = ref(false)
  const bulkVlanSummary = computed(() => (bulkAllVlans.value ? 'Все VLAN' : bulkVlanIds.value.size ? `Выбрано VLAN: ${bulkVlanIds.value.size}` : '— выбрать VLAN —'))
  const { onOverlayPointerDown: onVlanPickerOverlayPointerDown, onOverlayClick: onVlanPickerOverlayClick } = useOverlayDismiss(() => (bulkVlanPickerOpen.value = false))

  function toggleBulkVlan(vlanDefId: string, checked: boolean) {
    if (checked) bulkVlanIds.value.add(vlanDefId)
    else bulkVlanIds.value.delete(vlanDefId)
    bulkAllVlans.value = false
  }

  // Та же механика «Все VLAN», что у одиночного порта, только для панели: отмеченные порты получают признак «Все VLAN»
  // (а не просто набор из всех VLAN).
  function toggleBulkAllVlans(checked: boolean) {
    bulkAllVlans.value = checked
    bulkVlanIds.value = new Set(checked ? deps.vlanOptions().map((v) => v.id) : [])
  }

  function applyBulkEdit() {
    if (!ui.selectedIndices.value.size) {
      notify('Отметьте хотя бы один интерфейс галочкой "Выбрать".', 'error')
      return
    }
    deps.setRows(
      applyBulkEditToRows(
        deps.rows(),
        ui.selectedIndices.value,
        { typeId: bulkTypeId.value, speedId: bulkSpeedId.value, management: bulkManagement.value, dataTransfer: bulkDataTransfer.value, vlanMode: bulkVlanMode.value, vlanIds: bulkVlanIds.value, allVlans: bulkAllVlans.value },
        deps.vlanOptions(),
        (row) => deps.rowManaged(row).vlan,
      ),
    )
    // Полный сброс панели после применения: без сброса «не менять» показывал бы уже применённое значение, будто его можно применить ещё раз.
    ui.clearSelection()
    bulkTypeId.value = ''
    bulkSpeedId.value = ''
    bulkManagement.value = ''
    bulkDataTransfer.value = ''
    bulkVlanMode.value = ''
    bulkVlanIds.value = new Set()
    bulkAllVlans.value = false
    bulkVlanPickerOpen.value = false
  }

  return {
    bulkTypeId,
    bulkSpeedId,
    bulkManagement,
    bulkDataTransfer,
    bulkVlanMode,
    bulkVlanIds,
    bulkAllVlans,
    bulkVlanPickerOpen,
    bulkVlanSummary,
    onVlanPickerOverlayPointerDown,
    onVlanPickerOverlayClick,
    toggleBulkVlan,
    toggleBulkAllVlans,
    applyBulkEdit,
  }
}
