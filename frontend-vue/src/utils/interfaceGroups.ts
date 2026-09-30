// Группы портов устройства: чистые функции над черновиками (InterfaceDraftRow / InterfaceGroupDraft).
//
// Группа хранит параметры, одинаковые у многих портов (режим порта + VLAN, общий IP, открытые порты),
// один раз. Значения МАТЕРИАЛИЗУЮТСЯ в строки портов — applyGroupToRow() записывает их прямо в поля
// строки, поэтому таблица портов, валидация и сохранение работают с итоговыми значениями порта, как
// и без групп, а сервер (backend services/crud.py:_apply_group_to_interface) применяет те же
// правила ещё раз и является источником истины.
//
// Модуль не знает ни про Vue, ни про API — вся логика тестируется отдельно (см. __tests__).
import type { InterfaceDraftRow, InterfaceGroupDraft, OpenPortDraftRow } from '../api/types'
import { isValidIPv4, isValidPrefixLength } from './ipValidation'

let groupKeyCounter = 0

/** Временный ключ новой группы: по нему порты ссылаются на группу, у которой ещё нет id. */
export function newGroupKey(): string {
  groupKeyCounter += 1
  return `new-group-${groupKeyCounter}`
}

export function emptyGroup(name = ''): InterfaceGroupDraft {
  return { key: newGroupKey(), name, vlan_mode: '', vlan_ids: [], ip_address: '', prefix_length: '', manage_open_ports: false, open_ports: [] }
}

export interface ManagedFields {
  vlan: boolean
  ip: boolean
  openPorts: boolean
}

/** Какими параметрами порта управляет группа (заданные в группе). */
export function managedFields(group: InterfaceGroupDraft | undefined): ManagedFields {
  if (!group) return { vlan: false, ip: false, openPorts: false }
  return { vlan: group.vlan_mode !== '', ip: group.ip_address.trim() !== '', openPorts: group.manage_open_ports }
}

export function findGroup(row: InterfaceDraftRow, groups: InterfaceGroupDraft[]): InterfaceGroupDraft | undefined {
  return row.group_key ? groups.find((g) => g.key === row.group_key) : undefined
}

/** Индексы портов, входящих в группу. */
export function memberIndices(rows: InterfaceDraftRow[], groupKey: string): number[] {
  return rows.flatMap((row, i) => (row.group_key === groupKey ? [i] : []))
}

function portKey(p: { protocol_catalog_id: string; transport_protocol: string }): string {
  return `${p.protocol_catalog_id}|${p.transport_protocol || 'TCP'}`
}

/** Записывает в строку значения параметров, которыми управляет группа. Строки IP и открытых
 * портов, совпадающие по смыслу с уже стоящими на порту, сохраняют свой id (сервер обновит их на
 * месте, а не пересоздаст). Незаданные группой параметры строки не трогаются. */
export function applyGroupToRow(row: InterfaceDraftRow, group: InterfaceGroupDraft): InterfaceDraftRow {
  const managed = managedFields(group)
  let next = row
  if (managed.vlan) {
    next = { ...next, vlan_mode: group.vlan_mode as 'access' | 'trunk', vlan_ids: [...group.vlan_ids] }
  }
  if (managed.ip) {
    const first = row.ips[0]
    next = { ...next, ips: [{ id: first?.id, ip_address: group.ip_address.trim(), prefix_length: group.prefix_length, purpose: first?.purpose ?? '' }] }
  }
  if (managed.openPorts) {
    const reusable = new Map<string, string | undefined>()
    for (const existing of row.open_ports) if (!reusable.has(portKey(existing))) reusable.set(portKey(existing), existing.id)
    const seen = new Set<string>()
    const ports: OpenPortDraftRow[] = []
    for (const p of group.open_ports) {
      if (!p.protocol_catalog_id || seen.has(portKey(p))) continue
      seen.add(portKey(p))
      ports.push({ id: reusable.get(portKey(p)), protocol_catalog_id: p.protocol_catalog_id, transport_protocol: p.transport_protocol || 'TCP', description: p.description })
    }
    next = { ...next, open_ports: ports }
  }
  return next
}

/** Применяет группы ко всем их портам (порты вне групп и с неизвестным ключом не меняются). */
export function applyGroupsToRows(rows: InterfaceDraftRow[], groups: InterfaceGroupDraft[]): InterfaceDraftRow[] {
  return rows.map((row) => {
    const group = findGroup(row, groups)
    return group ? applyGroupToRow(row, group) : row
  })
}

/** Стирает у строки значения тех параметров, которыми управляла группа («стереть значения» при
 * удалении группы). Режим порта возвращается к значению по умолчанию для нового порта — access. */
export function eraseGroupValues(row: InterfaceDraftRow, group: InterfaceGroupDraft): InterfaceDraftRow {
  const managed = managedFields(group)
  let next = row
  if (managed.vlan) next = { ...next, vlan_mode: 'access', vlan_ids: [] }
  if (managed.ip) next = { ...next, ips: [] }
  if (managed.openPorts) next = { ...next, open_ports: [] }
  return next
}

/** Какие параметры группы можно скопировать с порта — только те, у которых на порту есть значение:
 * режим порта копируется вместе с VLAN (режим без VLAN ничего не задаёт), IP — если есть хотя бы
 * один непустой адрес, открытые порты — если выбран хотя бы один протокол справочника. Так
 * «копирование» не может случайно превратиться в «стереть у всей группы». */
export function copyableFields(row: InterfaceDraftRow): ManagedFields {
  return {
    vlan: row.vlan_ids.length > 0,
    ip: row.ips.some((ip) => ip.ip_address.trim() !== ''),
    openPorts: row.open_ports.some((p) => p.protocol_catalog_id !== ''),
  }
}

/** Копирует значения порта в черновик группы — только отмеченные в `what` и реально имеющиеся на
 * порту (см. copyableFields). Это правка черновика в окне группы: к портам она применяется, как и
 * любое другое значение, только при сохранении группы. Строки открытых портов копируются без id —
 * это новые строки группы, а не те же записи порта. У порта с несколькими IP берётся первый: группа
 * задаёт один общий адрес. */
export function copyValuesFromRow(group: InterfaceGroupDraft, row: InterfaceDraftRow, what: ManagedFields): InterfaceGroupDraft {
  const available = copyableFields(row)
  let next = group
  if (what.vlan && available.vlan) {
    next = { ...next, vlan_mode: row.vlan_mode, vlan_ids: row.vlan_mode === 'access' ? row.vlan_ids.slice(0, 1) : [...row.vlan_ids] }
  }
  if (what.ip && available.ip) {
    const ip = row.ips.find((x) => x.ip_address.trim() !== '')!
    next = { ...next, ip_address: ip.ip_address.trim(), prefix_length: ip.prefix_length }
  }
  if (what.openPorts && available.openPorts) {
    next = {
      ...next,
      manage_open_ports: true,
      open_ports: row.open_ports
        .filter((p) => p.protocol_catalog_id !== '')
        .map((p) => ({ protocol_catalog_id: p.protocol_catalog_id, transport_protocol: p.transport_protocol || 'TCP', description: p.description })),
    }
  }
  return next
}

/** Порт входит не более чем в одну группу: задаёт состав группы `groupKey` равным `members` —
 * добавленные порты переходят в неё из прежних групп, исключённые остаются без группы. */
export function setGroupMembers(rows: InterfaceDraftRow[], groupKey: string, members: ReadonlySet<number>): InterfaceDraftRow[] {
  return rows.map((row, i) => {
    if (members.has(i)) return row.group_key === groupKey ? row : { ...row, group_key: groupKey }
    return row.group_key === groupKey ? { ...row, group_key: '' } : row
  })
}

/** Краткое описание того, что задаёт группа, для списка групп («Access · VLAN 10 · IP 10.0.0.5/24»). */
export function describeGroup(group: InterfaceGroupDraft, vlanLabel: (vlanDefinitionId: string) => string, portLabel: (catalogId: string) => string): string {
  const parts: string[] = []
  if (group.vlan_mode) {
    const vlans = group.vlan_ids.map(vlanLabel).join(', ')
    parts.push(`${group.vlan_mode === 'access' ? 'Access' : 'Trunk'}${vlans ? ` · ${vlans}` : ''}`)
  }
  if (group.ip_address.trim()) parts.push(`IP ${group.ip_address.trim()}${group.prefix_length !== '' ? `/${group.prefix_length}` : ''}`)
  if (group.manage_open_ports) {
    const labels = group.open_ports.filter((p) => p.protocol_catalog_id).map((p) => portLabel(p.protocol_catalog_id))
    parts.push(labels.length ? `Открытые порты: ${labels.join(', ')}` : 'Открытые порты: нет')
  }
  return parts.length ? parts.join(' · ') : 'Параметры не заданы'
}

/** Проверка групп перед сохранением: понятная ошибка сразу, а не 422 сервера. null — всё верно. */
export function validateInterfaceGroups(groups: InterfaceGroupDraft[]): string | null {
  const names = new Set<string>()
  for (const group of groups) {
    const name = group.name.trim()
    if (!name) return 'У каждой группы портов должно быть наименование.'
    if (names.has(name.toLowerCase())) return `Наименования групп портов должны быть уникальны — «${name}» повторяется.`
    names.add(name.toLowerCase())
    if (group.vlan_mode === 'access' && group.vlan_ids.length > 1) return `В режиме access у группы «${name}» может быть не более одного VLAN.`
    if (!isValidIPv4(group.ip_address)) return `Некорректный IP-адрес «${group.ip_address}» группы «${name}».`
    if (!isValidPrefixLength(group.prefix_length)) return `Некорректный префикс «${group.prefix_length}» группы «${name}» — допустимо 0-32.`
  }
  return null
}

/** Копия устройства: у нового устройства нет групп донора, поэтому группы копируются заново —
 * без id, под новыми ключами, а порты перевязываются на эти ключи. */
export function cloneGroupsForCopy(
  groups: InterfaceGroupDraft[],
  rows: InterfaceDraftRow[],
): { groups: InterfaceGroupDraft[]; rows: InterfaceDraftRow[] } {
  const keyMap = new Map<string, string>()
  const clonedGroups = groups.map((g) => {
    const key = newGroupKey()
    keyMap.set(g.key, key)
    return { ...g, id: undefined, key, vlan_ids: [...g.vlan_ids], open_ports: g.open_ports.map((p) => ({ ...p, id: undefined })) }
  })
  const clonedRows = rows.map((row) => ({ ...row, group_key: row.group_key ? (keyMap.get(row.group_key) ?? '') : '' }))
  return { groups: clonedGroups, rows: clonedRows }
}
