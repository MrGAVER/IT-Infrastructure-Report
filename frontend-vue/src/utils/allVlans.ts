// Сверка признака «Все VLAN» порта с портом на другом конце подключения (блок «Подключение» формы устройства,
// диалоги расхождения и проверка перед сохранением). Чистые функции без Vue и запросов.
//
// «Все VLAN» — сохраняемый признак порта (backend models.DeviceInterface.all_vlans), значимый ТОЛЬКО в trunk: порт с
// признаком несёт все VLAN своего устройства, в том числе добавленные ему позже. Поэтому сравниваются именно признаки,
// а не наборы номеров VLAN: «все VLAN» устройства A и «все VLAN» устройства B — разные наборы номеров, но одна и та же
// настройка. Наборы, выбранные вручную (без признака), здесь не сверяются — их сверяет экран «Подключения».
//
// Расхождение признака имеет смысл, только когда оба порта в trunk: если режимы разные, расхождение уже описано режимом, а
// смена режима на access сама снимает признак. Что именно записать порту, которому признак нужно привести к соседу, решает
// пользователь (окно AllVlansChoiceModal.vue): значение источника («Все VLAN» либо набор номеров VLAN, перенесённый на VLAN
// устройства порта) или другое значение.
import type { VLANDefinition, VlanMode } from '../api/types'
import { formatVlans } from './portConfig'
import { vlanIdsForNumbers } from './portEdit'

/** То, что нужно знать о порте для сверки «Все VLAN»: режим и признак (в access признак не действует). */
export interface AllVlansState {
  vlan_mode: VlanMode
  all_vlans?: boolean
}

/** Несёт ли порт «все VLAN устройства»: признак стоит и режим trunk. */
export function carriesAllVlans(port: AllVlansState): boolean {
  return port.vlan_mode === 'trunk' && port.all_vlans === true
}

/** «Все VLAN» в trunk-режиме строки редактора портов — сохраняемый признак порта (InterfaceDraftRow.all_vlans, колонка
 * device_interfaces.all_vlans), а НЕ вывод из числа выбранных VLAN: порт, у которого вручную отмечены все VLAN,
 * признака не имеет, и наоборот. Пока признак стоит, vlan_ids зеркалит все допустимые VLAN устройства (так форма
 * показывает их отмеченными), а в БД хранится только признак — набор вычисляется из VLAN устройства. Режим здесь не
 * проверяется (в отличие от carriesAllVlans): так решает, отмечена ли галочка, а не несёт ли порт все VLAN. */
export function isAllVlansSelected(port: { all_vlans?: boolean }): boolean {
  return port.all_vlans === true
}

/** Расходятся ли порты по «Все VLAN»: оба в trunk, и признак есть только у одного из них. */
export function allVlansDiffer(own: AllVlansState, peer: AllVlansState): boolean {
  return own.vlan_mode === 'trunk' && peer.vlan_mode === 'trunk' && carriesAllVlans(own) !== carriesAllVlans(peer)
}

/** Значение VLAN trunk-порта, которое записывается порту: признак «Все VLAN» либо выбранные VLAN (id записей справочника
 * ЭТОГО устройства). При allVlans = true vlanIds не используется. */
export interface VlanValue {
  allVlans: boolean
  vlanIds: string[]
}

/** VLAN порта-источника: признак либо номера VLAN (id у устройств разные, номера — общие). */
export interface PortVlanSource {
  allVlans: boolean
  numbers: readonly number[]
}

/**
 * Значение, которое получит порт-цель, если взять его у источника: «Все VLAN» переносится признаком, набор — по НОМЕРАМ
 * VLAN на VLAN устройства цели. Номера, которых у цели нет, не назначаются и возвращаются в `missing`.
 *
 * @example
 * valueFromSource({ allVlans: false, numbers: [10, 20, 99] }, targetOptions)
 * // { value: { allVlans: false, vlanIds: [<id VLAN 10>, <id VLAN 20>] }, missing: [99] }
 */
export function valueFromSource(source: PortVlanSource, targetOptions: readonly VLANDefinition[]): { value: VlanValue; missing: number[] } {
  if (source.allVlans) return { value: { allVlans: true, vlanIds: [] }, missing: [] }
  const { ids, missing } = vlanIdsForNumbers(targetOptions, source.numbers)
  return { value: { allVlans: false, vlanIds: ids }, missing }
}

/** Краткое описание значения для окна и сообщений: «Все VLAN», «VLAN 10, 20», «VLAN не выбраны». */
export function describeVlanValue(value: VlanValue, options: readonly VLANDefinition[]): string {
  if (value.allVlans) return 'Все VLAN'
  const chosen = new Set(value.vlanIds)
  const numbers = options.filter((o) => chosen.has(o.id)).map((o) => o.vlan_id)
  return numbers.length ? `VLAN ${formatVlans(numbers)}` : 'VLAN не выбраны'
}

/** Значение для окна выбора VLAN (PortVlanPickerModal): «Все VLAN» отмечает все VLAN устройства — так форма показывает их у такого порта. */
export function pickerSelection(value: VlanValue, options: readonly VLANDefinition[]): string[] {
  return value.allVlans ? options.map((o) => o.id) : value.vlanIds
}

/** Значение после клика по одному VLAN в окне выбора: ручной выбор снимает признак «Все VLAN». */
export function toggleValueVlan(value: VlanValue, vlanId: string, checked: boolean, options: readonly VLANDefinition[]): VlanValue {
  const current = pickerSelection(value, options)
  const next = checked ? [...new Set([...current, vlanId])] : current.filter((id) => id !== vlanId)
  return { allVlans: false, vlanIds: next }
}

/** Значение после клика по «Все VLAN» в окне выбора. */
export function toggleValueAll(checked: boolean): VlanValue {
  return { allVlans: checked, vlanIds: [] }
}
