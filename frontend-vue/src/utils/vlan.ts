import type { DeviceVlanDraftRow, VLANDefinition } from '../api/types'

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

/**
 * Пункт 4 правки "включение в домен VLAN": возвращает черновик VLAN устройства, дополненный VLAN
 * выбранного домена (VLAN.domain_id === domainId), которых в нём ещё нет. Строки идут в порядке
 * возрастания номера VLAN и добавляются В КОНЕЦ — уже введённые пользователем строки (в том
 * числе пустые, ещё не выбранные) не переставляются и не затрагиваются. Чистая функция: входной
 * массив не мутируется, при отсутствии новых VLAN возвращается ТОТ ЖЕ массив (можно сравнивать по
 * ссылке, чтобы не вызывать лишний реактивный апдейт).
 *
 * Зеркалит бэкенд (services/crud.py:assign_domain_vlans_to_device): description строки берётся из
 * определения VLAN, IP/префикс пустые, is_management выключен. Зачем это нужно на фронтенде: форма
 * устройства приводит VLAN устройства в БД ровно к черновику (api/deviceVlans.ts:persistDeviceVlans),
 * поэтому VLAN, которые бэкенд назначит при создании членства, но которых нет в черновике, были бы
 * тут же удалены при том же сохранении.
 *
 * @example
 * mergeDomainVlansIntoDraft([], definitions, 'dom-1') // [{ vlan_id: 'v-10', ip_address: '', ... }, ...]
 */
export function mergeDomainVlansIntoDraft(
  rows: DeviceVlanDraftRow[],
  definitions: VLANDefinition[],
  domainId: string,
): DeviceVlanDraftRow[] {
  const present = new Set(rows.map((r) => r.vlan_id).filter(Boolean))
  const toAdd = definitions
    .filter((d) => d.domain_id === domainId && !present.has(d.id))
    .sort((a, b) => a.vlan_id - b.vlan_id)
  if (!toAdd.length) return rows
  return [
    ...rows,
    ...toAdd.map<DeviceVlanDraftRow>((d) => ({
      vlan_id: d.id,
      ip_address: '',
      prefix_length: '',
      is_management: false,
      description: d.description ?? '',
    })),
  ]
}

/**
 * Обратная к mergeDomainVlansIntoDraft: убирает из черновика НЕсохранённые строки (без id), чей VLAN
 * принадлежит домену domainId. Нужна при отмене ещё не сохранённого включения в домен: без
 * членства такие строки бэкенд всё равно отклонил бы 422 («Устройство не включено в домен этого
 * VLAN», _validate_physical_device_vlan), в том числе строки, которые пользователь выбрал вручную
 * уже после «Включить». Сохранённые строки (с id) не трогаются — они не могут принадлежать домену,
 * членства в котором ещё нет. Возвращает ТОТ ЖЕ массив, если убирать нечего.
 */
export function removeDomainVlansFromDraft(
  rows: DeviceVlanDraftRow[],
  definitions: VLANDefinition[],
  domainId: string,
): DeviceVlanDraftRow[] {
  const domainVlanIds = new Set(definitions.filter((d) => d.domain_id === domainId).map((d) => d.id))
  const kept = rows.filter((r) => r.id || !domainVlanIds.has(r.vlan_id))
  return kept.length === rows.length ? rows : kept
}
