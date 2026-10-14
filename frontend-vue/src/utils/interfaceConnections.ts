// Подключения портов в форме устройства (блок «Порты / интерфейсы», InterfaceConnectionEditor.vue).
// Чистые функции без зависимостей от Vue и сторов: DeviceFormModal.vue передаёт сюда уже
// загруженные данные, а сервер (backend services/interface_connections.py) применяет результат в
// том же PUT /devices/{id}/interfaces, что и сами порты.
import type { DeviceInterfaceConnection } from '../api/deviceConnectivity'
import type { DeviceInterface, InterfaceConnectionDraft, InterfaceDraftRow } from '../api/types'
import { allVlansDiffer, carriesAllVlans } from './allVlans'

/** Снимок подключений загруженных портов (ключ — id порта) на момент открытия формы: по нему при
 * сохранении отправляются только изменённые подключения, а нетронутые порты не затрагиваются. */
export type ConnectionBaseline = ReadonlyMap<string, InterfaceConnectionDraft | null>

/** Значение «устройства-соседа» для самого редактируемого устройства, у которого ещё нет id (создание). */
export const SELF_DEVICE = '__self__'

export function emptyConnectionDraft(): InterfaceConnectionDraft {
  return { peer_device_id: '', peer_interface_id: '', connection_type_id: '', description: '' }
}

/** Другой порт редактируемого устройства, который можно выбрать соседом (InterfaceConnectionEditor.vue).
 * `value` — peerRef(): id сохранённого порта либо `row:<key>` для ещё не сохранённой строки формы. */
export interface SelfPortCandidate {
  value: string
  label: string
  interfaceId?: string
  rowKey?: string
  config: PortConfigLike
}

/** Новый ключ строки формы (InterfaceDraftRow.key). */
let rowKeyCounter = 0
export function newRowKey(): string {
  rowKeyCounter += 1
  return `row-${Date.now().toString(36)}-${rowKeyCounter}`
}

/** Ссылка на порт соседа в пределах формы: id сохранённого порта либо `row:<key>` для несохранённой строки. */
export function peerRef(draft: Pick<InterfaceConnectionDraft, 'peer_interface_id' | 'peer_row_key'>): string {
  return draft.peer_row_key ? `row:${draft.peer_row_key}` : draft.peer_interface_id
}

/** Ссылка на саму строку в том же виде, что и peerRef (пусто — на строку нельзя сослаться). */
export function rowRef(row: Pick<InterfaceDraftRow, 'id' | 'key'>): string {
  return row.id ?? (row.key ? `row:${row.key}` : '')
}

/** Указывает ли подключение на эту строку. */
export function connectionPointsTo(draft: InterfaceConnectionDraft | null | undefined, row: Pick<InterfaceDraftRow, 'id' | 'key'>): boolean {
  const ref = rowRef(row)
  return !!draft && !!ref && peerRef(draft) === ref
}

/**
 * Заполняет `connection` у строк по действующим подключениям их портов, которые отдаёт сервер
 * (api/deviceConnectivity.ts:fetchDeviceInterfaceConnections). У порта без подключения и у строки без id
 * (ещё не сохранённый порт) — null. Если у порта несколько действующих подключений (исторические данные),
 * берётся первое в порядке ответа — как в utils/portConflicts.ts.
 *
 * @example
 * const rows = attachConnectionDrafts(ifaceRows, await fetchDeviceInterfaceConnections(deviceId))
 */
export function attachConnectionDrafts(rows: InterfaceDraftRow[], connections: readonly DeviceInterfaceConnection[]): InterfaceDraftRow[] {
  const byInterface = new Map<string, DeviceInterfaceConnection>()
  for (const c of connections) {
    if (!byInterface.has(c.interface_id)) byInterface.set(c.interface_id, c)
  }
  return rows.map((row) => {
    const c = row.id ? byInterface.get(row.id) : undefined
    if (!c) return { ...row, connection: null }
    return {
      ...row,
      connection: { peer_device_id: c.peer_device_id, peer_device_name: c.peer_device_name, peer_interface_id: c.peer_interface_id, peer_interface_name: c.peer_interface_name, connection_type_id: c.connection_type_id, description: c.description ?? '' },
    }
  })
}

/** Снимок подключений строк, у которых уже есть id (см. ConnectionBaseline). */
export function snapshotConnections(rows: readonly InterfaceDraftRow[]): ConnectionBaseline {
  const snapshot = new Map<string, InterfaceConnectionDraft | null>()
  for (const row of rows) {
    if (row.id) snapshot.set(row.id, row.connection ? { ...row.connection } : null)
  }
  return snapshot
}

/** Совпадают ли подключения по тому, что хранится на сервере. peer_device_id — служебное поле
 * формы и не сравнивается; пробелы по краям описания значения не имеют. */
export function sameConnection(a: InterfaceConnectionDraft | null | undefined, b: InterfaceConnectionDraft | null | undefined): boolean {
  if (!a || !b) return !a && !b
  return peerRef(a) === peerRef(b) && a.connection_type_id === b.connection_type_id && a.description.trim() === b.description.trim()
}

/** Изменилось ли подключение строки по сравнению со снимком на момент открытия формы. */
export function isConnectionChanged(row: Pick<InterfaceDraftRow, 'id' | 'connection'>, baseline: ConnectionBaseline): boolean {
  return !sameConnection(row.connection ?? null, row.id ? (baseline.get(row.id) ?? null) : null)
}

/** Ключ `connection` элемента payload: сосед — либо `peer_interface_id`, либо `peer_row` (номер элемента массива interfaces). */
export type ConnectionPayload = { connection_type_id: string; description: string | null } & ({ peer_interface_id: string } | { peer_row: number })

/**
 * Что отправить серверу в ключе `connection` порта: `undefined` — не отправлять (подключение не
 * менялось), `null` — отключить порт, объект — создать/обновить подключение.
 *
 * `rows` — ВСЕ строки в порядке отправки: по ним ссылка на несохранённую строку (`peer_row_key`)
 * превращается в номер элемента массива interfaces. Если такой строки нет — это ошибка вызывающей
 * стороны (validateConnectionDrafts отсекает её раньше), поэтому бросаем исключение, а не шлём мусор.
 *
 * @example
 * connectionPayload({ id: 'if-1', connection: null, ... }, baseline) // null, если раньше было подключение
 */
export function connectionPayload(row: Pick<InterfaceDraftRow, 'id' | 'connection'>, baseline: ConnectionBaseline, rows: readonly Pick<InterfaceDraftRow, 'key'>[] = []): ConnectionPayload | null | undefined {
  if (!isConnectionChanged(row, baseline)) return undefined
  const current = row.connection
  if (!current) return null
  const common = { connection_type_id: current.connection_type_id, description: current.description.trim() || null }
  if (current.peer_row_key) {
    const index = rows.findIndex((r) => r.key === current.peer_row_key)
    if (index < 0) throw new Error('Порт-сосед подключения не найден среди портов формы')
    return { peer_row: index, ...common }
  }
  return { peer_interface_id: current.peer_interface_id, ...common }
}

/** id уже сохранённых портов, подключение которых изменено в форме (создано, заменено или снято). */
export function changedConnectionRowIds(rows: readonly InterfaceDraftRow[], baseline: ConnectionBaseline): Set<string> {
  const ids = new Set<string>()
  for (const row of rows) {
    if (row.id && isConnectionChanged(row, baseline)) ids.add(row.id)
  }
  return ids
}

/** Меняются ли подключения вообще: у любой строки, включая ещё не сохранённые порты. */
export function hasConnectionChanges(rows: readonly InterfaceDraftRow[], baseline: ConnectionBaseline): boolean {
  return rows.some((row) => isConnectionChanged(row, baseline))
}

/**
 * Ошибка заполнения подключений строк либо null. Незаконченный черновик («Подключить» нажато, но
 * сосед или тип линии не выбраны) не сохраняется молча без подключения — пользователь должен либо
 * дозаполнить его, либо нажать «Отключить»; один порт соседа нельзя выбрать для двух портов.
 *
 * Полнота проверяется только у подключений, изменённых в этой форме (см. connectionPayload): уже
 * сохранённое подключение уходит на сервер как есть и не должно мешать сохранить остальные правки
 * устройства. Повтор порта соседа ищется среди всех строк.
 */
export function validateConnectionDrafts(rows: readonly InterfaceDraftRow[], baseline: ConnectionBaseline): string | null {
  const byRef = new Map<string, InterfaceDraftRow>()
  for (const row of rows) {
    const ref = rowRef(row)
    if (ref) byRef.set(ref, row)
  }
  const seen = new Set<string>()
  for (const row of rows) {
    const draft = row.connection
    if (!draft) continue
    const label = row.name.trim() || 'без имени'
    const changed = isConnectionChanged(row, baseline)
    const ref = peerRef(draft)
    if (changed) {
      if (!ref) return `Для порта «${label}» выберите устройство и порт, к которому он подключён, либо нажмите «Отключить».`
      if (draft.peer_row_key && !byRef.has(ref)) return `Порт, выбранный соседом для порта «${label}», удалён из списка портов — выберите другой порт либо нажмите «Отключить».`
      if (!draft.connection_type_id) return `Для подключения порта «${label}» выберите тип физической линии связи.`
      if (connectionPointsTo(draft, row)) return `Порт «${label}» нельзя подключить к самому себе.`
      // Сосед из этой же формы не должен быть подключён в другое место: порт участвует только в одном подключении.
      const neighbour = byRef.get(ref)
      if (neighbour?.connection && !connectionPointsTo(neighbour.connection, row)) {
        return `Порт «${neighbour.name.trim() || 'без имени'}» выбран соседом для порта «${label}», но у него самого задано другое подключение — оставьте подключение только с одной стороны.`
      }
    }
    if (!ref) continue
    if (seen.has(ref)) return 'Один и тот же порт соседнего устройства выбран для нескольких портов — порт может участвовать только в одном подключении.'
    seen.add(ref)
  }
  return null
}

/** Конфигурация порта для сверки с соседом. `all_vlans` — «Все VLAN» (значим только в trunk; не задан — как «нет»). */
export type PortConfigLike = Pick<DeviceInterface, 'is_management' | 'is_data_transfer' | 'vlan_mode'> & { all_vlans?: boolean }

const yesNo = (v: boolean) => (v ? 'да' : 'нет')

/** Вид расхождения с соседом: flags — «Управление»/«Передача данных», vlan_mode — режим порта (Trunk/Access),
 * all_vlans — «Все VLAN» (оба порта в trunk, признак только у одного, см. utils/allVlans.ts). */
export type ConfigDiffKind = 'flags' | 'vlan_mode' | 'all_vlans'

/**
 * Какие виды расхождений есть между портом формы и портом соседа (пусто — конфигурации совпадают).
 * Те же сравнения, что у connectionConfigDiffs, но структурно — для кнопок «Применить…».
 *
 * @example
 * connectionConfigDiffKinds({ is_management: true, is_data_transfer: false, vlan_mode: 'access' },
 *   { is_management: true, is_data_transfer: false, vlan_mode: 'trunk' }) // ['vlan_mode']
 */
export function connectionConfigDiffKinds(own: PortConfigLike, peer: PortConfigLike): ConfigDiffKind[] {
  const kinds: ConfigDiffKind[] = []
  if (own.is_management !== peer.is_management || own.is_data_transfer !== peer.is_data_transfer) kinds.push('flags')
  if (own.vlan_mode !== peer.vlan_mode) kinds.push('vlan_mode')
  if (allVlansDiffer(own, peer)) kinds.push('all_vlans')
  return kinds
}

/** Сосед, выбранный в блоке «Подключение», как цель действий «Применить конфигурацию…» (родитель — редактор портов). */
export interface PeerConfigTarget {
  /** peerRef(): id сохранённого порта либо `row:<key>` для ещё не сохранённой строки формы. */
  ref: string
  /** Подпись для сообщений и окна подтверждения: «b1» (CAS-GB) либо «eth2 (строка 3)» (это устройство). */
  label: string
  /** Конфигурация соседа на данный момент: порт другого устройства — с сервера, порт этого устройства — из формы. */
  config: PortConfigLike
  /** Id сохранённого порта соседа (нет у ещё не сохранённой строки этого устройства). */
  interfaceId?: string
  /** Ключ строки формы — только для не сохранённого порта этого устройства. */
  rowKey?: string
  /** Сосед — другой порт редактируемого устройства (правится в черновике), а не порт чужого устройства (запрос сразу). */
  isSelf: boolean
}

/**
 * Чем конфигурация порта формы отличается от порта соседа: «Управление», «Передача данных», режим
 * порта и «Все VLAN» (когда оба порта в trunk). Наборы VLAN, выбранные вручную, здесь не сверяются —
 * их сверяет сервер на дашборде «Подключения». Пустой список — конфигурации совпадают.
 *
 * @example
 * connectionConfigDiffs({ is_management: true, is_data_transfer: false, vlan_mode: 'access' }, peer)
 * // ['«Управление»: да / у соседа нет']
 */
export function connectionConfigDiffs(own: PortConfigLike, peer: PortConfigLike): string[] {
  const diffs: string[] = []
  if (own.is_management !== peer.is_management) diffs.push(`«Управление»: ${yesNo(own.is_management)} / у соседа ${yesNo(peer.is_management)}`)
  if (own.is_data_transfer !== peer.is_data_transfer) diffs.push(`«Передача данных»: ${yesNo(own.is_data_transfer)} / у соседа ${yesNo(peer.is_data_transfer)}`)
  if (own.vlan_mode !== peer.vlan_mode) diffs.push(`режим порта: ${own.vlan_mode} / у соседа ${peer.vlan_mode}`)
  if (allVlansDiffer(own, peer)) diffs.push(`«Все VLAN»: ${yesNo(carriesAllVlans(own))} / у соседа ${yesNo(carriesAllVlans(peer))}`)
  return diffs
}
