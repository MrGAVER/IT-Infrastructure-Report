// Проверка расхождений с соседними портами ПЕРЕД сохранением формы устройства (composables/usePreSaveReview.ts).
//
// Предупреждение в блоке «Подключение» легко не заметить (строка порта свёрнута), а уведомление после записи ничего не
// предлагает и появляется, когда форма уже закрыта. Поэтому при нажатии «Сохранить» расхождения, которые появляются именно в
// этом сохранении, выносятся в диалог. «Появляется в этом сохранении» — как у уведомления после записи
// (utils/portConflicts.ts): порт новый, его подключение создано или заменено в форме, либо конфигурация порта отличается от
// снимка при открытии формы. Старое, никем не тронутое расхождение диалог не поднимает — иначе он выскакивал бы при каждом
// сохранении. Здесь — чистые функции над строками формы и данными соседей.
import type { InterfaceDraftRow } from '../api/types'
import {
  SELF_DEVICE,
  changedConnectionRowIds,
  connectionConfigDiffKinds,
  connectionConfigDiffs,
  peerRef,
  rowRef,
  type ConfigDiffKind,
  type ConnectionBaseline,
  type PeerConfigTarget,
  type PortConfigLike,
} from './interfaceConnections'
import { portConfigOf, samePortConfig, type PortConfig } from './portConflicts'

export interface ReviewPeerRef {
  ref: string
  isSelf: boolean
  deviceId?: string
  interfaceId?: string
  nameHint?: string
  deviceNameHint?: string
}

/** Порт формы с подключением, расхождение по которому проверяется (ссылка на строку — rowRef). */
export interface ReviewEntry {
  rowRef: string
  peer: ReviewPeerRef
}

/** Расхождение, оставшееся прямо сейчас: строка формы, её сосед и что именно отличается. */
export interface ReviewItem {
  key: string
  index: number
  row: InterfaceDraftRow
  peer: PeerConfigTarget
  kinds: ConfigDiffKind[]
  texts: string[]
}

/** Конфигурация портов соседей на ДРУГИХ устройствах: id порта → имя и конфигурация (с сервера). */
export type ReviewPeers = Record<string, { name: string; config: PortConfigLike }>

/**
 * Подключения, которые стоит проверить: у порта есть подключение с выбранным соседом, и оно появляется именно в этом
 * сохранении (порт новый, подключение создано/заменено в форме или конфигурация порта отличается от снимка `initial`).
 * Пара портов этого же устройства, соединённых друг с другом, — одно расхождение, а не два.
 */
export function collectReviewEntries(
  rows: readonly InterfaceDraftRow[],
  initial: ReadonlyMap<string, PortConfig>,
  baseline: ConnectionBaseline | undefined,
  deviceId: string | null,
): ReviewEntry[] {
  const changed = changedConnectionRowIds(rows, baseline ?? new Map())
  const self = deviceId ?? SELF_DEVICE
  const seenPairs = new Set<string>()
  const entries: ReviewEntry[] = []
  for (const row of rows) {
    const draft = row.connection
    const ref = rowRef(row)
    const peer = draft ? peerRef(draft) : ''
    if (!draft || !ref || !peer) continue
    const before = row.id ? initial.get(row.id) : undefined
    if (row.id && before && !changed.has(row.id) && samePortConfig(before, portConfigOf(row))) continue
    const isSelf = !!draft.peer_row_key || draft.peer_device_id === self
    if (isSelf) {
      const pair = [ref, peer].sort().join('|')
      if (seenPairs.has(pair)) continue
      seenPairs.add(pair)
    }
    entries.push({
      rowRef: ref,
      peer: {
        ref: peer,
        isSelf,
        deviceId: isSelf ? undefined : draft.peer_device_id,
        interfaceId: draft.peer_interface_id || undefined,
        nameHint: draft.peer_interface_name,
        deviceNameHint: draft.peer_device_name,
      },
    })
  }
  return entries
}

/** Сосед как цель применения конфигурации: строка этой формы (всегда актуальна) либо порт другого устройства из `peers`. */
export function reviewPeerTarget(peer: ReviewPeerRef, rows: readonly InterfaceDraftRow[], peers: ReviewPeers): PeerConfigTarget | null {
  if (peer.isSelf) {
    const index = rows.findIndex((r) => rowRef(r) === peer.ref)
    if (index === -1) return null
    const target = rows[index]
    return {
      ref: peer.ref,
      label: `«${target.name.trim() || 'без имени'}» (это устройство, строка ${index + 1})`,
      config: portConfigOf(target),
      interfaceId: target.id,
      rowKey: target.id ? undefined : target.key,
      isSelf: true,
    }
  }
  const info = peer.interfaceId ? peers[peer.interfaceId] : undefined
  if (!peer.interfaceId || !info) return null
  return { ref: peer.ref, label: `«${peer.nameHint ?? info.name}» (${peer.deviceNameHint ?? 'другое устройство'})`, config: info.config, interfaceId: peer.interfaceId, isSelf: false }
}

/** Расхождения, оставшиеся ПРЯМО СЕЙЧАС: считаются заново из строк формы и конфигурации соседей, поэтому устранённое
 * действием из диалога пропадает из списка само. */
export function buildReviewItems(entries: readonly ReviewEntry[], rows: readonly InterfaceDraftRow[], peers: ReviewPeers): ReviewItem[] {
  return entries.flatMap((entry) => {
    const index = rows.findIndex((r) => rowRef(r) === entry.rowRef)
    const peer = reviewPeerTarget(entry.peer, rows, peers)
    if (index === -1 || !peer) return []
    const row = rows[index]
    const own = portConfigOf(row)
    const kinds = connectionConfigDiffKinds(own, peer.config)
    return kinds.length ? [{ key: `${entry.rowRef}>${entry.peer.ref}`, index, row, peer, kinds, texts: connectionConfigDiffs(own, peer.config) }] : []
  })
}
