// Чистые функции над черновыми строками подинтерфейсов порта (SubinterfaceDraftRow): создание,
// подсказка имени, загрузка из ответа сервера, проверка перед отправкой и сборка payload. Вынесено из
// компонентов ради тестов без монтирования и чтобы форма (проверка при сохранении) и редактор
// (InterfaceSubinterfacesEditor.vue) использовали одни правила. Правила проверки зеркальны серверным
// (backend/app/services/crud/subinterfaces.py): имя и VLAN обязательны, имя уникально на устройстве и
// не совпадает с именем порта, на одном порту VLAN используется один раз; VLAN подинтерфейса — один из VLAN порта (клиентское правило).
import type {
  DeviceSubinterface,
  InterfaceDraftRow,
  InterfaceGroupSubinterface,
  ProtocolPortCatalogEntry,
  SubinterfaceDraftRow,
  VLANDefinition,
} from '../api/types'
import { isValidIPv4, isValidPrefixLength } from './ipValidation'
import { duplicatePortNumbers } from './openPorts'
import { vlanLabel } from './vlan'

let keyCounter = 0

/** Стабильный ключ строки в пределах формы (у новой строки нет id): нужен для v-for и не уходит на сервер. */
export function newSubinterfaceKey(): string {
  keyCounter += 1
  return `sub-${keyCounter}-${Math.random().toString(36).slice(2, 8)}`
}

/** Подсказка имени подинтерфейса — как у сетевого оборудования: «<порт>.<номер VLAN>», например `Gi0/0.10`.
 * Пустая строка, если у порта ещё нет имени (подсказывать нечего: «.10» — не имя). */
export function suggestSubinterfaceName(parentName: string, vlanNumber: number): string {
  const parent = parentName.trim()
  return parent ? `${parent}.${vlanNumber}` : ''
}

/** Имя подинтерфейса ещё «автоматическое» — пустое либо равное подсказке `<порт>.<VLAN>` для заданных порта и VLAN.
 * Только такие имена приложение вправе пересчитывать само (смена VLAN, переименование порта): введённое вручную
 * (`wan-uplink`, `mgmt`) не трогаем. */
export function isAutoSubinterfaceName(name: string, parentName: string, vlanNumber: number): boolean {
  return !name.trim() || name === suggestSubinterfaceName(parentName, vlanNumber)
}

/** Подинтерфейс после смены VLAN: новый VLAN и — только если имя «автоматическое» (пустое либо `<порт>.<прежний VLAN>`) —
 * пересчитанное имя `<порт>.<новый VLAN>`; имя, введённое вручную, не трогается. `previous` — прежний VLAN, если он известен
 * (у подинтерфейса на недоступном VLAN его берут из справочника): без него автоимя не распознать, остаётся только пустое.
 * Одно правило и для смены VLAN в строке подинтерфейса (InterfaceSubinterfacesEditor), и для массового переноса недоступных
 * (moveStaleSubinterfaces ниже). */
export function reassignSubinterfaceVlan(
  sub: SubinterfaceDraftRow,
  parentName: string,
  previous: VLANDefinition | undefined,
  next: VLANDefinition,
): SubinterfaceDraftRow {
  const wasAutoName = !sub.name.trim() || (previous != null && isAutoSubinterfaceName(sub.name, parentName, previous.vlan_id))
  return { ...sub, vlan_id: next.id, ...(wasAutoName ? { name: suggestSubinterfaceName(parentName, next.vlan_id) } : {}) }
}

export interface MoveStaleResult {
  /** Строки портов после переноса — ТОТ ЖЕ массив, если переносить было нечего. */
  rows: InterfaceDraftRow[]
  /** Перенесённые подинтерфейсы (их новые имена). */
  moved: string[]
  /** Не перенесённые: на порту целевой VLAN уже занят другим подинтерфейсом (на порту VLAN используется один раз) либо не выбран на порту. */
  skipped: string[]
}

/** Переносит подинтерфейсы на недоступных устройству VLAN (вне `allowedVlanIds`) на выбранный VLAN `target` — массово, одним
 * действием. Подинтерфейс переносится, только если на его порту `target` ещё не занят (в том числе только что перенесённым
 * подинтерфейсом): иначе сохранение упало бы на правиле «на порту VLAN один раз», такие подинтерфейсы остаются на месте и
 * возвращаются в `skipped`. Автоимя пересчитывается как при обычной смене VLAN (reassignSubinterfaceVlan), номер прежнего VLAN
 * берётся из `knownVlans`. Порты и подинтерфейсы, которых это не касается, не копируются.
 *
 * @example
 * moveStaleSubinterfaces(rows, vlan10, new Set(['v-10']), [vlan10, vlan30]) // Gi0/0.30 → Gi0/0.10 на VLAN 10 */
export function moveStaleSubinterfaces(
  rows: readonly InterfaceDraftRow[],
  target: VLANDefinition,
  allowedVlanIds: ReadonlySet<string>,
  knownVlans: readonly VLANDefinition[],
): MoveStaleResult {
  const knownById = new Map(knownVlans.map((v) => [v.id, v]))
  const moved: string[] = []
  const skipped: string[] = []
  const nextRows = rows.map((row) => {
    if (!staleSubinterfaces(row.subinterfaces, allowedVlanIds).length) return row
    const used = new Set((row.subinterfaces ?? []).map((sub) => sub.vlan_id))
    const portVlans = portVlanIdSet(row, allowedVlanIds)
    const subinterfaces = (row.subinterfaces ?? []).map((sub) => {
      if (!sub.vlan_id || allowedVlanIds.has(sub.vlan_id)) return sub
      const label = sub.name.trim() || 'без имени'
      // VLAN подинтерфейса — один из VLAN порта: на порт, где `target` не выбран, подинтерфейс не переносим (форма не сохранилась бы).
      if (used.has(target.id) || !portVlans.has(target.id)) {
        skipped.push(label)
        return sub
      }
      used.add(target.id)
      const result = reassignSubinterfaceVlan(sub, row.name, knownById.get(sub.vlan_id), target)
      moved.push(result.name.trim() || label)
      return result
    })
    return { ...row, subinterfaces }
  })
  return { rows: moved.length ? nextRows : (rows as InterfaceDraftRow[]), moved, skipped }
}

/** Текст и вид уведомления по итогу массового переноса: успех — «Перенесено …», если часть осталась на месте — предупреждение с
 * перечнем оставшихся и причиной. null — переносить было нечего (ни перенесённых, ни пропущенных). */
export function moveStaleMessage(
  result: Pick<MoveStaleResult, 'moved' | 'skipped'>,
  target: VLANDefinition,
): { text: string; type: 'success' | 'warning' } | null {
  const { moved, skipped } = result
  if (!moved.length && !skipped.length) return null
  const done = moved.length ? `Перенесено подинтерфейсов: ${moved.length} — на VLAN ${vlanLabel(target)}.` : ''
  if (!skipped.length) return { text: done, type: 'success' }
  const left = `Не перенесены (на их порту этот VLAN не выбран или уже занят другим подинтерфейсом): ${skipped.map((name) => `«${name}»`).join(', ')} — выберите для них другой VLAN.`
  return { text: [done, left].filter(Boolean).join(' '), type: 'warning' }
}

/** Подинтерфейсы порта после его переименования `oldPortName` → `newPortName`: автоимена («Gi0/0.10») пересчитываются
 * под новое имя порта («Gi0/1.10»), имена, введённые вручную, остаются как есть. Номер VLAN берётся из `vlans`
 * (допустимые устройству); подинтерфейс на недоступном VLAN не трогаем — его автоимя не восстановить.
 *
 * Если порт остался без имени, автоимя тоже пустеет (подсказывать нечего), а при следующем вводе имени порта
 * восстанавливается — цепочка «набираю имя порта по буквам» работает без потери автоимён. Возвращает ТОТ ЖЕ
 * массив, если менять нечего (без лишнего реактивного обновления).
 *
 * @example
 * renameSubinterfacesForPort(subs, 'Gi0/0', 'Gi0/1', vlans) // «Gi0/0.10» → «Gi0/1.10», «wan-uplink» без изменений */
export function renameSubinterfacesForPort(
  subs: readonly SubinterfaceDraftRow[],
  oldPortName: string,
  newPortName: string,
  vlans: readonly VLANDefinition[],
): SubinterfaceDraftRow[] {
  if (oldPortName.trim() === newPortName.trim()) return subs as SubinterfaceDraftRow[]
  const vlanById = new Map(vlans.map((v) => [v.id, v]))
  let changed = false
  const next = subs.map((sub) => {
    const vlan = vlanById.get(sub.vlan_id)
    if (!vlan || !isAutoSubinterfaceName(sub.name, oldPortName, vlan.vlan_id)) return sub
    const name = suggestSubinterfaceName(newPortName, vlan.vlan_id)
    if (name === sub.name) return sub
    changed = true
    return { ...sub, name }
  })
  return changed ? next : (subs as SubinterfaceDraftRow[])
}

/** Подинтерфейсы порта, VLAN которых не входит в `allowedVlanIds` (снят с устройства, убран из типа устройства,
 * перенесён в другой домен): сервер такое сохранение отклонит (422), поэтому форма показывает их заранее. */
export function staleSubinterfaces(subs: readonly SubinterfaceDraftRow[] | undefined, allowedVlanIds: ReadonlySet<string>): SubinterfaceDraftRow[] {
  return (subs ?? []).filter((sub) => sub.vlan_id && !allowedVlanIds.has(sub.vlan_id))
}

/** Id VLAN порта: с «Все VLAN» (trunk) — все VLAN, допустимые устройству (`allowedVlanIds`), иначе выбранные на порту.
 * Подинтерфейс порта создаётся только на одном из них. */
export function portVlanIdSet(row: Pick<InterfaceDraftRow, 'vlan_ids' | 'all_vlans' | 'vlan_mode'>, allowedVlanIds?: ReadonlySet<string>): Set<string> {
  return row.all_vlans === true && row.vlan_mode === 'trunk' && allowedVlanIds ? new Set(allowedVlanIds) : new Set(row.vlan_ids)
}

/** VLAN порта как список определений (по порядку `vlans`): из них выбирается VLAN подинтерфейса порта. */
export function portVlanOptions(row: Pick<InterfaceDraftRow, 'vlan_ids' | 'all_vlans' | 'vlan_mode'>, vlans: readonly VLANDefinition[]): VLANDefinition[] {
  const ids = portVlanIdSet(row, new Set(vlans.map((v) => v.id)))
  return vlans.filter((v) => ids.has(v.id))
}

/** Подинтерфейсы порта, VLAN которых выбрать уже нельзя: он не выбран на порту (убран с порта) либо — если известны VLAN
 * устройства (`allowedVlanIds`) — снят с устройства. Такой подинтерфейс не теряется молча: форма показывает предупреждение, а
 * сохранение требует перенести его на другой VLAN порта или удалить (validateSubinterfaceRows). */
export function subinterfacesOffPortVlans(
  row: Pick<InterfaceDraftRow, 'vlan_ids' | 'all_vlans' | 'vlan_mode' | 'subinterfaces'>,
  allowedVlanIds?: ReadonlySet<string>,
): SubinterfaceDraftRow[] {
  const portVlans = portVlanIdSet(row, allowedVlanIds)
  return (row.subinterfaces ?? []).filter((sub) => sub.vlan_id && (!portVlans.has(sub.vlan_id) || (allowedVlanIds != null && !allowedVlanIds.has(sub.vlan_id))))
}

/** Текст уведомления, когда VLAN сняли с устройства (или сменили тип устройства), а подинтерфейсы на нём остались.
 * В отличие от VLAN порта и групп подинтерфейс молча не удаляется — на нём IP-адреса и открытые порты, — поэтому
 * пользователя нужно предупредить сразу, а не на 422 при сохранении. Сравнивает прежний и новый списки опций
 * (как reconcileVlanIds): упоминаются только подинтерфейсы на VLAN, которые ТОЛЬКО ЧТО перестали быть доступны.
 * Возвращает null, если таких нет.
 *
 * @example
 * subinterfaceVlanRemovalMessage(rows, oldOptions, newOptions)
 * // 'Сняты VLAN (20 — Гости), но на них остались подинтерфейсы: «Gi0/0.20». Выберите другой VLAN или удалите их — иначе сохранить не получится.' */
export function subinterfaceVlanRemovalMessage(
  rows: readonly InterfaceDraftRow[],
  oldOptions: readonly VLANDefinition[],
  newOptions: readonly VLANDefinition[],
): string | null {
  const stillAllowed = new Set(newOptions.map((v) => v.id))
  const removed = oldOptions.filter((v) => !stillAllowed.has(v.id))
  if (!removed.length) return null
  const removedIds = new Set(removed.map((v) => v.id))

  const lostIds = new Set<string>()
  const names: string[] = []
  for (const row of rows) {
    for (const sub of row.subinterfaces ?? []) {
      if (!removedIds.has(sub.vlan_id)) continue
      lostIds.add(sub.vlan_id)
      names.push(`«${sub.name.trim() || 'без имени'}»`)
    }
  }
  if (!names.length) return null

  const labels = removed.filter((v) => lostIds.has(v.id)).map((v) => vlanLabel(v))
  return `Сняты VLAN (${labels.join(', ')}), но на них остались подинтерфейсы: ${names.join(', ')}. Выберите другой VLAN или удалите их — иначе сохранить не получится.`
}

/** Новая пустая строка подинтерфейса. Если VLAN известен — сразу подставляет его и подсказку имени. */
export function emptySubinterface(parentName: string, vlan?: VLANDefinition): SubinterfaceDraftRow {
  return {
    key: newSubinterfaceKey(),
    name: vlan ? suggestSubinterfaceName(parentName, vlan.vlan_id) : '',
    vlan_id: vlan?.id ?? '',
    is_management: false,
    is_data_transfer: false,
    description: '',
    ips: [],
    open_ports: [],
  }
}

/** Строка формы по подинтерфейсу из ответа сервера (GET /devices/{id}/subinterfaces, PUT .../interfaces). */
export function toSubinterfaceDraftRow(sub: DeviceSubinterface): SubinterfaceDraftRow {
  return {
    id: sub.id,
    key: sub.id,
    name: sub.name,
    vlan_id: sub.vlan_id,
    is_management: sub.is_management,
    is_data_transfer: sub.is_data_transfer,
    description: sub.description ?? '',
    ips: sub.ips.map((ip) => ({
      id: ip.id,
      ip_address: ip.ip_address,
      prefix_length: ip.prefix_length == null ? '' : String(ip.prefix_length),
      purpose: ip.purpose ?? '',
    })),
    open_ports: sub.open_ports.map((p) => ({
      id: p.id,
      protocol_catalog_id: p.protocol_catalog_id,
      transport_protocol: p.transport_protocol,
      description: p.description ?? '',
    })),
  }
}

/** Шаблон подинтерфейса группы портов из ответа сервера: у шаблона нет имени и порта-родителя (имя подинтерфейса порта
 * строится из имени порта и номера VLAN), остальное — как у обычной строки. */
export function toGroupSubinterfaceDraftRow(sub: InterfaceGroupSubinterface): SubinterfaceDraftRow {
  return toSubinterfaceDraftRow({ ...sub, parent_interface_id: '', name: '' })
}

/** Группирует подинтерфейсы устройства по порту-родителю (parent_interface_id), сохраняя порядок сервера. */
export function groupSubinterfacesByParent(items: readonly DeviceSubinterface[]): Map<string, SubinterfaceDraftRow[]> {
  const byParent = new Map<string, SubinterfaceDraftRow[]>()
  for (const item of items) {
    const rows = byParent.get(item.parent_interface_id) ?? []
    rows.push(toSubinterfaceDraftRow(item))
    byParent.set(item.parent_interface_id, rows)
  }
  return byParent
}

/** Копия подинтерфейсов без id (у самих строк, IP и открытых портов) — для копирования устройства: каждая строка
 * должна создаться заново под новым устройством, а не обновить запись донора. Ключи строк пересоздаются. */
export function stripSubinterfaceIds(rows: readonly SubinterfaceDraftRow[] | undefined): SubinterfaceDraftRow[] | undefined {
  if (!rows) return rows
  return rows.map((row) => ({
    ...row,
    id: undefined,
    key: newSubinterfaceKey(),
    ips: row.ips.map((ip) => ({ ...ip, id: undefined })),
    open_ports: row.open_ports.map((p) => ({ ...p, id: undefined })),
  }))
}

/** Текст первой найденной ошибки подинтерфейсов всех портов формы либо null. portCatalog нужен для проверки
 * повторов номеров открытых портов (без него — пропускается, остаётся серверная проверка). allowedVlanIds — VLAN,
 * доступные устройству (опции VLAN порта): подинтерфейс на другом VLAN блокирует сохранение с понятным текстом вместо
 * 422 с сервера. Без него проверка пропускается (форма без списка VLAN устройства, например DevicePortsModal). */
export function validateSubinterfaceRows(
  rows: readonly InterfaceDraftRow[],
  portCatalog: readonly ProtocolPortCatalogEntry[] = [],
  allowedVlanIds?: ReadonlySet<string>,
): string | null {
  const portNames = new Set(rows.map((row) => row.name.trim().toLowerCase()).filter(Boolean))
  const seenNames = new Set<string>()
  for (const row of rows) {
    const parent = row.name.trim() || 'без имени'
    const seenVlans = new Set<string>()
    for (const sub of row.subinterfaces ?? []) {
      const name = sub.name.trim()
      if (!name) return `У каждого подинтерфейса должно быть имя (порт «${parent}»).`
      if (name.length > 100) return `Имя подинтерфейса «${name.slice(0, 30)}…» не должно превышать 100 символов.`
      if (!sub.vlan_id) return `У подинтерфейса «${name}» не выбран VLAN.`
      if (allowedVlanIds && !allowedVlanIds.has(sub.vlan_id)) {
        return `VLAN подинтерфейса «${name}» не назначен устройству — выберите другой VLAN или удалите подинтерфейс.`
      }
      // VLAN подинтерфейса выбирается из VLAN, выбранных на порту: убрали его с порта — подинтерфейс нужно перенести или удалить.
      if (allowedVlanIds && !portVlanIdSet(row, allowedVlanIds).has(sub.vlan_id)) {
        return `VLAN подинтерфейса «${name}» не выбран на порту «${parent}» — выберите другой VLAN подинтерфейса или добавьте этот VLAN порту.`
      }
      const key = name.toLowerCase()
      if (seenNames.has(key)) return `Имя подинтерфейса «${name}» повторяется — имена подинтерфейсов на устройстве должны быть уникальны.`
      seenNames.add(key)
      if (portNames.has(key)) return `Имя подинтерфейса «${name}» совпадает с именем порта устройства.`
      if (seenVlans.has(sub.vlan_id)) return `На порту «${parent}» несколько подинтерфейсов на одном VLAN — на порту VLAN используется один раз.`
      seenVlans.add(sub.vlan_id)
      for (const ip of sub.ips) {
        if (!isValidIPv4(ip.ip_address)) return `Некорректный IP-адрес «${ip.ip_address}» у подинтерфейса «${name}».`
        if (!isValidPrefixLength(ip.prefix_length)) return `Некорректный префикс «${ip.prefix_length}» у подинтерфейса «${name}» — допустимо 0-32.`
      }
      const duplicates = duplicatePortNumbers(sub.open_ports, portCatalog)
      if (duplicates.length) return `У подинтерфейса «${name}» номера открытых портов повторяются: ${duplicates.join(', ')}.`
    }
  }
  return null
}

/** Элемент payload `subinterfaces` ГРУППЫ портов для PUT /devices/{id}/interfaces: то же, что у порта, но без имени —
 * сервер сам называет подинтерфейс каждого порта `<порт>.<номер VLAN>`. */
export function groupSubinterfacesPayload(rows: readonly SubinterfaceDraftRow[]) {
  return subinterfacesPayload(rows).map((sub) => ({
    id: sub.id,
    vlan_id: sub.vlan_id,
    is_management: sub.is_management,
    is_data_transfer: sub.is_data_transfer,
    description: sub.description,
    ips: sub.ips,
    open_ports: sub.open_ports,
  }))
}

/** Элемент payload `subinterfaces` порта для PUT /devices/{id}/interfaces. Строки без IP-адреса и открытые порты без
 * выбранной записи справочника (пустые плейсхолдеры формы) пропускаются — как у самого порта. */
export function subinterfacesPayload(rows: readonly SubinterfaceDraftRow[]) {
  return rows.map((sub) => ({
    id: sub.id,
    name: sub.name.trim(),
    vlan_id: sub.vlan_id || null,
    is_management: sub.is_management,
    is_data_transfer: sub.is_data_transfer,
    description: sub.description || null,
    ips: sub.ips
      .filter((ip) => ip.ip_address.trim())
      .map((ip) => ({
        id: ip.id,
        ip_address: ip.ip_address.trim(),
        prefix_length: ip.prefix_length === '' ? null : Number(ip.prefix_length),
        purpose: ip.purpose || null,
      })),
    open_ports: sub.open_ports
      .filter((p) => p.protocol_catalog_id)
      .map((p) => ({
        id: p.id,
        protocol_catalog_id: p.protocol_catalog_id,
        transport_protocol: p.transport_protocol || 'TCP',
        description: p.description || null,
      })),
  }))
}
