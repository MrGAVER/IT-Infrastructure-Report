// «Все VLAN» при приведении порта к соседу (редактор портов, DeviceInterfacesEditor.vue).
//
// Признак «Все VLAN» (utils/allVlans.ts) — часть конфигурации порта, и «Применить конфигурацию соседа» / «Применить текущую
// конфигурацию» приводят к одному виду и его. Но «Все VLAN» устройства A и B — разные наборы номеров, а набор, выбранный
// вручную, у другого устройства может быть недоступен, поэтому значение пользователь выбирает сам: как у источника (признак
// либо набор, перенесённый по номерам VLAN) или другое (AllVlansChoiceModal).
//
// Сверка идёт ПОСЛЕ применения назначения и режима: смена режима сама меняет признак (из trunk в access он снимается, порт
// формы, переходящий в trunk, получает «Все VLAN» по умолчанию), и сравнивать нужно итоговое состояние. Значение нужно, только
// когда оба порта в trunk и признак есть у одного из них; если порт остался в access, признака у него нет. Порт формы правится
// в черновике (сохранится вместе с формой), порт другого устройства — сразу (PUT port-config).
import { ref } from 'vue'
import { setPortConfig, type PortConfigPatch } from '../api/portConfig'
import { loadPortVlanContext } from '../api/portVlans'
import type { InterfaceDraftRow, PortConflictInfo, VLANDefinition } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import { useVLANsStore } from '../stores/vlans'
import { carriesAllVlans, describeVlanValue, valueFromSource, type AllVlansState, type VlanValue } from '../utils/allVlans'
import type { ManagedFields } from '../utils/interfaceGroups'
import { rowRef, type PeerConfigTarget } from '../utils/interfaceConnections'
import { numbersOf } from '../utils/portEdit'
import { useToast } from './useToast'

/** Порт, участвующий в сверке «Все VLAN»: строка этой формы (ref — rowRef) либо порт другого устройства (interfaceId). */
export type VlanSideRef =
  | { kind: 'row'; ref: string; label: string }
  // known — состояние порта, которое уже известно и не менялось (порт-источник: сосед из блока «Подключение»): по нему сверка
  // обходится без запроса. У порта, который только что меняли (режим каскадом), known не задаётся — состояние читается с сервера.
  | { kind: 'port'; interfaceId: string; label: string; known?: AllVlansState }

interface VlanSide {
  label: string
  mode: 'access' | 'trunk'
  allVlans: boolean
  /** Номера выбранных VLAN (нужны, когда набор переносится на другое устройство). */
  numbers: number[]
  /** VLAN, допустимые устройству порта. */
  options: VLANDefinition[]
  /** Не пусто — набор порта задаёт группа и здесь не правится; текст — причина. */
  lockNote: string
  /** Порт этой формы: запись — правка черновика, а не запрос. */
  isDraft: boolean
  write: (value: VlanValue) => Promise<void>
}

/** Вопрос пользователю в окне AllVlansChoiceModal: какое значение «Все VLAN» установить порту. */
export interface AllVlansPrompt {
  portLabel: string
  sourceLabel: string
  description: string
  sourceValue: VlanValue
  missing: number[]
  options: VLANDefinition[]
  resolve: (value: VlanValue | null) => void
}

export interface AllVlansSettleDeps {
  rows: () => InterfaceDraftRow[]
  vlanOptions: () => VLANDefinition[]
  /** Все известные VLAN (справочник): по ним известны номера выбранных VLAN порта формы. */
  knownVlans: () => readonly VLANDefinition[]
  updateRow: (index: number, patch: Partial<InterfaceDraftRow>) => void
  rowManaged: (row: InterfaceDraftRow) => ManagedFields
  groupLockNote: (row: InterfaceDraftRow, what: string) => string
  /** Порт другого устройства записан отсюда: блоки «Подключение» и родитель должны перечитать соседей. */
  onPeerPortWritten: () => void
}

export function useAllVlansSettle(deps: AllVlansSettleDeps) {
  const { notify } = useToast()
  const catalogs = useCatalogsStore()
  const vlansStore = useVLANsStore()

  const allVlansPrompt = ref<AllVlansPrompt | null>(null)

  function askAllVlansValue(prompt: Omit<AllVlansPrompt, 'resolve'>): Promise<VlanValue | null> {
    return new Promise((resolve) => {
      allVlansPrompt.value = { ...prompt, resolve }
    })
  }
  function answerAllVlansPrompt(value: VlanValue | null) {
    const prompt = allVlansPrompt.value
    allVlansPrompt.value = null
    prompt?.resolve(value)
  }

  const findRow = (ref: string) => deps.rows().find((r) => rowRef(r) === ref)

  function ownSide(row: InterfaceDraftRow): VlanSideRef {
    return { kind: 'row', ref: rowRef(row), label: `«${row.name.trim() || 'без имени'}»` }
  }

  /** Сосед из выбранного в блоке «Подключение»: строка этой формы либо порт другого устройства. */
  function peerSide(peer: PeerConfigTarget): VlanSideRef | null {
    if (peer.isSelf) return { kind: 'row', ref: peer.ref, label: peer.label }
    return peer.interfaceId ? { kind: 'port', interfaceId: peer.interfaceId, label: peer.label, known: peer.config } : null
  }

  /** Сосед из расхождения по значку: порт этого же устройства (кабель между двумя его портами) — строка формы, иначе порт другого.
   * `fresh` — состояние порта уже могло измениться (ему меняли режим): не полагаться на данные расхождения, читать с сервера. */
  function conflictPeerSide(conflict: PortConflictInfo, fresh = false): VlanSideRef {
    const peerRow = deps.rows().find((r) => r.id === conflict.otherInterfaceId)
    if (peerRow) return { kind: 'row', ref: rowRef(peerRow), label: `«${conflict.otherInterfaceName}» (это устройство)` }
    const label = `«${conflict.otherInterfaceName}» (${conflict.otherDeviceName})`
    return { kind: 'port', interfaceId: conflict.otherInterfaceId, label, ...(fresh ? {} : { known: { vlan_mode: conflict.other.vlan_mode, all_vlans: conflict.other.all_vlans } }) }
  }

  /** Режим и «Все VLAN» порта без запроса к серверу — когда они известны сразу (строка формы, порт-источник с известным состоянием). */
  function knownVlanState(side: VlanSideRef): AllVlansState | null {
    if (side.kind === 'port') return side.known ?? null
    const row = findRow(side.ref)
    return row ? { vlan_mode: row.vlan_mode, all_vlans: carriesAllVlans(row) } : null
  }

  /** Значение VLAN порта в виде строки формы: «Все VLAN» зеркалит все VLAN устройства (так форма показывает их отмеченными). */
  function rowPatchForValue(value: VlanValue): Partial<InterfaceDraftRow> {
    return { all_vlans: value.allVlans, vlan_ids: value.allVlans ? deps.vlanOptions().map((v) => v.id) : [...value.vlanIds] }
  }

  async function resolveVlanSide(side: VlanSideRef): Promise<VlanSide | null> {
    if (side.kind === 'row') {
      const row = findRow(side.ref)
      if (!row) return null
      return {
        label: side.label,
        mode: row.vlan_mode,
        allVlans: carriesAllVlans(row),
        numbers: numbersOf(deps.knownVlans(), row.vlan_ids),
        options: deps.vlanOptions(),
        lockNote: deps.rowManaged(row).vlan ? deps.groupLockNote(row, 'Набор VLAN') : '',
        isDraft: true,
        write: async (value) => {
          const index = deps.rows().findIndex((r) => rowRef(r) === side.ref)
          if (index !== -1) deps.updateRow(index, rowPatchForValue(value))
        },
      }
    }
    await vlansStore.ensureLoaded()
    const ctx = await loadPortVlanContext(side.interfaceId, vlansStore.allDefinitions)
    return {
      label: side.label,
      mode: ctx.mode,
      allVlans: ctx.allVlans,
      numbers: numbersOf(vlansStore.allDefinitions, ctx.vlanIds),
      options: ctx.options,
      lockNote: '', // порт в группе, задающей VLAN, сервер не изменит и ответит понятной ошибкой
      isDraft: false,
      write: async (value) => {
        const patch: PortConfigPatch = value.allVlans ? { all_vlans: true, mode: 'trunk' } : { all_vlans: false, vlan_ids: value.vlanIds, mode: 'trunk' }
        catalogs.replaceInterface(await setPortConfig(side.interfaceId, patch))
        deps.onPeerPortWritten()
      },
    }
  }

  /**
   * Приводит «Все VLAN» порта `to` к порту `from` — но значение выбирает пользователь: по умолчанию как у `from`, либо другое.
   * Ничего не делает, если порты (уже) не расходятся по «Все VLAN»: хотя бы один не в trunk или признак у обоих одинаков.
   * Отказ в окне оставляет порт как есть (расхождение сохраняется и видно в блоке «Подключение»).
   */
  async function settleAllVlans(from: VlanSideRef, to: VlanSideRef) {
    // Обходимся без запросов, когда ответ ясен по уже известному: порт в access (признака нет) или признак у портов одинаков.
    const knownFrom = knownVlanState(from)
    const knownTo = knownVlanState(to)
    if (knownFrom?.vlan_mode === 'access' || knownTo?.vlan_mode === 'access') return
    if (knownFrom && knownTo && carriesAllVlans(knownFrom) === carriesAllVlans(knownTo)) return
    const [source, target] = await Promise.all([resolveVlanSide(from), resolveVlanSide(to)])
    if (!source || !target) return
    if (source.mode !== 'trunk' || target.mode !== 'trunk' || source.allVlans === target.allVlans) return
    if (target.lockNote) {
      notify(`${target.lockNote} «Все VLAN» порта ${target.label} не изменено.`, 'warning')
      return
    }
    const { value, missing } = valueFromSource(source, target.options)
    const yesNo = (v: boolean) => (v ? 'стоит' : 'не стоит')
    const chosen = await askAllVlansValue({
      portLabel: target.label,
      sourceLabel: `порта ${source.label}`,
      description: `«Все VLAN»: у порта ${source.label} ${yesNo(source.allVlans)}, у порта ${target.label} ${yesNo(target.allVlans)}.`,
      sourceValue: value,
      missing,
      options: target.options,
    })
    if (!chosen) {
      notify(`«Все VLAN» порта ${target.label} не изменено — расхождение осталось`, 'info')
      return
    }
    await target.write(chosen)
    notify(`Порту ${target.label} установлено: ${describeVlanValue(chosen, target.options)}${target.isDraft ? ' — сохраните форму' : ''}`, 'success')
  }

  return { allVlansPrompt, answerAllVlansPrompt, ownSide, peerSide, conflictPeerSide, settleAllVlans }
}
