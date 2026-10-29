// Тексты и сводки строк редактора портов (components/DeviceInterfacesEditor.vue): подписи свёрнутой строки, всплывающие
// подсказки и описания расхождений с соседним портом. Чистые функции без Vue и сторов — проверяются отдельно от компонента.
import type { InterfaceDraftRow, PortConflictInfo, VLANDefinition } from '../api/types'
import { SELF_DEVICE, peerRef, rowRef, type ConfigDiffKind } from './interfaceConnections'
import { subinterfacesOffPortVlans } from './subinterfaces'
import { vlanLabel } from './vlan'

/** Что именно разошлось с подключённым портом: назначение (Управление / Передача данных), режим порта или «Все VLAN». */
export type ConflictKind = ConfigDiffKind

const CONFLICT_TITLES: Record<ConflictKind, string> = {
  flags: 'Расхождение назначения порта',
  vlan_mode: 'Расхождение режима порта',
  all_vlans: 'Расхождение «Все VLAN»',
}

/** Заголовок окна решения расхождения. */
export function conflictTitle(kind: ConflictKind): string {
  return CONFLICT_TITLES[kind]
}

/** Подсказка у значка расхождения: что именно отличается на связанном порту. */
export function conflictSummary(conflict: PortConflictInfo, kind: ConflictKind): string {
  const where = `${conflict.otherDeviceName} · ${conflict.otherInterfaceName}`
  if (kind === 'flags') return `На связанном порту (${where}) указано другое назначение (Управление/Передача данных).`
  if (kind === 'all_vlans') return `На связанном порту (${where}) ${conflict.other.all_vlans ? 'стоит' : 'не стоит'} «Все VLAN».`
  return `На связанном порту (${where}) установлен другой режим порта (Trunk/Access).`
}

/** Краткая сводка для свёрнутой строки таблицы (ячейка "VLAN / IP") — показывает режим порта,
 * не разворачивая деталь. Для access с ещё не выбранным VLAN — просто "Access", без "0 VLAN"
 * (звучало бы как ошибка, хотя это обычное промежуточное состояние при заполнении формы). */
export function vlanCellSummary(row: InterfaceDraftRow, vlanOptions: readonly VLANDefinition[]): string {
  if (row.vlan_mode === 'access') {
    const vlan = vlanOptions.find((v) => v.id === row.vlan_ids[0])
    return vlan ? `Access: ${vlanLabel(vlan)}` : 'Access'
  }
  return row.all_vlans ? `Trunk · все VLAN (${row.vlan_ids.length})` : `Trunk · ${row.vlan_ids.length} VLAN`
}

/** Сводка набора VLAN trunk-порта рядом с кнопкой выбора: с признаком «Все VLAN» — число всех VLAN устройства. */
export function trunkVlanSummary(row: InterfaceDraftRow, vlanOptions: readonly VLANDefinition[]): string {
  const selected = vlanOptions.filter((v) => row.vlan_ids.includes(v.id)).length
  return `Выбрано VLAN: ${selected} из ${vlanOptions.length}`
}

/** Всплывающая подсказка со списком выбранных VLAN trunk-порта (длинный список в строку не помещается). */
export function trunkVlanTitle(row: InterfaceDraftRow, vlanOptions: readonly VLANDefinition[]): string {
  const labels = vlanOptions.filter((v) => row.vlan_ids.includes(v.id)).map((v) => vlanLabel(v))
  return labels.length ? labels.join('\n') : 'VLAN не выбраны'
}

/** Значок на свёрнутой строке порта: подинтерфейсы, VLAN которых выбрать уже нельзя, — он не выбран на порту (убран с порта)
 * либо снят с устройства. VLAN подинтерфейса выбирается из VLAN порта (см. InterfaceSubinterfacesEditor), поэтому такой
 * подинтерфейс нужно перенести на другой VLAN порта или удалить — иначе форма не сохранится. Пустая строка — предупреждать не о чем. */
export function staleSubinterfaceText(row: InterfaceDraftRow, allowedVlanIds: ReadonlySet<string>): string {
  const names = subinterfacesOffPortVlans(row, allowedVlanIds).map((sub) => `«${sub.name.trim() || 'без имени'}»`)
  return names.length ? `Подинтерфейсы на VLAN, не выбранном на порту или не назначенном устройству: ${names.join(', ')} — выберите другой VLAN или удалите их` : ''
}

/** Подсказка у индикатора повторяющихся номеров открытых портов (utils/openPorts.ts:duplicatePortNumbers). */
export function duplicatePortsText(numbers: readonly number[]): string {
  return `Повторяются номера открытых портов: ${numbers.join(', ')}`
}

/** Краткая подпись подключения порта для свёрнутой строки: сосед на другом устройстве либо другой порт этого же. */
export function connectionSummary(row: InterfaceDraftRow, rows: readonly InterfaceDraftRow[], deviceId: string | null): string {
  const draft = row.connection
  if (!draft) return ''
  const ref = peerRef(draft)
  if (!ref) return '↔ порт не выбран'
  if (draft.peer_row_key || draft.peer_device_id === (deviceId ?? SELF_DEVICE)) {
    const target = rows.find((r) => rowRef(r) === ref)
    return `↔ это устройство · ${target ? target.name.trim() || 'без имени' : '?'}`
  }
  return `↔ ${draft.peer_device_name ?? '?'} · ${draft.peer_interface_name ?? '?'}`
}
