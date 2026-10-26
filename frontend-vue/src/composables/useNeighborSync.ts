// Согласование порта с соседним портом (редактор портов, DeviceInterfacesEditor.vue): окно решения расхождения по значку в
// таблице и действия блока «Подключение» («Применить конфигурацию соседа» / «Применить текущую конфигурацию»).
//
// Сосед может быть другим портом ЭТОГО устройства (правится черновик формы, сохранится вместе с ней) либо портом ДРУГОГО
// устройства — тогда это не черновик, а немедленный запрос:
//  * назначение порта (flags): точечный PUT generic-ресурса 'interfaces'; группы флажки не задают;
//  * режим порта (vlan_mode): каскад (composables/useVlanModeCascade.ts) — режим могут задавать группы, и у связанных портов
//    он тоже должен совпасть. Тривиальный случай (один порт, без групп и снимаемых VLAN) применяется сразу, остальное — через
//    окно подтверждения;
//  * «Все VLAN»: composables/useAllVlansSettle.ts — после смены режима, значение выбирает пользователь.
// После успешного ответа локальный кэш catalogs.items['interfaces'] правится на месте — иначе значок расхождения пропал бы
// только после полной перезагрузки каталогов.
import { nextTick, ref } from 'vue'
import { updateResource } from '../api/client'
import type { InterfaceDraftRow, InterfaceGroupDraft, PortConflictInfo, VLANDefinition } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import type { ManagedFields } from '../utils/interfaceGroups'
import { rowRef, type ConfigDiffKind, type PeerConfigTarget } from '../utils/interfaceConnections'
import type { ConflictKind } from '../utils/interfaceRowView'
import { applyCascadeToDraft, buildEditedState, isFormOnlyPlan } from '../utils/vlanModeCascade'
import { useAllVlansSettle } from './useAllVlansSettle'
import { useOverlayDismiss } from './useOverlayDismiss'
import { useToast } from './useToast'
import { useVlanModeCascade } from './useVlanModeCascade'

export interface NeighborSyncDeps {
  rows: () => InterfaceDraftRow[]
  groups: () => InterfaceGroupDraft[]
  deviceId: () => string | null
  /** Расхождения сохранённых портов с соседями (id порта → расхождение): считает родитель по данным подключений с сервера. */
  conflicts: () => Record<string, PortConflictInfo>
  vlanOptions: () => VLANDefinition[]
  knownVlans: () => readonly VLANDefinition[]
  setRows: (rows: InterfaceDraftRow[]) => void
  setGroups: (groups: InterfaceGroupDraft[]) => void
  updateRow: (index: number, patch: Partial<InterfaceDraftRow>) => void
  setVlanMode: (index: number, mode: 'access' | 'trunk') => void
  rowManaged: (row: InterfaceDraftRow) => ManagedFields
  groupLockNote: (row: InterfaceDraftRow, what: string) => string
  /** Конфигурация портов соседей изменена отсюда (запись на другие устройства выполнена): родитель должен перечитать их. */
  emitNeighborsChanged: () => void
  /** Каскад завершён (дошёл до порта соседа или группы): окно проверки перед сохранением обновляет данные соседей. */
  onCascadeFinished?: () => void
}

/** Нужна ли сверка «Все VLAN»: после смены режима и при явном расхождении признака. */
const needsAllVlansSettle = (kinds: readonly ConfigDiffKind[]) => kinds.includes('vlan_mode') || kinds.includes('all_vlans')

export function useNeighborSync(deps: NeighborSyncDeps) {
  const { notify, notifyError } = useToast()
  const catalogs = useCatalogsStore()

  // Одно окно на все виды расхождения: kind определяет, какие поля показать и применить, а механизм (два действия — «оставить
  // как у меня» / «взять как у соседа») общий.
  const activeConflict = ref<{ index: number; kind: ConflictKind } | null>(null)
  const applyingConflict = ref(false)
  // Счётчик изменений портов соседей, сделанных отсюда (конфигурация применена соседу или каскад режима дошёл до его порта):
  // блоки «Подключение» по нему перечитывают порты соседа с сервера и убирают уже устранённое расхождение.
  const peersVersion = ref(0)
  // Идёт применение конфигурации из блока «Подключение» (запрос соседу или предпросмотр каскада).
  const applyingPeerConfig = ref(false)

  function peersChanged() {
    peersVersion.value++
    deps.emitNeighborsChanged()
  }

  function rowConflict(row: InterfaceDraftRow): PortConflictInfo | undefined {
    return row.id ? deps.conflicts()[row.id] : undefined
  }

  function openConflict(index: number, kind: ConflictKind) {
    activeConflict.value = { index, kind }
  }
  function closeConflict() {
    activeConflict.value = null
  }
  const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(closeConflict)

  const { allVlansPrompt, answerAllVlansPrompt, ownSide, peerSide, conflictPeerSide, settleAllVlans } = useAllVlansSettle({
    rows: deps.rows,
    vlanOptions: deps.vlanOptions,
    knownVlans: deps.knownVlans,
    updateRow: deps.updateRow,
    rowManaged: deps.rowManaged,
    groupLockNote: deps.groupLockNote,
    onPeerPortWritten: peersChanged,
  })

  // Каскадная смена режима порта (composables/useVlanModeCascade.ts, backend services/vlan_mode_cascade.py): сервер считает
  // область изменения по СОСТОЯНИЮ ЭТОЙ ФОРМЫ (режим, группа, VLAN портов в черновике), порты и группы формы не пишет, а отдаёт
  // как deferred — applyDeferred вносит их в черновик, и они сохраняются вместе с формой. Остальные устройства пишутся сразу.
  const {
    pending: cascadePending,
    applying: cascadeApplying,
    preview: cascadePreview,
    review: cascadeReview,
    start: cascadeStart,
    confirm: cascadeConfirm,
    cancel: cascadeCancel,
  } = useVlanModeCascade({
    edited: () => buildEditedState(deps.deviceId(), deps.rows(), deps.groups()),
    applyDeferred(plan) {
      const draft = applyCascadeToDraft(deps.rows(), deps.groups(), plan)
      if (draft.changedPorts > 0) {
        deps.setRows(draft.rows)
        deps.setGroups(draft.groups)
      }
      return draft.changedPorts
    },
    onFinished: async () => {
      closeConflict()
      peersChanged()
      deps.onCascadeFinished?.()
      await runAfterCascade()
    },
  })

  // Что сделать, когда каскад режима завершится: сверить «Все VLAN» портов уже ПОСЛЕ смены режима (она меняет и признак: сервер
  // снимает его у порта, который уходит из trunk, а форма ставит у порта, который в trunk приходит). Каскад может ждать
  // подтверждения в окне последствий — тогда действие хранится здесь, пока пользователь не подтвердит или не откажется.
  let afterCascade: (() => Promise<void>) | null = null

  async function runAfterCascade() {
    const action = afterCascade
    afterCascade = null
    if (!action) return
    const wasApplying = applyingPeerConfig.value
    applyingPeerConfig.value = true
    try {
      await nextTick() // правка черновика из каскада доходит до props на следующем тике
      await action()
    } catch (err) {
      notifyError(err)
    } finally {
      applyingPeerConfig.value = wasApplying
    }
  }

  /** «Отмена» в окне последствий каскада: отложенная сверка «Все VLAN» не выполняется — режим не менялся. */
  function cancelCascadeReview() {
    afterCascade = null
    cascadeCancel()
  }

  // «Применить конфигурацию соседа [ко мне]» (окно расхождения):
  //  * назначение порта (flags) — меняет только ЭТУ строку черновика, сохраняется вместе с остальной формой;
  //  * режим порта (vlan_mode) — каскад от СВОЕГО порта с режимом соседа: если режим этого порта задан его группой, меняется
  //    вся группа (и связанные с ней порты, чтобы не осталось расхождений). Когда затрагивается только эта строка — правится
  //    черновик, иначе открывается окно последствий.
  async function applyNeighborConfig() {
    if (!activeConflict.value) return
    const { index, kind } = activeConflict.value
    const row = deps.rows()[index]
    const conflict = rowConflict(row)
    if (!conflict) return
    if (kind === 'flags') {
      deps.updateRow(index, { is_management: conflict.other.is_management, is_data_transfer: conflict.other.is_data_transfer })
      closeConflict()
      return
    }
    if (!row.id) return // расхождение бывает только у сохранённого порта
    applyingConflict.value = true
    try {
      // «Все VLAN»: порту — значение соседа (или другое по выбору пользователя), см. settleAllVlans.
      const settle = () => settleAllVlans(conflictPeerSide(conflict), ownSide(row))
      if (kind === 'all_vlans') {
        await settle()
        closeConflict()
        return
      }
      const current = await cascadePreview(row.id, conflict.other.vlan_mode, `«${row.name}» (это устройство)`)
      if (!current) return
      if (isFormOnlyPlan(current.plan)) {
        deps.setVlanMode(index, conflict.other.vlan_mode)
        closeConflict()
        await nextTick()
        await settle()
      } else {
        cascadeReview(current)
        afterCascade = settle
      }
    } catch (err) {
      notifyError(err)
    } finally {
      applyingConflict.value = false
    }
  }

  // Назначение порта соседа (другого устройства) — точечный PUT generic-ресурса 'interfaces'; группы флажки не задают.
  async function writeFlagsToNeighbor(interfaceId: string, from: Pick<InterfaceDraftRow, 'is_management' | 'is_data_transfer'>) {
    const payload = { is_management: from.is_management, is_data_transfer: from.is_data_transfer }
    await updateResource('interfaces', interfaceId, payload)
    const cached = ((catalogs.items['interfaces'] ?? []) as unknown as { id: string }[]).find((i) => i.id === interfaceId)
    if (cached) Object.assign(cached, payload)
  }

  // «Применить текущую конфигурацию [соседу]» (окно расхождения) — сам сосед принадлежит ДРУГОМУ устройству, не входящему в
  // modelValue этой формы, поэтому это не черновик, а немедленный запрос.
  async function applyCurrentConfigToNeighbor() {
    if (!activeConflict.value) return
    const { index, kind } = activeConflict.value
    const row = deps.rows()[index]
    const conflict = rowConflict(row)
    if (!conflict) return
    applyingConflict.value = true
    try {
      if (kind === 'all_vlans') {
        await settleAllVlans(ownSide(row), conflictPeerSide(conflict))
        closeConflict()
        return
      }
      if (kind === 'vlan_mode') {
        // Сверка «Все VLAN» — после смены режима соседа: каскад может ждать подтверждения, тогда она выполнится по его завершении.
        afterCascade = () => settleAllVlans(ownSide(row), conflictPeerSide(conflict, true))
        try {
          await cascadeStart(conflict.otherInterfaceId, row.vlan_mode, `«${conflict.otherInterfaceName}» (${conflict.otherDeviceName})`)
        } catch (err) {
          afterCascade = null
          throw err
        }
        return
      }
      await writeFlagsToNeighbor(conflict.otherInterfaceId, row)
      notify('Конфигурация применена к соседнему порту', 'success')
      closeConflict()
      peersChanged()
    } catch (err) {
      notifyError(err)
    } finally {
      applyingConflict.value = false
    }
  }

  // Режим порта строки формы → mode (общий шаг обоих действий из блока «Подключение»).
  //  * Сохранённый порт — каскад: режим может задавать группа, а у связанных портов он тоже должен совпасть. Затрагивается
  //    только эта строка — правится черновик, иначе окно последствий.
  //  * Ещё не сохранённый порт: серверу считать нечего — правим саму строку, но если режим задан её группой, менять его
  //    нельзя (группу правят в панели групп).
  // Возвращает: 'draft' — изменён черновик, 'pending' — ждёт подтверждения в окне, 'none' — менять нечего/нельзя.
  async function changeRowVlanMode(index: number, mode: 'access' | 'trunk'): Promise<'draft' | 'pending' | 'none'> {
    const row = deps.rows()[index]
    if (!row) return 'none'
    if (row.vlan_mode === mode) return 'none'
    if (!row.id) {
      if (deps.rowManaged(row).vlan) {
        notify(deps.groupLockNote(row, 'Режим порта'), 'warning')
        return 'none'
      }
      deps.setVlanMode(index, mode)
      return 'draft'
    }
    const current = await cascadePreview(row.id, mode, `«${row.name}» (это устройство)`)
    if (!current) return 'none'
    if (isFormOnlyPlan(current.plan)) {
      deps.setVlanMode(index, mode)
      return 'draft'
    }
    cascadeReview(current)
    return 'pending'
  }

  // Блок «Подключение» (InterfaceConnectionEditor): расхождение с выбранным соседом показывается сразу, ещё до сохранения
  // формы, и тут же его можно устранить — любым из двух способов. kinds — что именно расходится.
  //
  // «Применить конфигурацию соседа»: этому порту — назначение (Управление/Передача данных) и/или режим соседа. Назначение
  // правит только строку черновика (сохранится вместе с формой), режим — см. changeRowVlanMode.
  async function applyPeerConfigToPort(index: number, peer: PeerConfigTarget, kinds: ConfigDiffKind[]) {
    const row = deps.rows()[index]
    if (!row || applyingPeerConfig.value) return
    applyingPeerConfig.value = true
    try {
      let changedDraft = false
      let waitsForCascade = false
      const source = peerSide(peer)
      const settle = () => (source ? settleAllVlans(source, ownSide(row)) : Promise.resolve())
      if (kinds.includes('flags')) {
        deps.updateRow(index, { is_management: peer.config.is_management, is_data_transfer: peer.config.is_data_transfer })
        changedDraft = true
        // Следующий шаг читает строку из props: ждём, пока родитель применит правку, иначе она перетрётся.
        await nextTick()
      }
      if (kinds.includes('vlan_mode')) {
        const outcome = await changeRowVlanMode(index, peer.config.vlan_mode)
        if (outcome === 'draft') changedDraft = true
        if (outcome === 'pending') {
          waitsForCascade = true
          afterCascade = settle // сверка «Все VLAN» — когда пользователь подтвердит каскад
        }
      }
      if (changedDraft) notify(`Порту «${row.name.trim() || 'без имени'}» применена конфигурация соседа — сохраните форму`, 'success')
      if (!waitsForCascade && needsAllVlansSettle(kinds)) {
        await nextTick()
        await settle()
      }
    } catch (err) {
      notifyError(err)
    } finally {
      applyingPeerConfig.value = false
    }
  }

  // «Применить текущую конфигурацию»: соседу — назначение и/или режим порта этой строки.
  //  * Сосед — другой порт ЭТОГО устройства: правим его строку черновика (сохранится вместе с формой).
  //  * Сосед — порт ДРУГОГО устройства: это не черновик, а немедленный запрос (writeFlagsToNeighbor / cascadeStart).
  //    Подключение при этом пока не сохранено — сообщение честно говорит, что порт соседа уже изменён.
  async function applyPortConfigToPeer(index: number, peer: PeerConfigTarget, kinds: ConfigDiffKind[]) {
    const row = deps.rows()[index]
    if (!row || applyingPeerConfig.value) return
    applyingPeerConfig.value = true
    try {
      if (peer.isSelf) {
        const peerIndex = deps.rows().findIndex((r) => rowRef(r) === peer.ref)
        if (peerIndex === -1) {
          notify('Порт соседа уже убран из формы — выберите соседа заново', 'warning')
          return
        }
        let changedDraft = false
        let waitsForCascade = false
        const settle = () => settleAllVlans(ownSide(row), { kind: 'row', ref: peer.ref, label: peer.label })
        if (kinds.includes('flags')) {
          deps.updateRow(peerIndex, { is_management: row.is_management, is_data_transfer: row.is_data_transfer })
          changedDraft = true
          await nextTick()
        }
        if (kinds.includes('vlan_mode')) {
          const outcome = await changeRowVlanMode(peerIndex, row.vlan_mode)
          if (outcome === 'draft') changedDraft = true
          if (outcome === 'pending') {
            waitsForCascade = true
            afterCascade = settle
          }
        }
        if (changedDraft) notify(`Соседнему порту ${peer.label} применена текущая конфигурация — сохраните форму`, 'success')
        if (!waitsForCascade && needsAllVlansSettle(kinds)) {
          await nextTick()
          await settle()
        }
        return
      }
      if (!peer.interfaceId) return
      const interfaceId = peer.interfaceId
      const settleRemote = () => settleAllVlans(ownSide(row), { kind: 'port', interfaceId, label: peer.label })
      if (kinds.includes('flags')) {
        await writeFlagsToNeighbor(interfaceId, row)
        notify(`Назначение порта соседа ${peer.label} изменено сразу (это порт другого устройства)`, 'success')
      }
      if (kinds.includes('vlan_mode')) {
        // Каскад сам запускает сверку «Все VLAN» по завершении (в т.ч. после подтверждения в окне последствий).
        afterCascade = settleRemote
        try {
          await cascadeStart(interfaceId, row.vlan_mode, peer.label)
        } catch (err) {
          afterCascade = null
          throw err
        }
      } else if (needsAllVlansSettle(kinds)) {
        await settleRemote()
      }
      // Одно «Все VLAN»: порт соседа записывает и обновляет панель сам (resolveVlanSide) — второе уведомление ни к чему.
      if (kinds.some((kind) => kind !== 'all_vlans')) peersChanged()
    } catch (err) {
      notifyError(err)
    } finally {
      applyingPeerConfig.value = false
    }
  }

  return {
    activeConflict,
    applyingConflict,
    peersVersion,
    applyingPeerConfig,
    rowConflict,
    openConflict,
    closeConflict,
    onOverlayPointerDown,
    onOverlayClick,
    cascadePending,
    cascadeApplying,
    cascadeConfirm,
    cancelCascadeReview,
    allVlansPrompt,
    answerAllVlansPrompt,
    applyNeighborConfig,
    applyCurrentConfigToNeighbor,
    applyPeerConfigToPort,
    applyPortConfigToPeer,
  }
}
