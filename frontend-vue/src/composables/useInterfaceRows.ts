// Операции над списком портов редактора (DeviceInterfacesEditor.vue): добавить, удалить, переставить, изменить поле,
// переименовать порт и скопировать открытые порты на другой порт. Сам список — проп родителя: любое изменение уходит наверх
// через setRows (emit 'update:modelValue'), массив не мутируется.
import type { InterfaceDraftRow, ProtocolPortCatalogEntry, VLANDefinition } from '../api/types'
import { emptyInterfaceRow, clearReferencesTo, portNamePatch } from '../utils/interfaceRowDraft'
import type { ManagedFields } from '../utils/interfaceGroups'
import { moveRow, swapIndexes } from '../utils/interfaceOrder'
import { sortOpenPortRows } from '../utils/openPorts'
import { useToast } from './useToast'
import type { RowUiState } from './useRowUiState'

export interface InterfaceRowsDeps {
  rows: () => InterfaceDraftRow[]
  setRows: (rows: InterfaceDraftRow[]) => void
  /** Все известные VLAN (для пересчёта автоимён подинтерфейсов при переименовании порта). */
  knownVlans: () => readonly VLANDefinition[]
  protocolPortCatalog: () => readonly ProtocolPortCatalogEntry[]
  /** Показывается блок «Подключение»: новым строкам нужен ключ. */
  editConnections: () => boolean
  rowManaged: (row: InterfaceDraftRow) => ManagedFields
  groupLockNote: (row: InterfaceDraftRow, what: string) => string
}

export function useInterfaceRows(deps: InterfaceRowsDeps, ui: RowUiState) {
  const { notify } = useToast()

  const emptyRow = () => emptyInterfaceRow(deps.editConnections())

  function addRow() {
    ui.clearSelection()
    // п.1.4.3.1: новая строка НЕ разворачивается автоматически — блок VLAN/IP свёрнут по умолчанию для любой строки.
    deps.setRows([...deps.rows(), emptyRow()])
  }

  function removeRow(index: number) {
    const rows = deps.rows()
    ui.resetStructure()
    deps.setRows(
      clearReferencesTo(
        rows.filter((_, i) => i !== index),
        [rows[index]],
      ),
    )
  }

  /** Перестановка порта стрелками «вверх»/«вниз» в столбце порядка. Порядок строк массива и есть порядок, заданный
   * пользователем: он уходит на сервер вместе со списком портов и сохраняется (device_interfaces.sort_order). Отмеченные
   * галочкой и развёрнутые строки едут вместе со своим портом; выбор получателя в «Копировать» сбрасывается, как при
   * любом другом структурном изменении списка. */
  function moveRowBy(index: number, direction: -1 | 1) {
    const moved = moveRow(deps.rows(), index, direction)
    if (!moved) return
    const target = index + direction
    ui.selectedIndices.value = swapIndexes(ui.selectedIndices.value, index, target)
    ui.expandedIndices.value = swapIndexes(ui.expandedIndices.value, index, target)
    ui.copyTargetIndex.value = {}
    deps.setRows(moved)
  }

  function updateRow(index: number, patch: Partial<InterfaceDraftRow>) {
    deps.setRows(deps.rows().map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  /** Новое имя порта вместе с подинтерфейсами (utils/interfaceRowDraft.ts:portNamePatch). */
  function renamePort(index: number, name: string) {
    const row = deps.rows()[index]
    if (row) updateRow(index, portNamePatch(row, name, deps.knownVlans()))
  }

  /** Копирует набор открытых портов строки sourceIndex на targetIndex — именно КОПИРУЕТ (у источника порты остаются как
   * есть), а не переносит: id каждого порта сбрасывается, чтобы при сохранении backend/app/services/crud/interfaces.py:
   * _sync_interface_open_ports создал НОВЫЕ записи для целевого интерфейса, а не пытался переприсвоить владельца уже
   * существующих (порт физически размещён на одном порту устройства, скопировать можно только список технологий/протоколов).
   * Если у получателя уже есть открытые порты, требует подтверждения — молчаливая замена была бы неожиданной потерей данных. */
  function copyPortsTo(sourceIndex: number, targetIndex: number) {
    const rows = deps.rows()
    const source = rows[sourceIndex]
    const target = rows[targetIndex]
    if (!source || !target || sourceIndex === targetIndex || !source.open_ports.length) return
    const sourceLabel = source.name || `#${sourceIndex + 1}`
    const targetLabel = target.name || `#${targetIndex + 1}`
    if (deps.rowManaged(target).openPorts) {
      notify(deps.groupLockNote(target, `Список открытых портов порта «${targetLabel}»`), 'error')
      return
    }
    if (target.open_ports.length) {
      const ok = confirm(`На порту «${targetLabel}» уже есть открытые порты (${target.open_ports.length} шт.) — заменить их копией с «${sourceLabel}» (${source.open_ports.length} шт.)?`)
      if (!ok) return
    }
    // Копия упорядочивается по номеру порта — как список, к которому пользователь добавил порт кнопкой.
    updateRow(targetIndex, { open_ports: sortOpenPortRows(source.open_ports.map((p) => ({ ...p, id: undefined })), deps.protocolPortCatalog()) })
    notify(`Открытые порты скопированы с «${sourceLabel}» на «${targetLabel}».`, 'success')
    ui.setCopyTarget(sourceIndex, '')
  }

  /** Кнопка «Копировать» строки: получатель — выбранный в её списке порт. */
  function applyCopyPorts(sourceIndex: number) {
    const targetIndex = ui.copyTargetIndex.value[sourceIndex]
    if (!targetIndex) return
    copyPortsTo(sourceIndex, Number(targetIndex))
  }

  return { emptyRow, addRow, removeRow, moveRowBy, updateRow, renamePort, copyPortsTo, applyCopyPorts }
}
