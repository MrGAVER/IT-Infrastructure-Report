// Группа порта и то, чем она управляет (редактор портов, DeviceInterfacesEditor.vue). Управляемые группой поля в строке
// заблокированы: чтобы задать порту своё значение, его сначала выводят из группы (значения при этом остаются в порте).
import type { InterfaceDraftRow, InterfaceGroupDraft } from '../api/types'
import { findGroup, managedFields, type ManagedFields } from '../utils/interfaceGroups'

export interface GroupLocks {
  rowGroup: (row: InterfaceDraftRow) => InterfaceGroupDraft | undefined
  rowManaged: (row: InterfaceDraftRow) => ManagedFields
  /** Подсказка у заблокированного поля: что именно задано группой и как это изменить. */
  groupLockNote: (row: InterfaceDraftRow, what: string) => string
}

/** @param groups — группы портов устройства (геттер, чтобы подхватывать новые значения пропа). */
export function useGroupLocks(groups: () => InterfaceGroupDraft[]): GroupLocks {
  const rowGroup = (row: InterfaceDraftRow) => findGroup(row, groups())
  const rowManaged = (row: InterfaceDraftRow) => managedFields(rowGroup(row))
  const groupLockNote = (row: InterfaceDraftRow, what: string) => `${what} задан группой «${rowGroup(row)?.name ?? ''}» — измените в группе или выведите порт из группы.`
  return { rowGroup, rowManaged, groupLockNote }
}
