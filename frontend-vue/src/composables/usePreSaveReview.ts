// Проверка расхождений с соседями ПЕРЕД сохранением формы устройства (DeviceInterfacesEditor.vue). DeviceFormModal при
// нажатии «Сохранить» вызывает reviewNeighborMismatches: расхождения, появляющиеся именно в этом сохранении
// (utils/neighborReview.ts), выносятся в диалог — по каждому те же два действия, что и в блоке «Подключение»
// (применить конфигурацию соседа / текущую), а внизу «Сохранить как есть» или «Вернуться к форме».
import { computed, ref } from 'vue'
import { fetchAllFreeInterfaces } from '../api/deviceConnectivity'
import type { InterfaceDraftRow } from '../api/types'
import type { ConfigDiffKind, ConnectionBaseline, PeerConfigTarget } from '../utils/interfaceConnections'
import { buildReviewItems, collectReviewEntries, type ReviewEntry, type ReviewItem, type ReviewPeers } from '../utils/neighborReview'
import type { PortConfig } from '../utils/portConflicts'
import { useToast } from './useToast'

export interface PreSaveReviewDeps {
  rows: () => InterfaceDraftRow[]
  deviceId: () => string | null
  /** Блок «Подключение» включён (форма устройства): без него подключений нет и проверять нечего. */
  editConnections: () => boolean
  connectionBaseline: () => ConnectionBaseline | undefined
  applyPeerConfigToPort: (index: number, peer: PeerConfigTarget, kinds: ConfigDiffKind[]) => Promise<void>
  applyPortConfigToPeer: (index: number, peer: PeerConfigTarget, kinds: ConfigDiffKind[]) => Promise<void>
}

export function usePreSaveReview(deps: PreSaveReviewDeps) {
  const { notifyError } = useToast()

  const reviewOpen = ref(false)
  const reviewEntries = ref<ReviewEntry[]>([])
  // Конфигурация портов соседей на ДРУГИХ устройствах (id порта → имя и конфигурация): с сервера, перечитывается после
  // каждого применённого действия. Соседи с этого же устройства берутся из строк формы — они всегда актуальны.
  const reviewPeers = ref<ReviewPeers>({})
  let reviewResolve: ((proceed: boolean) => void) | null = null

  async function loadReviewPeers(entries: readonly ReviewEntry[]): Promise<ReviewPeers> {
    const idsByDevice = new Map<string, Set<string>>()
    for (const { peer } of entries) {
      if (peer.isSelf || !peer.deviceId || !peer.interfaceId) continue
      const ids = idsByDevice.get(peer.deviceId) ?? new Set<string>()
      ids.add(peer.interfaceId)
      idsByDevice.set(peer.deviceId, ids)
    }
    const peers: ReviewPeers = {}
    await Promise.all(
      [...idsByDevice].map(async ([deviceId, ids]) => {
        // Порт соседа уже занят этим подключением — на сервере он отдаётся только по явному include.
        for (const port of await fetchAllFreeInterfaces(deviceId, [...ids])) {
          if (ids.has(port.id)) peers[port.id] = { name: port.name, config: { is_management: port.is_management, is_data_transfer: port.is_data_transfer, vlan_mode: port.vlan_mode, all_vlans: port.all_vlans } }
        }
      }),
    )
    return peers
  }

  // Расхождения, оставшиеся ПРЯМО СЕЙЧАС: устранённое действием из диалога пропадает из списка само.
  const reviewItems = computed<ReviewItem[]>(() => buildReviewItems(reviewEntries.value, deps.rows(), reviewPeers.value))

  async function refreshReviewPeers() {
    if (!reviewOpen.value) return
    try {
      reviewPeers.value = await loadReviewPeers(reviewEntries.value)
    } catch (err) {
      notifyError(err)
    }
  }

  function finishReview(proceed: boolean) {
    if (!reviewOpen.value) return
    reviewOpen.value = false
    reviewEntries.value = []
    reviewPeers.value = {}
    const resolve = reviewResolve
    reviewResolve = null
    resolve?.(proceed)
  }

  async function reviewApplyNeighbor(item: ReviewItem) {
    await deps.applyPeerConfigToPort(item.index, item.peer, item.kinds)
    await refreshReviewPeers()
  }
  async function reviewApplyCurrent(item: ReviewItem) {
    await deps.applyPortConfigToPeer(item.index, item.peer, item.kinds)
    await refreshReviewPeers()
  }

  /**
   * Вызывается формой перед записью. Если среди подключений есть расхождение назначения (Управление / Передача данных) или
   * режима порта с соседом, появившееся в этом сохранении, показывает диалог и ждёт решения.
   *
   * @param initial снимок конфигурации сохранённых портов на момент открытия формы (snapshotPortConfigs)
   * @returns true — сохранять (расхождений нет, устранены или пользователь выбрал «Сохранить как есть»);
   *          false — «Вернуться к форме». Не отклоняется: сбой чтения соседей не блокирует сохранение (проверка —
   *          подсказка, а не условие), но показывается уведомлением.
   */
  async function reviewNeighborMismatches(initial: ReadonlyMap<string, PortConfig> = new Map()): Promise<boolean> {
    if (!deps.editConnections() || reviewOpen.value) return true
    const entries = collectReviewEntries(deps.rows(), initial, deps.connectionBaseline(), deps.deviceId())
    if (!entries.length) return true
    try {
      reviewPeers.value = await loadReviewPeers(entries)
    } catch (err) {
      notifyError(err)
      return true
    }
    reviewEntries.value = entries
    if (!reviewItems.value.length) {
      reviewEntries.value = []
      return true
    }
    reviewOpen.value = true
    return new Promise<boolean>((resolve) => {
      reviewResolve = resolve
    })
  }

  return { reviewOpen, reviewItems, finishReview, reviewApplyNeighbor, reviewApplyCurrent, refreshReviewPeers, reviewNeighborMismatches }
}
