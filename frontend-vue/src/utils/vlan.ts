import type { VLANDefinition } from '../api/types'

/**
 * "10 — Гостевой [Филиал-1]" либо "10 — Гостевой", если VLAN не принадлежит домену. Общая
 * функция для DeviceVlanListEditor.vue (VLAN устройства) и DeviceInterfacesEditor.vue (VLAN
 * порта) — единый формат подписи VLAN в обоих местах.
 *
 * @example
 * vlanLabel({ vlan_id: 10, name: 'Гостевой', domain_name: 'Филиал-1', ... }) // '10 — Гостевой [Филиал-1]'
 */
export function vlanLabel(v: VLANDefinition): string {
  return v.domain_name ? `${v.vlan_id} — ${v.name} [${v.domain_name}]` : `${v.vlan_id} — ${v.name}`
}
