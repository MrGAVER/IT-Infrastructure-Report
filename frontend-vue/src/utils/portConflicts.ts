// Уведомление о сохранении порта, конфигурация которого расходится с подключённым соседним
// портом (пункт 5 правки формы физического устройства). Чистые функции без зависимостей от Vue —
// DeviceFormModal.vue лишь передаёт сюда уже вычисленные данные (interfaceConflicts и снимок
// конфигурации портов на момент загрузки формы), а показ toast остаётся за ним.
//
// «В первый раз для конкретной конфигурации порта» понимается как «эта конфигурация порта
// сохраняется впервые»: уведомляем, только когда (is_management, is_data_transfer, vlan_mode)
// порта в сохраняемой форме отличается от того, что было в БД при открытии формы. Если порт не
// менялся (расхождение уже существовало и пользователь о нём знает), повторное сохранение
// устройства уведомление не показывает — иначе оно повторялось бы при каждом сохранении.
import type { DeviceInterfaceConnection } from '../api/deviceConnectivity'
import type { InterfaceDraftRow, PortConflictInfo } from '../api/types'

export interface PortConfig {
  is_management: boolean
  is_data_transfer: boolean
  vlan_mode: 'access' | 'trunk'
}

/** То, что нужно от строки порта для сверки с соседом: подходит и черновая строка формы, и уже
 * сохранённый порт из ответа сервера (после сохранения у нового порта появляется id). */
export type PortRowLike = Pick<InterfaceDraftRow, 'id' | 'name' | 'is_management' | 'is_data_transfer' | 'vlan_mode'>

/**
 * Расхождения конфигурации портов формы с портами на другом конце АКТИВНЫХ подключений (ключ —
 * id порта, в результате только порты с расхождением). Общая логика DeviceFormModal.vue (подсветка
 * в редакторе портов и уведомление после сохранения) и DevicePortsModal.vue (уведомление).
 *
 * Сведения о соседе берутся из подключений ЭТОГО устройства, которые отдаёт сервер
 * (GET /devices/{id}/interface-connections, api/deviceConnectivity.ts): в каждой записи уже есть
 * имя и устройство соседнего порта, его роль и режим. Раньше сосед искался по общим спискам
 * подключений и интерфейсов, загружаемым целиком с потолком в 1000 записей, — в большом реестре
 * расхождение с портом, не попавшим в выборку, просто пропадало.
 *
 * Строки без id пропускаются: у ещё не сохранённого порта не может быть подключения. Если у порта
 * несколько подключений, берётся первое в порядке ответа сервера — как и раньше.
 *
 * @example
 * const connections = await fetchDeviceInterfaceConnections(deviceId)
 * const conflicts = computePortConflicts(rows, connections)
 */
export function computePortConflicts(
  rows: PortRowLike[],
  connections: readonly DeviceInterfaceConnection[],
): Record<string, PortConflictInfo> {
  const conflicts: Record<string, PortConflictInfo> = {}
  if (!connections.length || !rows.some((r) => r.id)) return conflicts
  const neighborOf = new Map<string, DeviceInterfaceConnection>()
  for (const c of connections) {
    if (!neighborOf.has(c.interface_id)) neighborOf.set(c.interface_id, c)
  }
  for (const row of rows) {
    if (!row.id) continue
    const neighbor = neighborOf.get(row.id)
    if (!neighbor) continue
    const flagsDiffer = neighbor.peer_is_management !== row.is_management || neighbor.peer_is_data_transfer !== row.is_data_transfer
    const vlanModeDiffer = neighbor.peer_vlan_mode !== row.vlan_mode
    if (!flagsDiffer && !vlanModeDiffer) continue
    conflicts[row.id] = {
      otherInterfaceId: neighbor.peer_interface_id,
      otherDeviceName: neighbor.peer_device_name,
      otherInterfaceName: neighbor.peer_interface_name,
      flagsDiffer,
      vlanModeDiffer,
      other: { is_management: neighbor.peer_is_management, is_data_transfer: neighbor.peer_is_data_transfer, vlan_mode: neighbor.peer_vlan_mode },
    }
  }
  return conflicts
}

/** Максимум портов, перечисляемых в тексте одного уведомления; остальные сворачиваются в «и ещё N». */
const MAX_LISTED_PORTS = 3

export function portConfigOf(row: Pick<InterfaceDraftRow, 'is_management' | 'is_data_transfer' | 'vlan_mode'>): PortConfig {
  return { is_management: row.is_management, is_data_transfer: row.is_data_transfer, vlan_mode: row.vlan_mode }
}

/** Снимок конфигурации уже сохранённых портов (только строки с id) — по нему потом определяется,
 * менялась ли конфигурация порта в форме. */
export function snapshotPortConfigs(rows: InterfaceDraftRow[]): Map<string, PortConfig> {
  const snapshot = new Map<string, PortConfig>()
  for (const row of rows) {
    if (row.id) snapshot.set(row.id, portConfigOf(row))
  }
  return snapshot
}

export function samePortConfig(a: PortConfig, b: PortConfig): boolean {
  return a.is_management === b.is_management && a.is_data_transfer === b.is_data_transfer && a.vlan_mode === b.vlan_mode
}

const yesNo = (v: boolean) => (v ? 'да' : 'нет')

function describeDifferences(row: PortRowLike, conflict: PortConflictInfo): string {
  const parts: string[] = []
  if (conflict.flagsDiffer) {
    if (row.is_management !== conflict.other.is_management) {
      parts.push(`«Управление»: ${yesNo(row.is_management)} / у соседа ${yesNo(conflict.other.is_management)}`)
    }
    if (row.is_data_transfer !== conflict.other.is_data_transfer) {
      parts.push(`«Передача данных»: ${yesNo(row.is_data_transfer)} / у соседа ${yesNo(conflict.other.is_data_transfer)}`)
    }
  }
  if (conflict.vlanModeDiffer) parts.push(`режим порта: ${row.vlan_mode} / у соседа ${conflict.other.vlan_mode}`)
  return parts.join('; ')
}

/**
 * Текст уведомления для портов, сохранённых с новой (не совпадающей с БД на момент открытия формы)
 * конфигурацией, расходящейся с соседним портом, либо null, если уведомлять не о чем.
 *
 * @param rows        строки портов из формы (то, что только что сохранено)
 * @param conflicts   interfaceConflicts из DeviceFormModal.vue — ключ id порта, только порты с расхождением
 * @param initial     снимок snapshotPortConfigs() на момент загрузки формы
 * @param alwaysInclude  id портов, чьё подключение создано или заменено в этой же форме: расхождение с НОВЫМ
 *                    соседом — новость, даже если конфигурация самого порта не менялась
 *
 * @example
 * buildPortConflictNotice(rows, conflicts, initial)
 * // 'Порты сохранены, но конфигурация расходится с соседними:\nпорт Gi0/1 ↔ Gi0/24 (SW-2) — режим порта: trunk / у соседа access'
 */
export function buildPortConflictNotice(
  rows: PortRowLike[],
  conflicts: Record<string, PortConflictInfo>,
  initial: Map<string, PortConfig>,
  alwaysInclude: ReadonlySet<string> = new Set(),
): string | null {
  const lines: string[] = []
  for (const row of rows) {
    if (!row.id) continue
    const conflict = conflicts[row.id]
    if (!conflict) continue
    const before = initial.get(row.id)
    if (before && samePortConfig(before, portConfigOf(row)) && !alwaysInclude.has(row.id)) continue
    lines.push(`порт ${row.name} ↔ ${conflict.otherInterfaceName} (${conflict.otherDeviceName}) — ${describeDifferences(row, conflict)}`)
  }
  if (!lines.length) return null
  const listed = lines.slice(0, MAX_LISTED_PORTS).join('\n')
  const rest = lines.length > MAX_LISTED_PORTS ? `\nи ещё ${lines.length - MAX_LISTED_PORTS}` : ''
  return `Порты сохранены, но конфигурация расходится с соседними:\n${listed}${rest}`
}
