// Соседи портов в блоке «Подключение» (components/InterfaceConnectionEditor.vue) формы устройства: какие порты уже заняты,
// какие можно выбрать соседом и какие порты других устройств форма освобождает. Чистые функции над строками формы.
import type { InterfaceDraftRow } from '../api/types'
import { connectionPointsTo, peerRef, rowRef, type ConnectionBaseline, type SelfPortCandidate } from './interfaceConnections'
import { portConfigOf } from './portConflicts'

/** Порты соседей, уже выбранные в ДРУГИХ строках, — чтобы один порт соседа нельзя было выбрать дважды. */
export function takenPeerIds(rows: readonly InterfaceDraftRow[], index: number): Set<string> {
  const ids = new Set<string>()
  rows.forEach((r, j) => {
    const ref = j !== index && r.connection ? peerRef(r.connection) : ''
    if (ref) ids.add(ref)
  })
  return ids
}

/** Другие порты ЭТОГО устройства, доступные строке `index` в роли соседа: не она сама, не выбранные соседом
 * другой строки и не имеющие собственного подключения (порт участвует только в одном подключении, а кабель
 * между двумя портами формы описывается с одной стороны). Уже выбранный этой строкой сосед остаётся в списке. */
export function selfPortCandidates(rows: readonly InterfaceDraftRow[], index: number): SelfPortCandidate[] {
  const me = rows[index]
  const taken = takenPeerIds(rows, index)
  return rows.flatMap((row, i): SelfPortCandidate[] => {
    const ref = rowRef(row)
    if (i === index || !ref) return []
    if (!connectionPointsTo(me.connection, row) && (taken.has(ref) || row.connection)) return []
    return [
      {
        value: ref,
        label: `${row.name.trim() || 'без имени'} (строка ${i + 1})`,
        interfaceId: row.id,
        rowKey: row.id ? undefined : row.key,
        config: portConfigOf(row),
      },
    ]
  })
}

/** Порты соседей, которые форма освобождает: подключение порта снято или переставлено на другой порт. */
export function freedPeerIds(rows: readonly InterfaceDraftRow[], baseline: ConnectionBaseline | undefined): Set<string> {
  const freed = new Set<string>()
  if (!baseline) return freed
  for (const row of rows) {
    const before = row.id ? baseline.get(row.id) : null
    if (before?.peer_interface_id && row.connection?.peer_interface_id !== before.peer_interface_id) freed.add(before.peer_interface_id)
  }
  return freed
}
