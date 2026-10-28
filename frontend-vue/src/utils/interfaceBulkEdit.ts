// Массовое редактирование отмеченных портов (components/DeviceInterfacesEditor.vue, строка «Массовое редактирование»).
// Портировано из applyBulkInterfaceEdit() vanilla-версии. Чистая функция: входные строки не мутируются.
import type { InterfaceDraftRow, VLANDefinition } from '../api/types'

/** Значения панели. Пустая строка в поле — «не менять»; для флажков `'true'`/`'false'` — включить/выключить. */
export interface BulkEditValues {
  typeId: string
  speedId: string
  management: string
  dataTransfer: string
  /** '' — не менять, 'access'/'trunk' — режим порта (п.1.4.3.2). */
  vlanMode: string
  vlanIds: ReadonlySet<string> | readonly string[]
  /** «Все VLAN» панели — тот же признак, что у порта (all_vlans), а не вывод из набора vlanIds. */
  allVlans: boolean
}

/**
 * Применяет значения панели к строкам с индексами из `selected`. Поля со значением «не менять» не трогают соответствующее
 * поле; VLAN добавляется К уже стоящим на порту (объединение множеств, не замена) — случайно снять чужой VLAN массовым
 * действием хуже, чем ничего не убрать. Режим и VLAN порта, чей набор задаёт группа (`isVlanLocked`), не меняются.
 */
export function applyBulkEditToRows(
  rows: readonly InterfaceDraftRow[],
  selected: ReadonlySet<number>,
  values: BulkEditValues,
  vlanOptions: readonly VLANDefinition[],
  isVlanLocked: (row: InterfaceDraftRow) => boolean,
): InterfaceDraftRow[] {
  const vlanIds = [...values.vlanIds]
  return rows.map((row, i) => {
    if (!selected.has(i)) return row
    const vlanLocked = isVlanLocked(row)
    const vlan_mode = (vlanLocked ? row.vlan_mode : values.vlanMode || row.vlan_mode) as 'access' | 'trunk'
    let vlan_ids = vlanLocked ? row.vlan_ids : vlanIds.length ? Array.from(new Set([...row.vlan_ids, ...vlanIds])) : row.vlan_ids
    // access допускает не более одного VLAN — если массовое действие переключает режим в access (или строка уже была в
    // access, а панель добавляет VLAN), лишние отбрасываем, чтобы не сохранить некорректную комбинацию.
    if (vlan_mode === 'access' && vlan_ids.length > 1) vlan_ids = vlan_ids.slice(0, 1)
    // Признак «Все VLAN» держится, пока порт в trunk и его набор не менялся вручную; панель с «Все VLAN» ставит его
    // отмеченным trunk-портам (vlan_ids при этом зеркалит все допустимые VLAN), в access он невозможен.
    let all_vlans = vlan_mode === 'trunk' && row.all_vlans === true
    if (!vlanLocked && values.allVlans && vlan_mode === 'trunk') {
      all_vlans = true
      vlan_ids = vlanOptions.map((v) => v.id)
    }
    return {
      ...row,
      interface_type_id: values.typeId || row.interface_type_id,
      speed_id: values.speedId || row.speed_id,
      is_management: values.management === '' ? row.is_management : values.management === 'true',
      is_data_transfer: values.dataTransfer === '' ? row.is_data_transfer : values.dataTransfer === 'true',
      vlan_mode,
      vlan_ids,
      all_vlans,
    }
  })
}
