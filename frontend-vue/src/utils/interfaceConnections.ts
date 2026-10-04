// Подключения портов в форме устройства (блок «Порты / интерфейсы», InterfaceConnectionEditor.vue).
// Чистые функции без зависимостей от Vue и сторов: DeviceFormModal.vue передаёт сюда уже
// загруженные данные, а сервер (backend services/interface_connections.py) применяет результат в
// том же PUT /devices/{id}/interfaces, что и сами порты.
import type { Connection, DeviceInterface, InterfaceConnectionDraft, InterfaceDraftRow } from '../api/types'

type InterfaceLocation = Pick<DeviceInterface, 'id' | 'physical_device_id'>

/** Снимок подключений загруженных портов (ключ — id порта) на момент открытия формы: по нему при
 * сохранении отправляются только изменённые подключения, а нетронутые порты не затрагиваются. */
export type ConnectionBaseline = ReadonlyMap<string, InterfaceConnectionDraft | null>

export function emptyConnectionDraft(): InterfaceConnectionDraft {
  return { peer_device_id: '', peer_interface_id: '', connection_type_id: '', description: '' }
}

/**
 * Заполняет `connection` у строк по активным подключениям их портов. У порта без подключения и у
 * строки без id (ещё не сохранённый порт) — null. Если у порта несколько активных подключений
 * (исторические данные), берётся первое в порядке списка — как в utils/portConflicts.ts.
 *
 * @example
 * const rows = attachConnectionDrafts(ifaceRows, connectionsStore.all, catalogs.items['interfaces'])
 */
export function attachConnectionDrafts(rows: InterfaceDraftRow[], connections: readonly Connection[], interfaces: readonly InterfaceLocation[]): InterfaceDraftRow[] {
  const activeByInterface = new Map<string, Connection>()
  for (const c of connections) {
    if (!c.is_active) continue
    if (!activeByInterface.has(c.source_interface_id)) activeByInterface.set(c.source_interface_id, c)
    if (!activeByInterface.has(c.destination_interface_id)) activeByInterface.set(c.destination_interface_id, c)
  }
  const deviceByInterface = new Map(interfaces.map((i) => [i.id, i.physical_device_id]))
  return rows.map((row) => {
    const connection = row.id ? activeByInterface.get(row.id) : undefined
    if (!connection) return { ...row, connection: null }
    const peerId = connection.source_interface_id === row.id ? connection.destination_interface_id : connection.source_interface_id
    return {
      ...row,
      connection: { peer_device_id: deviceByInterface.get(peerId) ?? '', peer_interface_id: peerId, connection_type_id: connection.connection_type_id, description: connection.description ?? '' },
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
  return a.peer_interface_id === b.peer_interface_id && a.connection_type_id === b.connection_type_id && a.description.trim() === b.description.trim()
}

/**
 * Что отправить серверу в ключе `connection` порта: `undefined` — не отправлять (подключение не
 * менялось), `null` — отключить порт, объект — создать/обновить подключение.
 *
 * @example
 * connectionPayload({ id: 'if-1', connection: null, ... }, baseline) // null, если раньше было подключение
 */
export function connectionPayload(row: Pick<InterfaceDraftRow, 'id' | 'connection'>, baseline: ConnectionBaseline): { peer_interface_id: string; connection_type_id: string; description: string | null } | null | undefined {
  const current = row.connection ?? null
  const before = row.id ? (baseline.get(row.id) ?? null) : null
  if (sameConnection(current, before)) return undefined
  if (!current) return null
  return { peer_interface_id: current.peer_interface_id, connection_type_id: current.connection_type_id, description: current.description.trim() || null }
}

/** id уже сохранённых портов, подключение которых изменено в форме (создано, заменено или снято). */
export function changedConnectionRowIds(rows: readonly InterfaceDraftRow[], baseline: ConnectionBaseline): Set<string> {
  const ids = new Set<string>()
  for (const row of rows) {
    if (row.id && connectionPayload(row, baseline) !== undefined) ids.add(row.id)
  }
  return ids
}

/** Меняются ли подключения вообще: у любой строки, включая ещё не сохранённые порты. */
export function hasConnectionChanges(rows: readonly InterfaceDraftRow[], baseline: ConnectionBaseline): boolean {
  return rows.some((row) => connectionPayload(row, baseline) !== undefined)
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
  const seen = new Set<string>()
  for (const row of rows) {
    const draft = row.connection
    if (!draft) continue
    const label = row.name.trim() || 'без имени'
    if (connectionPayload(row, baseline) !== undefined) {
      if (!draft.peer_interface_id) return `Для порта «${label}» выберите устройство и порт, к которому он подключён, либо нажмите «Отключить».`
      if (!draft.connection_type_id) return `Для подключения порта «${label}» выберите тип физической линии связи.`
    }
    if (!draft.peer_interface_id) continue
    if (seen.has(draft.peer_interface_id)) return 'Один и тот же порт соседнего устройства выбран для нескольких портов — порт может участвовать только в одном подключении.'
    seen.add(draft.peer_interface_id)
  }
  return null
}

type PortConfigLike = Pick<DeviceInterface, 'is_management' | 'is_data_transfer' | 'vlan_mode'>

const yesNo = (v: boolean) => (v ? 'да' : 'нет')

/**
 * Чем конфигурация порта формы отличается от порта соседа: «Управление», «Передача данных» и режим
 * порта (VLAN порта в каталоге интерфейсов нет — их сверяет сервер на дашборде «Подключения»).
 * Пустой список — конфигурации совпадают.
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
  return diffs
}
