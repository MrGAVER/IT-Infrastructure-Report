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

/**
 * Список VLAN, доступных для назначения устройству в блоке "VLAN устройства". Правило зависит от
 * того, состоит ли устройство в доменах VLAN (сохранённо или с отложенным до сохранения
 * включением — вызывающий код передаёт объединение обоих множеств):
 * - устройство НЕ в домене — только VLAN без домена (доменные чужие, показывать их нельзя: бэкенд
 *   отклонит назначение 422 "Устройство не включено в домен этого VLAN");
 * - устройство в одном или нескольких доменах — ТОЛЬКО VLAN этих доменов, VLAN без домена
 *   скрываются (иначе список засоряется общими VLAN, хотя устройство работает в рамках домена).
 *
 * Чистая функция: порядок VLAN сохраняется как во входном массиве, сам массив не мутируется.
 *
 * @example
 * filterVlansForDeviceDomains(definitions, new Set(['dom-1'])) // только VLAN домена dom-1
 * filterVlansForDeviceDomains(definitions, new Set())          // только VLAN без домена
 */
export function filterVlansForDeviceDomains(
  definitions: VLANDefinition[],
  deviceDomainIds: ReadonlySet<string>,
): VLANDefinition[] {
  if (!deviceDomainIds.size) return definitions.filter((d) => !d.domain_id)
  return definitions.filter((d) => !!d.domain_id && deviceDomainIds.has(d.domain_id))
}

/**
 * Приводит vlan_ids порта или группы портов в соответствие с изменением списка допустимых VLAN
 * устройства (oldOptions → newOptions). Одна и та же логика для портов и для групп — иначе группа
 * расходилась бы со своими портами, а сервер, применяя группу к портам, затирал бы значения порта.
 *
 * 1. VLAN, переставшие быть допустимыми, убираются из vlan_ids.
 * 2. Если появились новые VLAN и порт/группа в trunk-режиме имеет выбранными ВСЕ прежние опции
 *    («Все VLAN» — состояние, а не флаг), новые VLAN добавляются в конец: «Все VLAN» остаётся правдой.
 *    Правило не применяется, когда прежних опций не было (первая загрузка устройства: «все выбраны» было бы
 *    истинно вырожденно и раздало бы новые VLAN всем trunk-портам без разбора).
 *
 * Чистая функция: входной массив не мутируется; если менять нечего — возвращается ТОТ ЖЕ массив
 * (можно сравнивать по ссылке и не вызывать лишний реактивный апдейт).
 *
 * @example
 * reconcileVlanIds(['a', 'b'], 'trunk', [{ id: 'a' }, { id: 'b' }], [{ id: 'a' }, { id: 'b' }, { id: 'c' }]) // ['a', 'b', 'c']
 */
export function reconcileVlanIds(
  vlanIds: string[],
  vlanMode: string,
  oldOptions: readonly { id: string }[],
  newOptions: readonly { id: string }[],
): string[] {
  const oldIds = new Set(oldOptions.map((o) => o.id))
  const newIds = new Set(newOptions.map((o) => o.id))
  const removedIds = oldOptions.filter((o) => !newIds.has(o.id)).map((o) => o.id)
  const addedIds = newOptions.filter((o) => !oldIds.has(o.id)).map((o) => o.id)

  let next = vlanIds
  if (removedIds.length && next.some((id) => removedIds.includes(id))) {
    next = next.filter((id) => !removedIds.includes(id))
  }
  // Проверка «все прежние опции выбраны» идёт по уже очищенному списку: если одновременно что-то
  // убрали из выбранных, «Все VLAN» уже не было полным — новые VLAN не добавляем.
  if (addedIds.length && oldOptions.length > 0 && vlanMode === 'trunk' && oldOptions.every((o) => next.includes(o.id))) {
    next = [...next, ...addedIds]
  }
  return next
}

/**
 * Фильтрует список VLAN по строке поиска (окно выбора VLAN группы портов). Ищет по тому же тексту, что
 * видит пользователь, — vlanLabel(): номер, имя и домен, без учёта регистра. Запрос из нескольких слов —
 * должны встретиться ВСЕ слова, в любом порядке («серверы 110»). Порядок исходного списка сохраняется.
 * Пустой запрос возвращает ТОТ ЖЕ массив (не создаёт лишнего реактивного апдейта).
 *
 * @example
 * filterVlansByQuery(vlans, 'гост 20') // [{ vlan_id: 20, name: 'Гостевой', ... }]
 */
export function filterVlansByQuery<T extends VLANDefinition>(vlans: T[], query: string): T[] {
  const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  if (!tokens.length) return vlans
  return vlans.filter((v) => {
    const label = vlanLabel(v).toLowerCase()
    return tokens.every((token) => label.includes(token))
  })
}

/**
 * Текст уведомления, когда VLAN, снятые с устройства, были убраны и из групп портов (reconcileVlanIds
 * делает это молча — пользователь должен узнать, что группа изменилась). Возвращает null, если ни одна
 * группа ничего не потеряла.
 *
 * `before` и `after` сопоставляются ПО ИНДЕКСУ (после reconcileVlanIds порядок групп не меняется).
 * VLAN в сообщении — без повторов, в порядке списка прежних опций (oldOptions); VLAN, которого в опциях
 * нет, показывается идентификатором. Группы — в порядке списка, нетронутые не упоминаются.
 *
 * @example
 * groupVlanRemovalMessage([{ name: 'Транки', vlan_ids: ['a', 'b'] }], [{ name: 'Транки', vlan_ids: ['a'] }], options)
 * // 'Снятые с устройства VLAN (20 — Гости) убраны и из групп портов: «Транки».'
 */
export function groupVlanRemovalMessage(
  before: readonly { name: string; vlan_ids: string[] }[],
  after: readonly { name: string; vlan_ids: string[] }[],
  oldOptions: readonly VLANDefinition[],
): string | null {
  const lostIds = new Set<string>()
  const groupNames: string[] = []
  before.forEach((group, i) => {
    const kept = new Set(after[i]?.vlan_ids ?? [])
    const lost = group.vlan_ids.filter((id) => !kept.has(id))
    if (!lost.length) return
    lost.forEach((id) => lostIds.add(id))
    groupNames.push(`«${group.name.trim() || 'без названия'}»`)
  })
  if (!groupNames.length) return null

  const labelById = new Map(oldOptions.map((v) => [v.id, vlanLabel(v)]))
  const orderedIds = [...oldOptions.map((v) => v.id).filter((id) => lostIds.has(id)), ...[...lostIds].filter((id) => !labelById.has(id))]
  const labels = orderedIds.map((id) => labelById.get(id) ?? id)
  return `Снятые с устройства VLAN (${labels.join(', ')}) убраны и из групп портов: ${groupNames.join(', ')}.`
}
