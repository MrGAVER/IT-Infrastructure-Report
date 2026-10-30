// Правки VLAN порта в редакторе портов (DeviceInterfacesEditor.vue): каждая функция возвращает частичную правку строки
// (`Partial<InterfaceDraftRow>`), которую вызывающая сторона применяет через updateRow. Чистые функции без Vue и сторов.
import type { InterfaceDraftRow, VLANDefinition } from '../api/types'

/** Отметить/снять один VLAN в наборе порта. Ручной выбор VLAN снимает признак «Все VLAN» — даже если в итоге выбраны все:
 * признак не выводится из числа VLAN. */
export function toggleVlanPatch(row: Pick<InterfaceDraftRow, 'vlan_ids'>, vlanDefId: string, checked: boolean): Partial<InterfaceDraftRow> {
  const vlan_ids = checked ? [...row.vlan_ids, vlanDefId] : row.vlan_ids.filter((id) => id !== vlanDefId)
  return { vlan_ids, all_vlans: false }
}

/** п.1.4.3.2: режим порта — access (ровно один VLAN) или trunk (несколько, в т.ч. «все»). */
export function vlanModePatch(
  row: Pick<InterfaceDraftRow, 'vlan_ids'>,
  mode: 'access' | 'trunk',
  vlanOptions: readonly VLANDefinition[],
): Partial<InterfaceDraftRow> {
  if (mode === 'access') {
    // При переключении в access оставляем только первый уже отмеченный VLAN — несколько было бы некорректным сочетанием
    // (см. validateInterfaceDraftRows).
    return { vlan_mode: 'access', vlan_ids: row.vlan_ids.slice(0, 1), all_vlans: false }
  }
  // Фикс п.2.1.1: переключение на trunk сразу ставит «Все VLAN» — сохраняемый признак (all_vlans), а vlan_ids зеркалит все
  // допустимые VLAN, чтобы форма показывала их отмеченными. Если у устройства VLAN ещё нет, признак не ставится — «всех»
  // пока нет, а порт не должен подхватывать VLAN, которые пользователь потом добавит, не выбирая «Все VLAN» осознанно.
  return { vlan_mode: 'trunk', vlan_ids: vlanOptions.map((v) => v.id), all_vlans: vlanOptions.length > 0 }
}

/** Access-порт: единственный VLAN (пустое значение — не выбран). */
export function accessVlanPatch(vlanDefId: string): Partial<InterfaceDraftRow> {
  return { vlan_ids: vlanDefId ? [vlanDefId] : [] }
}

/** «Все VLAN» в trunk-режиме — сохраняемый признак порта (колонка device_interfaces.all_vlans), а НЕ вывод из числа выбранных
 * VLAN. Пока признак стоит, vlan_ids зеркалит все допустимые VLAN устройства, а в БД хранится только признак. */
export function allVlansPatch(checked: boolean, vlanOptions: readonly VLANDefinition[]): Partial<InterfaceDraftRow> {
  return { all_vlans: checked, vlan_ids: checked ? vlanOptions.map((v) => v.id) : [] }
}
