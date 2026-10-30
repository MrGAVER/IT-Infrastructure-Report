// Правки черновика группы портов в окне создания/правки (GroupEditModal.vue): чистые функции без Vue.
// Каждая возвращает НОВЫЙ черновик (или массив) и не трогает аргументы — окно подменяет ими своё состояние целиком.
import type { InterfaceGroupDraft, ProtocolPortCatalogEntry, SubinterfaceDraftRow, VLANDefinition } from '../api/types'
import { sortOpenPortRows } from './openPorts'

/** Глубокая копия группы для рабочего черновика окна: правки не должны задевать группу из списка до «Применить». */
export function cloneGroupForEdit(group: InterfaceGroupDraft): InterfaceGroupDraft {
  return {
    ...group,
    vlan_ids: [...group.vlan_ids],
    all_vlans: group.all_vlans === true,
    ips: group.ips.map((ip) => ({ ...ip })),
    open_ports: group.open_ports.map((p) => ({ ...p })),
    subinterfaces: (group.subinterfaces ?? []).map((sub) => ({
      ...sub,
      ips: sub.ips.map((ip) => ({ ...ip })),
      open_ports: sub.open_ports.map((p) => ({ ...p })),
    })),
  }
}

/**
 * Смена режима порта группы.
 * - access оставляет не более одного VLAN (тот же инвариант, что у порта);
 * - trunk сразу отмечает «Все VLAN» (как у порта, DeviceInterfacesEditor.vue: setVlanMode): пустой trunk — бесполезное
 *   стартовое состояние, а нужные VLAN снимаются в окне выбора. Если у устройства VLAN ещё нет, признак не ставится;
 * - «без режима» и access признак «Все VLAN» иметь не могут.
 */
export function setGroupVlanMode(group: InterfaceGroupDraft, mode: InterfaceGroupDraft['vlan_mode'], vlans: readonly VLANDefinition[]): InterfaceGroupDraft {
  const vlan_ids = mode === 'access' ? group.vlan_ids.slice(0, 1) : mode === 'trunk' ? vlans.map((v) => v.id) : []
  return { ...group, vlan_mode: mode, vlan_ids, all_vlans: mode === 'trunk' && vlans.length > 0 }
}

/** Единственный VLAN access-группы (пустая строка — VLAN не выбран). Признак «Все VLAN» снимается. */
export function setGroupAccessVlan(group: InterfaceGroupDraft, vlanId: string): InterfaceGroupDraft {
  return { ...group, vlan_ids: vlanId ? [vlanId] : [], all_vlans: false }
}

/** Ручной выбор VLAN снимает признак «Все VLAN» — даже если в итоге выбраны все: признак не выводится из набора. */
export function toggleGroupVlan(group: InterfaceGroupDraft, vlanId: string, checked: boolean): InterfaceGroupDraft {
  const ids = new Set(group.vlan_ids)
  if (checked) ids.add(vlanId)
  else ids.delete(vlanId)
  return { ...group, vlan_ids: [...ids], all_vlans: false }
}

/** «Все VLAN» в trunk-режиме — сохраняемый признак группы, а не вывод из числа выбранных VLAN. Пока он стоит, vlan_ids
 * зеркалит все VLAN устройства (сервер хранит только признак; порты группы получают его же). */
export function setGroupAllVlans(group: InterfaceGroupDraft, checked: boolean, vlans: readonly VLANDefinition[]): InterfaceGroupDraft {
  return { ...group, all_vlans: checked, vlan_ids: checked ? vlans.map((v) => v.id) : [] }
}

/** Сколько VLAN устройства выбрано в группе (id, которых нет среди VLAN устройства, не считаются). */
export function countSelectedVlans(vlanIds: readonly string[], vlans: readonly VLANDefinition[]): number {
  return vlans.filter((v) => vlanIds.includes(v.id)).length
}

/** VLAN, из которых выбирается VLAN подинтерфейса группы: те, что группа записывает своим портам (с «Все VLAN» — все VLAN
 * устройства). Без режима порта подинтерфейсы не задаются — список пуст, редактор подскажет почему. */
export function groupSubinterfaceVlans(group: InterfaceGroupDraft, vlans: readonly VLANDefinition[]): VLANDefinition[] {
  if (!group.vlan_mode) return []
  return group.vlan_mode === 'trunk' && group.all_vlans === true ? [...vlans] : vlans.filter((v) => group.vlan_ids.includes(v.id))
}

/** Шаблоны подинтерфейсов группы при сохранении: по возрастанию номера VLAN (неизвестный VLAN — в конце), открытые порты
 * каждого — по возрастанию порта. Исходный массив не меняется. */
export function normalizeGroupSubinterfaces(
  rows: readonly SubinterfaceDraftRow[],
  vlans: readonly VLANDefinition[],
  catalog: readonly ProtocolPortCatalogEntry[],
): SubinterfaceDraftRow[] {
  const number = (vlanId: string) => vlans.find((v) => v.id === vlanId)?.vlan_id ?? Number.MAX_SAFE_INTEGER
  return [...rows].sort((a, b) => number(a.vlan_id) - number(b.vlan_id)).map((sub) => ({ ...sub, open_ports: sortOpenPortRows(sub.open_ports, catalog) }))
}
