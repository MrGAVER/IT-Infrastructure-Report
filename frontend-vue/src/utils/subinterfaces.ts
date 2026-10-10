// Чистые функции над черновыми строками подинтерфейсов порта (SubinterfaceDraftRow): создание,
// подсказка имени, загрузка из ответа сервера, проверка перед отправкой и сборка payload. Вынесено из
// компонентов ради тестов без монтирования и чтобы форма (проверка при сохранении) и редактор
// (InterfaceSubinterfacesEditor.vue) использовали одни правила. Правила проверки зеркальны серверным
// (backend/app/services/crud/subinterfaces.py): имя и VLAN обязательны, имя уникально на устройстве и
// не совпадает с именем порта, на одном порту VLAN используется один раз.
import type { DeviceSubinterface, InterfaceDraftRow, ProtocolPortCatalogEntry, SubinterfaceDraftRow, VLANDefinition } from '../api/types'
import { isValidIPv4, isValidPrefixLength } from './ipValidation'
import { duplicatePortNumbers } from './openPorts'

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
    ips: sub.ips.map((ip) => ({ id: ip.id, ip_address: ip.ip_address, prefix_length: ip.prefix_length == null ? '' : String(ip.prefix_length), purpose: ip.purpose ?? '' })),
    open_ports: sub.open_ports.map((p) => ({ id: p.id, protocol_catalog_id: p.protocol_catalog_id, transport_protocol: p.transport_protocol, description: p.description ?? '' })),
  }
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
 * повторов номеров открытых портов (без него — пропускается, остаётся серверная проверка). */
export function validateSubinterfaceRows(rows: readonly InterfaceDraftRow[], portCatalog: readonly ProtocolPortCatalogEntry[] = []): string | null {
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
