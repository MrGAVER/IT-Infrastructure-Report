<script setup lang="ts">
// Редактор физических/логических интерфейсов устройства — карточки портов, генерация по
// шаблону имени, вложенные IP-адреса интерфейса и назначение VLAN на порту. Портирован с
// наибольшего оставшегося блока vanilla-фронтенда (до 2.60.0:
// renderInterfaceEditor + interfaceCardHtml + generateInterfaces), т.к. именно интерфейсы
// устройства нужны для организации подключений (Лист 3 отчёта) — без них новое устройство,
// заведённое через этот UI, нельзя было подключить ни к чему без /legacy.
//
// VLAN на порту: список допустимых VLAN приходит готовым в vlanOptions (вычисляется вызывающей
// стороной через api/portVlans.ts:computePortVlanOptions — DeviceFormModal.vue и
// DevicePortsModal.vue делают это по-разному, см. комментарии там) и выбирается в trunk-режиме
// во всплывающем окне с галочкой «Все VLAN» рядом с кнопкой его открытия (PortVlanPickerModal.vue),
// а в access — одиночным SearchableSelect (см. InterfaceDraftRow.vlan_mode, п.1.4.3.2);
// сам компонент ничего не запрашивает и не решает, какие VLAN разрешены.
//
// Массовое редактирование выбранных карточек ("Выбрать" на каждой + панель "Массовое
// редактирование" сверху) — портировано из bulkInterfaceEditHtml()/applyBulkInterfaceEdit() в
// vanilla-версии. selectedIndices — чисто UI-состояние этого компонента (не часть modelValue,
// как if-count/if-name-template генератора выше): индексы сбрасываются при любом структурном
// изменении списка (добавление/удаление/генерация), чтобы после сдвига индексов старый выбор не
// указывал на другую карточку.
//
// п.1.4: четыре независимых фикса блока "Порты / интерфейсы" по обратной связи пользователя —
// 1.4.1) generate() (кнопка "Сгенерировать") ЗАМЕНЯЕТ существующие строки по индексу — так было
//   и раньше, оставлено как есть для обратной совместимости с уже привычным поведением;
//   appendGenerated() (кнопка "Дополнить") — новая, ДОБАВЛЯЕТ новые строки, не трогая старые;
// 1.4.2) HelpTip рядом с "Шаблон имени" — пояснение по {n}/{n0} по клику, а не только в описании
//   README/памяти проекта;
// 1.4.3.1) addRow() больше не разворачивает новую строку автоматически — VLAN/IP свёрнуты по
//   умолчанию для любой строки, включая только что добавленную;
// 1.4.3.2) InterfaceDraftRow.vlan_mode — access (один VLAN, select) / trunk (чекбоксы, в т.ч.
//   "Все VLAN" одним кликом).
import { computed, nextTick, ref, watch } from 'vue'
import { updateResource } from '../api/client'
import { fetchAllFreeInterfaces } from '../api/deviceConnectivity'
import { setPortConfig, type PortConfigPatch } from '../api/portConfig'
import { loadPortVlanContext } from '../api/portVlans'
import { useCatalogsStore } from '../stores/catalogs'
import { useVLANsStore } from '../stores/vlans'
import { useFormPreferencesStore } from '../stores/formPreferences'
import type { CatalogItem, InterfaceDraftRow, InterfaceGroupDraft, InterfaceIpDraftRow, PortConflictInfo, ProtocolPortCatalogEntry, VLANDefinition } from '../api/types'
import { useToast } from '../composables/useToast'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { vTruncateTooltip } from '../directives/truncateTooltip'
import { vlanLabel } from '../utils/vlan'
import { applyBulkEditToRows } from '../utils/interfaceBulkEdit'
import { clearReferencesTo, emptyInterfaceRow, generateNewRows, portNamePatch, replaceWithGenerated, resolveStartNumber, TEMPLATE_HELP_TEXT, type GeneratorSettings } from '../utils/interfaceRowDraft'
import { conflictSummary, conflictTitle, connectionSummary, duplicatePortsText, staleSubinterfaceText, trunkVlanSummary, trunkVlanTitle, vlanCellSummary, type ConflictKind } from '../utils/interfaceRowView'
import { freedPeerIds as computeFreedPeerIds, selfPortCandidates, takenPeerIds } from '../utils/interfacePeers'
import { carriesAllVlans, describeVlanValue, valueFromSource, type AllVlansState, type VlanValue } from '../utils/allVlans'
import { numbersOf } from '../utils/portEdit'
import { findGroup, managedFields } from '../utils/interfaceGroups'
import { applyCascadeToDraft, buildEditedState, isFormOnlyPlan } from '../utils/vlanModeCascade'
import { useVlanModeCascade } from '../composables/useVlanModeCascade'
import { duplicatePortNumbers, sortOpenPortRows } from '../utils/openPorts'
import { moveRow, swapIndexes } from '../utils/interfaceOrder'
import { moveStaleMessage, moveStaleSubinterfaces, portVlanOptions, staleSubinterfaces } from '../utils/subinterfaces'
import {
  SELF_DEVICE,
  changedConnectionRowIds,
  connectionConfigDiffKinds,
  connectionConfigDiffs,
  newRowKey,
  peerRef,
  rowRef,
  type ConfigDiffKind,
  type ConnectionBaseline,
  type PeerConfigTarget,
  type PortConfigLike,
} from '../utils/interfaceConnections'
import { portConfigOf, samePortConfig, type PortConfig } from '../utils/portConflicts'
import QuickAddButton from './QuickAddButton.vue'
import HelpTip from './HelpTip.vue'
import OpenPortListEditor from './OpenPortListEditor.vue'
import InterfaceSubinterfacesEditor from './InterfaceSubinterfacesEditor.vue'
import InterfaceGroupsPanel from './InterfaceGroupsPanel.vue'
import InterfaceConnectionEditor from './InterfaceConnectionEditor.vue'
import AllVlansChoiceModal from './AllVlansChoiceModal.vue'
import PortVlanPickerModal from './PortVlanPickerModal.vue'
import SearchableSelect from './SearchableSelect.vue'
import VlanModeCascadeModal from './VlanModeCascadeModal.vue'

const props = withDefaults(
  defineProps<{
    modelValue: InterfaceDraftRow[]
    typeOptions: CatalogItem[]
    speedOptions: CatalogItem[]
    vlanOptions: VLANDefinition[]
    // Все известные VLAN (справочник), включая уже недоступные устройству: по ним известен номер VLAN у подинтерфейса
    // на снятом VLAN — подпись в его предупреждении и пересчёт автоимени при переименовании порта и при переносе.
    vlanCatalog?: VLANDefinition[]
    // п.1.4 (батч4): справочник "порт + протокол" для OpenPortListEditor.vue каждого интерфейса —
    // тот же catalogs.protocolPortCatalog, что раньше прокидывался напрямую в единственный
    // ("на всё устройство") экземпляр редактора в DeviceFormModal.vue.
    protocolPortCatalog?: ProtocolPortCatalogEntry[]
    // Пункты 1-2 правки "физическое устройство: расхождение с соседним портом" — считаются
    // родителем (DeviceFormModal.vue: interfaceConflicts), т.к. только у него есть данные о подключениях
    // устройства с сервера; этот компонент их только отображает и предлагает разрешить.
    conflicts?: Record<string, PortConflictInfo>
    // Группы портов устройства (v-model:groups): параметры группы записываются в её порты, а у
    // членов группы управляемые ею поля недоступны для правки в самой строке (см. rowManaged()).
    groups?: InterfaceGroupDraft[]
    // Устройство, чьи порты редактируются в этой форме. Нужно каскадной смене режима порта соседа
    // («Применить текущую конфигурацию»): порты и группы этого устройства сервер не пишет, а отдаёт
    // в плане как изменения черновика формы (см. utils/vlanModeCascade.ts).
    deviceId?: string | null
    // Подпись редактируемого устройства (имя или серийный номер из формы) — для пункта «это устройство» в списке
    // соседей блока «Подключение».
    deviceLabel?: string
    // Показывать блок «Подключение» в раскрытой строке порта. Включает только вызывающая сторона,
    // которая сохраняет подключения вместе с портами (форма устройства): окно «Управлять портами»
    // (DevicePortsModal.vue) их не сохраняет, и кнопка «Подключить» там ничего бы не делала.
    editConnections?: boolean
    // Подключения портов на момент открытия формы (только вместе с editConnections): по ним видно, какие
    // порты других устройств этой же формой освобождаются, — их можно выбрать соседом другой строки
    // (обмен соседями между портами без промежуточного сохранения).
    connectionBaseline?: ConnectionBaseline
  }>(),
  { conflicts: () => ({}), protocolPortCatalog: () => [], groups: () => [], deviceId: null, editConnections: false, connectionBaseline: undefined },
)
const emit = defineEmits<{
  'update:modelValue': [rows: InterfaceDraftRow[]]
  'update:groups': [groups: InterfaceGroupDraft[]]
  /** Конфигурация портов-соседей изменена отсюда (запись на другие устройства уже выполнена): родитель, который
   * считает расхождения по данным соседей, должен перечитать их. */
  'neighbors-changed': []
}>()
const { notify, notifyError } = useToast()
const catalogs = useCatalogsStore()
const vlansStore = useVLANsStore()
// Общий порог сворачивания длинных списков (из «Настроек») — передаётся вложенным редакторам открытых портов.
const formPreferences = useFormPreferencesStore()

// Поля генератора — черновой ввод формы, не часть modelValue (как if-count/if-name-template в
// vanilla). Начальное количество подставляется от уже загруженных интерфейсов один раз при
// монтировании — компонент монтируется уже после загрузки данных (см. DeviceFormModal.vue:
// loadingNested), так что на момент монтирования modelValue уже в актуальном состоянии.
const genCount = ref(String(props.modelValue.length))
const genNameTemplate = ref('eth{n}')
const genTypeId = ref('')
const genSpeedId = ref('')
// Фикс п.1.3.3: "нужно больше вариаций шаблонов — например, нумерация с определённого до
// определённого номера". Раньше {n} всегда отсчитывался от 1 (режим "Заменить все порты") или от
// количества уже существующих интерфейсов (режим "Дополнить", см. applyGenerator()) — не было
// способа явно продолжить нумерацию портов с произвольного номера, например сгенерировать порты
// 5-24, когда 1-4 уже заняты чем-то другим и не участвуют в этом списке вовсе. Пустая строка —
// прежнее поведение без изменений (авто: 1 или продолжение от количества строк).
const genStartAt = ref('')
// Фикс п.1.3.4: были две отдельные кнопки — "Сгенерировать" (заменяет) и "Дополнить" (добавляет),
// путавшие своими названиями, какая из них разрушительна. Теперь одна кнопка + галочка,
// отключенная по умолчанию — безопасный режим (append) остаётся действием по умолчанию, а
// разрушительный (replace) требует явного осознанного действия (поставить галочку) и всегда
// показывает предупреждение, если есть что терять (см. generate() ниже).
const replaceAllPorts = ref(false)

// Группа порта и то, чем она управляет. Управляемые поля в строке заблокированы: чтобы задать
// порту своё значение, его сначала выводят из группы (значения при этом остаются в порте).
function rowGroup(row: InterfaceDraftRow): InterfaceGroupDraft | undefined {
  return findGroup(row, props.groups)
}
function rowManaged(row: InterfaceDraftRow) {
  return managedFields(rowGroup(row))
}
function groupLockNote(row: InterfaceDraftRow, what: string): string {
  return `${what} задан группой «${rowGroup(row)?.name ?? ''}» — измените в группе или выведите порт из группы.`
}

// Панель групп отдаёт согласованное изменение порт+группа одним событием.
function onGroupsChange(payload: { rows: InterfaceDraftRow[]; groups: InterfaceGroupDraft[] }) {
  emit('update:modelValue', payload.rows)
  emit('update:groups', payload.groups)
  selectedIndices.value = new Set()
}

// Пустая строка нового порта (utils/interfaceRowDraft.ts). Ключ нужен, чтобы подключение другого порта могло
// сослаться на строку, у которой ещё нет id.
const emptyRow = () => emptyInterfaceRow(props.editConnections)

// Повторяющиеся номера открытых портов по строкам (индекс → номера). Показываются индикатором на
// свёрнутой строке — иначе подсвеченную внутри раскрытого блока строку увидит только тот, кто его
// раскроет; сохранение с повтором всё равно блокируется (validateInterfaceDraftRows).
const duplicatePortsByRow = computed(() => props.modelValue.map((row) => duplicatePortNumbers(row.open_ports, props.protocolPortCatalog)))

// Подинтерфейсы на VLAN, которого у устройства больше нет (снят в блоке «VLAN устройства», сменили тип устройства,
// VLAN перенесён в другой домен). Подинтерфейс молча не удаляется — на нём IP-адреса и открытые порты, — а сохранение
// с таким VLAN сервер отклонит (422), поэтому, как и повторы открытых портов, показываем индикатор на свёрнутой строке.
const allowedVlanIds = computed(() => new Set(props.vlanOptions.map((v) => v.id)))
// Справочник VLAN с допустимыми устройству: по нему известны номера и тех VLAN, что устройству уже не разрешены.
const knownVlans = computed(() => {
  const byId = new Map([...(props.vlanCatalog ?? []), ...props.vlanOptions].map((v) => [v.id, v]))
  return [...byId.values()]
})

const staleSubinterfaceCount = computed(() => props.modelValue.reduce((sum, row) => sum + staleSubinterfaces(row.subinterfaces, allowedVlanIds.value).length, 0))
const sortedVlanOptions = computed(() => [...props.vlanOptions].sort((a, b) => a.vlan_id - b.vlan_id))
const bulkMoveTargetId = ref('')

// Массовый перенос: все подинтерфейсы на недоступных VLAN — на один выбранный VLAN устройства одним действием (вместо правки
// каждого). Там, где на порту этот VLAN уже занят, подинтерфейс остаётся на месте — о таких говорит предупреждение.
function moveAllStaleSubinterfaces() {
  const target = props.vlanOptions.find((v) => v.id === bulkMoveTargetId.value)
  if (!target) return
  const result = moveStaleSubinterfaces(props.modelValue, target, allowedVlanIds.value, knownVlans.value)
  bulkMoveTargetId.value = ''
  if (result.moved.length) emit('update:modelValue', result.rows)
  const message = moveStaleMessage(result, target)
  if (message) notify(message.text, message.type)
}

// VLAN, из которых выбирается VLAN подинтерфейса порта: выбранные на самом порту (с «Все VLAN» — все VLAN устройства).
function subinterfaceVlanOptions(row: InterfaceDraftRow) {
  return portVlanOptions(row, props.vlanOptions)
}

// Строка без id может стать соседом подключения другого порта этой же формы, а ссылаться на неё нужно по
// стабильному ключу (индекс меняется при добавлении и удалении строк). Строки, созданные не в этом
// редакторе (копия устройства), получают ключ сразу при показе.
watch(
  () => props.modelValue,
  (rows) => {
    if (!props.editConnections || rows.every((r) => r.id || r.key)) return
    emit('update:modelValue', rows.map((r) => (r.id || r.key ? r : { ...r, key: newRowKey() })))
  },
  { immediate: true },
)

// Порты соседей, которые эта форма освобождает: подключение порта снято или переставлено на другой порт.
const freedPeerIds = computed(() => computeFreedPeerIds(props.modelValue, props.connectionBaseline))

function rowConflict(row: InterfaceDraftRow): PortConflictInfo | undefined {
  return row.id ? props.conflicts[row.id] : undefined
}

// Пункты 1-2 правки "физическое устройство: расхождение с соседним портом": одно окно на оба
// вида расхождения — kind определяет, какие именно поля показать/применить, но сам механизм
// (два действия — "оставить как у меня" / "взять как у соседа") общий.
const activeConflict = ref<{ index: number; kind: ConflictKind } | null>(null)
const applyingConflict = ref(false)
// Счётчик изменений портов соседей, сделанных отсюда (конфигурация применена соседу или каскад режима дошёл до его
// порта): блоки «Подключение» по нему перечитывают порты соседа с сервера и убирают уже устранённое расхождение.
const peersVersion = ref(0)
// Идёт применение конфигурации из блока «Подключение» (запрос соседу или предпросмотр каскада).
const applyingPeerConfig = ref(false)

function openConflict(index: number, kind: ConflictKind) {
  activeConflict.value = { index, kind }
}
function closeConflict() {
  activeConflict.value = null
}
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(closeConflict)

// Каскадная смена режима порта (composables/useVlanModeCascade.ts, backend services/vlan_mode_cascade.py):
// режим могут задавать группы, и у связанных портов он тоже должен совпасть, иначе расхождения просто
// переедут дальше. Сервер считает область изменения по СОСТОЯНИЮ ЭТОЙ ФОРМЫ (режим, группа, VLAN портов
// в черновике), порты и группы формы не пишет, а отдаёт как deferred — applyDeferred вносит их в черновик,
// и они сохраняются вместе с формой. Остальные устройства записываются сразу.
const {
  pending: cascadePending,
  applying: cascadeApplying,
  preview: cascadePreview,
  review: cascadeReview,
  start: cascadeStart,
  confirm: cascadeConfirm,
  cancel: cascadeCancel,
} = useVlanModeCascade({
  edited: () => buildEditedState(props.deviceId, props.modelValue, props.groups),
  applyDeferred(plan) {
    const draft = applyCascadeToDraft(props.modelValue, props.groups, plan)
    if (draft.changedPorts > 0) {
      emit('update:modelValue', draft.rows)
      emit('update:groups', draft.groups)
    }
    return draft.changedPorts
  },
  onFinished: async () => {
    closeConflict()
    peersVersion.value++
    emit('neighbors-changed')
    void refreshReviewPeers() // каскад дошёл до порта соседа или группы — окно проверки перед сохранением обновляется
    await runAfterCascade()
  },
})

// Что сделать, когда каскад режима завершится: сверить «Все VLAN» портов уже ПОСЛЕ смены режима (она меняет и признак:
// сервер снимает его у порта, который уходит из trunk, а форма ставит у порта, который в trunk приходит). Каскад может
// ждать подтверждения в окне последствий — тогда действие хранится здесь, пока пользователь не подтвердит или не откажется.
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

// "Применить конфигурацию соседа [ко мне]":
//  * Назначение порта (flags) — меняет только ЭТУ строку черновика, сохраняется вместе с остальной формой.
//  * Режим порта (vlan_mode) — каскад от СВОЕГО порта с режимом соседа: если режим этого порта задан его
//    группой, меняется вся группа (и связанные с ней порты, чтобы не осталось расхождений). Когда
//    затрагивается только эта строка — правится черновик, как раньше; иначе открывается окно последствий.
async function applyNeighborConfig() {
  if (!activeConflict.value) return
  const { index, kind } = activeConflict.value
  const row = props.modelValue[index]
  const conflict = rowConflict(row)
  if (!conflict) return
  if (kind === 'flags') {
    updateRow(index, { is_management: conflict.other.is_management, is_data_transfer: conflict.other.is_data_transfer })
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
      setVlanMode(index, conflict.other.vlan_mode)
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

// Назначение порта соседа (другого устройства) — точечный PUT generic-ресурса 'interfaces'; группы флажки не
// задают. Локальный кэш catalogs.items['interfaces'] правим на месте: без этого значок расхождения пропал бы
// только после полной перезагрузки каталогов.
async function writeFlagsToNeighbor(interfaceId: string, from: Pick<InterfaceDraftRow, 'is_management' | 'is_data_transfer'>) {
  const payload = { is_management: from.is_management, is_data_transfer: from.is_data_transfer }
  await updateResource('interfaces', interfaceId, payload)
  const cached = ((catalogs.items['interfaces'] ?? []) as unknown as { id: string }[]).find((i) => i.id === interfaceId)
  if (cached) Object.assign(cached, payload)
}

// "Применить текущую конфигурацию [соседу]" — сам сосед принадлежит ДРУГОМУ устройству, не
// входящему в modelValue этой формы, поэтому это не черновик, а немедленный запрос.
//  * Назначение порта (flags): точечный PUT generic-ресурса 'interfaces'; группы флажки не задают.
//  * Режим порта (vlan_mode): каскад от порта соседа с режимом этой строки. Тривиальный случай (один
//    порт, без групп и снимаемых VLAN) применяется сразу, остальное — через окно подтверждения.
// После успешного ответа правим локальный кэш catalogs.items['interfaces'] на месте — иначе значок
// расхождения пропал бы только после полной перезагрузки каталогов, а не сразу.
async function applyCurrentConfigToNeighbor() {
  if (!activeConflict.value) return
  const { index, kind } = activeConflict.value
  const row = props.modelValue[index]
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
    peersVersion.value++
    emit('neighbors-changed')
  } catch (err) {
    notifyError(err)
  } finally {
    applyingConflict.value = false
  }
}

// Режим порта строки формы → mode (общий шаг обоих действий из блока «Подключение»).
//  * Сохранённый порт — каскад (composables/useVlanModeCascade.ts): режим может задавать группа, а у связанных
//    портов он тоже должен совпасть. Затрагивается только эта строка — правится черновик, иначе окно последствий.
//  * Ещё не сохранённый порт: серверу считать нечего — правим саму строку, но если режим задан её группой,
//    менять его нельзя (группу правят в панели групп).
// Возвращает: 'draft' — изменён черновик, 'pending' — ждёт подтверждения в окне, 'none' — менять нечего/нельзя.
async function changeRowVlanMode(index: number, mode: 'access' | 'trunk'): Promise<'draft' | 'pending' | 'none'> {
  const row = props.modelValue[index]
  if (!row) return 'none'
  if (row.vlan_mode === mode) return 'none'
  if (!row.id) {
    if (rowManaged(row).vlan) {
      notify(groupLockNote(row, 'Режим порта'), 'warning')
      return 'none'
    }
    setVlanMode(index, mode)
    return 'draft'
  }
  const current = await cascadePreview(row.id, mode, `«${row.name}» (это устройство)`)
  if (!current) return 'none'
  if (isFormOnlyPlan(current.plan)) {
    setVlanMode(index, mode)
    return 'draft'
  }
  cascadeReview(current)
  return 'pending'
}

// ===== «Все VLAN» при приведении порта к соседу =====
// Признак «Все VLAN» (utils/allVlans.ts) — часть конфигурации порта, и «Применить конфигурацию соседа» / «Применить
// текущую конфигурацию» приводят к одному виду и его. Но «Все VLAN» устройства A и B — разные наборы номеров, а набор,
// выбранный вручную, у другого устройства может быть недоступен, поэтому значение пользователь выбирает сам: как у
// источника (признак либо набор, перенесённый по номерам VLAN) или другое (AllVlansChoiceModal).
//
// Сверка идёт ПОСЛЕ применения назначения и режима: смена режима сама меняет признак (из trunk в access он снимается,
// порт формы, переходящий в trunk, получает «Все VLAN» по умолчанию), и сравнивать нужно итоговое состояние. Значение
// нужно, только когда оба порта в trunk и признак есть у одного из них; если порт остался в access, признака у него нет.
// Порт формы правится в черновике (сохранится вместе с формой), порт другого устройства — сразу (PUT port-config).

/** Порт, участвующий в сверке «Все VLAN»: строка этой формы (ref — rowRef) либо порт другого устройства (interfaceId). */
type VlanSideRef =
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

interface AllVlansPrompt {
  portLabel: string
  sourceLabel: string
  description: string
  sourceValue: VlanValue
  missing: number[]
  options: VLANDefinition[]
  resolve: (value: VlanValue | null) => void
}
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
  const peerRow = props.modelValue.find((r) => r.id === conflict.otherInterfaceId)
  if (peerRow) return { kind: 'row', ref: rowRef(peerRow), label: `«${conflict.otherInterfaceName}» (это устройство)` }
  const label = `«${conflict.otherInterfaceName}» (${conflict.otherDeviceName})`
  return { kind: 'port', interfaceId: conflict.otherInterfaceId, label, ...(fresh ? {} : { known: { vlan_mode: conflict.other.vlan_mode, all_vlans: conflict.other.all_vlans } }) }
}

/** Режим и «Все VLAN» порта без запроса к серверу — когда они известны сразу (строка формы, порт-источник с известным состоянием). */
function knownVlanState(side: VlanSideRef): AllVlansState | null {
  if (side.kind === 'port') return side.known ?? null
  const row = props.modelValue.find((r) => rowRef(r) === side.ref)
  return row ? { vlan_mode: row.vlan_mode, all_vlans: carriesAllVlans(row) } : null
}

/** Значение VLAN порта в виде строки формы: «Все VLAN» зеркалит все VLAN устройства (так форма показывает их отмеченными). */
function rowPatchForValue(value: VlanValue): Partial<InterfaceDraftRow> {
  return { all_vlans: value.allVlans, vlan_ids: value.allVlans ? props.vlanOptions.map((v) => v.id) : [...value.vlanIds] }
}

async function resolveVlanSide(side: VlanSideRef): Promise<VlanSide | null> {
  if (side.kind === 'row') {
    const row = props.modelValue.find((r) => rowRef(r) === side.ref)
    if (!row) return null
    return {
      label: side.label,
      mode: row.vlan_mode,
      allVlans: carriesAllVlans(row),
      numbers: numbersOf(knownVlans.value, row.vlan_ids),
      options: props.vlanOptions,
      lockNote: rowManaged(row).vlan ? groupLockNote(row, 'Набор VLAN') : '',
      isDraft: true,
      write: async (value) => {
        const index = props.modelValue.findIndex((r) => rowRef(r) === side.ref)
        if (index !== -1) updateRow(index, rowPatchForValue(value))
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
      peersVersion.value++
      emit('neighbors-changed')
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

/** Нужна ли сверка «Все VLAN»: после смены режима и при явном расхождении признака. */
const needsAllVlansSettle = (kinds: readonly ConfigDiffKind[]) => kinds.includes('vlan_mode') || kinds.includes('all_vlans')

// Блок «Подключение» (InterfaceConnectionEditor): расхождение с выбранным соседом показывается сразу, ещё до
// сохранения формы, и тут же его можно устранить — любым из двух способов. kinds — что именно расходится.
//
// «Применить конфигурацию соседа»: этому порту — назначение (Управление/Передача данных) и/или режим соседа.
// Назначение правит только строку черновика (сохранится вместе с формой), режим — см. changeRowVlanMode.
async function applyPeerConfigToPort(index: number, peer: PeerConfigTarget, kinds: ConfigDiffKind[]) {
  const row = props.modelValue[index]
  if (!row || applyingPeerConfig.value) return
  applyingPeerConfig.value = true
  try {
    let changedDraft = false
    let waitsForCascade = false
    const source = peerSide(peer)
    const settle = () => (source ? settleAllVlans(source, ownSide(row)) : Promise.resolve())
    if (kinds.includes('flags')) {
      updateRow(index, { is_management: peer.config.is_management, is_data_transfer: peer.config.is_data_transfer })
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
//  * Сосед — порт ДРУГОГО устройства: это не черновик, а немедленный запрос, как у «Применить текущую
//    конфигурацию» в окне расхождения: PUT назначения и каскад режима (writeFlagsToNeighbor / cascadeStart).
//    Подключение при этом пока не сохранено — сообщение честно говорит, что порт соседа уже изменён.
async function applyPortConfigToPeer(index: number, peer: PeerConfigTarget, kinds: ConfigDiffKind[]) {
  const row = props.modelValue[index]
  if (!row || applyingPeerConfig.value) return
  applyingPeerConfig.value = true
  try {
    if (peer.isSelf) {
      const peerIndex = props.modelValue.findIndex((r) => rowRef(r) === peer.ref)
      if (peerIndex === -1) {
        notify('Порт соседа уже убран из формы — выберите соседа заново', 'warning')
        return
      }
      let changedDraft = false
      let waitsForCascade = false
      const settle = () => settleAllVlans(ownSide(row), { kind: 'row', ref: peer.ref, label: peer.label })
      if (kinds.includes('flags')) {
        updateRow(peerIndex, { is_management: row.is_management, is_data_transfer: row.is_data_transfer })
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
    const settleRemote = () => settleAllVlans(ownSide(row), { kind: 'port', interfaceId: peer.interfaceId!, label: peer.label })
    if (kinds.includes('flags')) {
      await writeFlagsToNeighbor(peer.interfaceId, row)
      notify(`Назначение порта соседа ${peer.label} изменено сразу (это порт другого устройства)`, 'success')
    }
    if (kinds.includes('vlan_mode')) {
      // Каскад сам запускает сверку «Все VLAN» по завершении (в т.ч. после подтверждения в окне последствий).
      afterCascade = settleRemote
      try {
        await cascadeStart(peer.interfaceId, row.vlan_mode, peer.label)
      } catch (err) {
        afterCascade = null
        throw err
      }
    } else if (needsAllVlansSettle(kinds)) {
      await settleRemote()
    }
    // Одно «Все VLAN»: порт соседа записывает и обновляет панель сам (resolveVlanSide) — второе уведомление ни к чему.
    if (kinds.some((kind) => kind !== 'all_vlans')) {
      peersVersion.value++
      emit('neighbors-changed')
    }
  } catch (err) {
    notifyError(err)
  } finally {
    applyingPeerConfig.value = false
  }
}

// ===== Проверка расхождений с соседями ПЕРЕД сохранением формы =====
// Предупреждение в блоке «Подключение» легко не заметить (строка порта свёрнута), а уведомление после записи
// ничего не предлагает и появляется, когда форма уже закрыта. Поэтому при нажатии «Сохранить» (DeviceFormModal
// вызывает reviewNeighborMismatches) расхождения, которые появляются именно в этом сохранении, выносятся в диалог:
// по каждому — те же два действия, что и в блоке «Подключение» (applyPeerConfigToPort / applyPortConfigToPeer),
// а внизу «Сохранить как есть» или «Вернуться к форме».
//
// Что считается «появляется в этом сохранении» — как у уведомления после записи (utils/portConflicts.ts): порт новый,
// его подключение создано или заменено в форме, либо конфигурация порта отличается от снимка при открытии формы.
// Старое, никем не тронутое расхождение диалог не поднимает — иначе он выскакивал бы при каждом сохранении.
interface ReviewPeerRef {
  ref: string
  isSelf: boolean
  deviceId?: string
  interfaceId?: string
  nameHint?: string
  deviceNameHint?: string
}
interface ReviewEntry {
  rowRef: string
  peer: ReviewPeerRef
}
interface ReviewItem {
  key: string
  index: number
  row: InterfaceDraftRow
  peer: PeerConfigTarget
  kinds: ConfigDiffKind[]
  texts: string[]
}

const reviewOpen = ref(false)
const reviewEntries = ref<ReviewEntry[]>([])
// Конфигурация портов соседей на ДРУГИХ устройствах (id порта → имя и конфигурация): с сервера, перечитывается после
// каждого применённого действия. Соседи с этого же устройства берутся из строк формы — они всегда актуальны.
const reviewPeers = ref<Record<string, { name: string; config: PortConfigLike }>>({})
let reviewResolve: ((proceed: boolean) => void) | null = null

function collectReviewEntries(initial: ReadonlyMap<string, PortConfig>): ReviewEntry[] {
  const changed = changedConnectionRowIds(props.modelValue, props.connectionBaseline ?? new Map())
  const self = props.deviceId ?? SELF_DEVICE
  const seenPairs = new Set<string>()
  const entries: ReviewEntry[] = []
  for (const row of props.modelValue) {
    const draft = row.connection
    const ref = rowRef(row)
    const peer = draft ? peerRef(draft) : ''
    if (!draft || !ref || !peer) continue
    const before = row.id ? initial.get(row.id) : undefined
    if (row.id && before && !changed.has(row.id) && samePortConfig(before, portConfigOf(row))) continue
    const isSelf = !!draft.peer_row_key || draft.peer_device_id === self
    if (isSelf) {
      // Два порта этого устройства, соединённые друг с другом, — одно расхождение, а не два.
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

async function loadReviewPeers(entries: readonly ReviewEntry[]): Promise<Record<string, { name: string; config: PortConfigLike }>> {
  const idsByDevice = new Map<string, Set<string>>()
  for (const { peer } of entries) {
    if (peer.isSelf || !peer.deviceId || !peer.interfaceId) continue
    const ids = idsByDevice.get(peer.deviceId) ?? new Set<string>()
    ids.add(peer.interfaceId)
    idsByDevice.set(peer.deviceId, ids)
  }
  const peers: Record<string, { name: string; config: PortConfigLike }> = {}
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

function reviewPeerTarget(peer: ReviewPeerRef): PeerConfigTarget | null {
  if (peer.isSelf) {
    const index = props.modelValue.findIndex((r) => rowRef(r) === peer.ref)
    if (index === -1) return null
    const target = props.modelValue[index]
    return {
      ref: peer.ref,
      label: `«${target.name.trim() || 'без имени'}» (это устройство, строка ${index + 1})`,
      config: portConfigOf(target),
      interfaceId: target.id,
      rowKey: target.id ? undefined : target.key,
      isSelf: true,
    }
  }
  const info = peer.interfaceId ? reviewPeers.value[peer.interfaceId] : undefined
  if (!peer.interfaceId || !info) return null
  return { ref: peer.ref, label: `«${peer.nameHint ?? info.name}» (${peer.deviceNameHint ?? 'другое устройство'})`, config: info.config, interfaceId: peer.interfaceId, isSelf: false }
}

// Расхождения, оставшиеся ПРЯМО СЕЙЧАС: считаются заново из строк формы и конфигурации соседей, поэтому
// устранённое действием из диалога пропадает из списка само.
const reviewItems = computed<ReviewItem[]>(() =>
  reviewEntries.value.flatMap((entry) => {
    const index = props.modelValue.findIndex((r) => rowRef(r) === entry.rowRef)
    const peer = reviewPeerTarget(entry.peer)
    if (index === -1 || !peer) return []
    const row = props.modelValue[index]
    const own = portConfigOf(row)
    const kinds = connectionConfigDiffKinds(own, peer.config)
    return kinds.length ? [{ key: `${entry.rowRef}>${entry.peer.ref}`, index, row, peer, kinds, texts: connectionConfigDiffs(own, peer.config) }] : []
  }),
)

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
const { onOverlayPointerDown: onReviewOverlayPointerDown, onOverlayClick: onReviewOverlayClick } = useOverlayDismiss(() => finishReview(false))

async function reviewApplyNeighbor(item: ReviewItem) {
  await applyPeerConfigToPort(item.index, item.peer, item.kinds)
  await refreshReviewPeers()
}
async function reviewApplyCurrent(item: ReviewItem) {
  await applyPortConfigToPeer(item.index, item.peer, item.kinds)
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
  if (!props.editConnections || reviewOpen.value) return true
  const entries = collectReviewEntries(initial)
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
// «Показать» в уведомлении о подинтерфейсах на снятом VLAN: раскрывает порты с такими подинтерфейсами (остальные
// раскрытые не сворачивает) и прокручивает к первому предупреждению. Возвращает число найденных портов.
const rootEl = ref<HTMLElement | null>(null)

async function revealStaleSubinterfaces(): Promise<number> {
  const indices = props.modelValue.flatMap((row, i) => (staleSubinterfaces(row.subinterfaces, allowedVlanIds.value).length ? [i] : []))
  if (!indices.length) return 0
  expandedIndices.value = new Set([...expandedIndices.value, ...indices])
  await nextTick()
  rootEl.value?.querySelector('.sub-warn')?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  return indices.length
}

defineExpose({ reviewNeighborMismatches, revealStaleSubinterfaces })

// Сохраняет существующие строки по индексу (вместе с их id/ips/vlan_ids) — повторное нажатие
// "Заменить" с другим количеством не должно рвать связь с уже сохранёнными интерфейсами и их IP,
// если индекс совпал. Совпадает по смыслу с generateInterfaces() в vanilla-версии.
//
// п.3.3, два фикса:
// 1) Если хотя бы одна строка уже содержит реальные данные (не просто пустая карточка,
//    добавленная кнопкой "+ Интерфейс"), генерация без предупреждения перезаписывала бы их
//    шаблонными значениями — теперь сначала спрашиваем подтверждение (тот же паттерн confirm(),
//    что и в DeviceFormModal.vue для конфликтов сохранения).
// 2) genTypeId/genSpeedId, оставленные "— не выбрано —", раньше ВСЕГДА принудительно затирали
//    interface_type_id/speed_id уже существующих строк пустым значением — даже если
//    пользователь нажал "Заменить" только чтобы поменять количество или шаблон имени, а тип
//    со скоростью на строках были выставлены вручную ранее. applyBulkEdit() ниже для того же
//    случая уже трактует пустое значение поля как "не менять" (bulkTypeId.value || row.type) —
//    generate() приведён к тому же принципу.
//
// п.1.4.1: раньше это была ЕДИНСТВЕННАЯ кнопка генератора — "заменить" было единственным
// доступным режимом, добавить N интерфейсов К уже существующим, не трогая их, было нельзя (кроме
// как по одному через "+ Интерфейс"). appendGenerated() ниже — второй режим именно для этого,
// доступный без галочки "Заменить все порты" (см. applyGenerator() и фикс п.1.3.4).
// Фикс п.1.3.3: явное «Начать нумерацию с» переопределяет умолчание (1 при замене, продолжение от числа строк при
// добавлении); пустое поле — «не задано», а не 0 (utils/interfaceRowDraft.ts:resolveStartNumber).
function generatorSettings(count: number, defaultStart: number): GeneratorSettings {
  return { count, startNumber: resolveStartNumber(genStartAt.value, defaultStart), nameTemplate: genNameTemplate.value, typeId: genTypeId.value, speedId: genSpeedId.value }
}

function generate() {
  // Фикс п.1.3.4: раньше подтверждение спрашивалось только если строки содержали "осмысленные"
  // данные (эвристика hasExistingData) — неочевидно и непредсказуемо для пользователя, когда
  // именно спросят, а когда молча заменят. Теперь режим "заменить" явно включается галочкой
  // "Заменить все порты" (по умолчанию выключена, см. applyGenerator()), поэтому предупреждение
  // безусловно показывается при любом непустом списке — раз уж галочка стоит, значит замена
  // ожидаема, но масштаб (сколько именно портов будет затронуто) всё равно стоит подтвердить.
  const count = Math.max(0, Number(genCount.value) || 0)
  // Фикс (аудит fix/usability-batch4, находка №1): count вычисляется ДО текста подтверждения,
  // чтобы отдельно предупредить про случай "Заменить все порты" + "Количество" = 0 — раньше это
  // молча удаляло все существующие порты устройства, а диалог говорил только про "заменит N шт.
  // новыми", не сообщая, что новых будет ноль.
  if (props.modelValue.length > 0) {
    const existingCount = props.modelValue.length
    const message = count === 0
      ? `Количество для генерации равно 0 — все ${existingCount} уже добавленных порта(ов) будут удалены, новые созданы не будут. Продолжить?`
      : `Это полностью заменит все порты устройства (${existingCount} шт.) новыми, сгенерированными по шаблону. Продолжить?`
    const ok = confirm(message)
    if (!ok) return
  }
  const rows = replaceWithGenerated(props.modelValue, generatorSettings(count, 1), knownVlans.value, emptyRow)
  selectedIndices.value = new Set()
  expandedIndices.value = new Set()
  copyTargetIndex.value = {}
  emit('update:modelValue', clearReferencesTo(rows, props.modelValue.slice(count)))
  replaceAllPorts.value = false // одноразовая осознанная галочка — не должна оставаться взведённой "на будущее" (см. её комментарий)
}

// п.1.4.1: добавляет genCount НОВЫХ интерфейсов к уже существующим, не трогая их вовсе — ни
// имена, ни тип/скорость, ни VLAN/IP. Нумерация в шаблоне имени продолжается от количества уже
// существующих строк (а не начинается заново с 1), чтобы не плодить дублирующиеся имена вроде
// второго eth1 при повторном использовании генератора. Подтверждение не нужно — действие ничего
// не перезаписывает.
function appendGenerated() {
  const count = Math.max(0, Number(genCount.value) || 0)
  if (!count) return
  const newRows = generateNewRows(generatorSettings(count, props.modelValue.length + 1), emptyRow)
  selectedIndices.value = new Set()
  emit('update:modelValue', [...props.modelValue, ...newRows])
}

// Фикс п.1.3.4: единственный обработчик кнопки "Сгенерировать" — маршрутизирует в один из двух
// прежних режимов по состоянию галочки "Заменить все порты" вместо двух отдельных кнопок.
function applyGenerator() {
  if (replaceAllPorts.value) {
    generate()
  } else {
    appendGenerated()
  }
}

function addRow() {
  selectedIndices.value = new Set()
  // п.1.4.3.1: новая строка НЕ разворачивается автоматически — блок VLAN/IP свёрнут по
  // умолчанию для любой строки, включая только что добавленную (было наоборот: разворачивалась
  // принудительно — см. историю, до этого фикса строка ниже была `expandedIndices.value.add(...)`).
  emit('update:modelValue', [...props.modelValue, emptyRow()])
}

function removeRow(index: number) {
  selectedIndices.value = new Set()
  expandedIndices.value = new Set()
  copyTargetIndex.value = {}
  emit(
    'update:modelValue',
    clearReferencesTo(
      props.modelValue.filter((_, i) => i !== index),
      [props.modelValue[index]],
    ),
  )
}

// Перестановка порта стрелками «вверх»/«вниз» в столбце порядка. Порядок строк массива и есть порядок, заданный
// пользователем: он уходит на сервер вместе со списком портов и сохраняется (device_interfaces.sort_order). Отмеченные
// галочкой и развёрнутые строки едут вместе со своим портом (индексы меняются местами); выбор получателя в «Копировать»
// сбрасывается, как при любом другом структурном изменении списка (см. removeRow).
function moveRowBy(index: number, direction: -1 | 1) {
  const moved = moveRow(props.modelValue, index, direction)
  if (!moved) return
  const target = index + direction
  selectedIndices.value = swapIndexes(selectedIndices.value, index, target)
  expandedIndices.value = swapIndexes(expandedIndices.value, index, target)
  copyTargetIndex.value = {}
  emit('update:modelValue', moved)
}

function updateRow(index: number, patch: Partial<InterfaceDraftRow>) {
  emit(
    'update:modelValue',
    props.modelValue.map((row, i) => (i === index ? { ...row, ...patch } : row)),
  )
}

function renamePort(index: number, name: string) {
  const row = props.modelValue[index]
  if (row) updateRow(index, portNamePatch(row, name, knownVlans.value))
}

function addIp(index: number) {
  const row = props.modelValue[index]
  if (!row) return
  updateRow(index, { ips: [...row.ips, { ip_address: '', prefix_length: '', purpose: '' }] })
}

function removeIp(index: number, ipIndex: number) {
  const row = props.modelValue[index]
  if (!row) return
  updateRow(index, { ips: row.ips.filter((_, j) => j !== ipIndex) })
}

function updateIp(index: number, ipIndex: number, patch: Partial<InterfaceIpDraftRow>) {
  const row = props.modelValue[index]
  if (!row) return
  updateRow(index, { ips: row.ips.map((ip, j) => (j === ipIndex ? { ...ip, ...patch } : ip)) })
}

// п.1.4 (батч4): выбранный в select'е индекс интерфейса-получателя для кнопки "Копировать" в
// блоке "Открытые порты" каждой строки — ключ по индексу СТРОКИ-ИСТОЧНИКА (не по её id: у ещё не
// сохранённой строки id нет). Чисто UI-состояние этого компонента, как selectedIndices/
// expandedIndices выше — сбрасывается при любом структурном изменении списка (см. generate()/
// addRow()/removeRow()), чтобы после сдвига индексов старый выбор не указывал на другую строку.
const copyTargetIndex = ref<Record<number, string>>({})

function setCopyTarget(index: number, targetIndexStr: string) {
  copyTargetIndex.value = { ...copyTargetIndex.value, [index]: targetIndexStr }
}

/** Копирует набор открытых портов строки sourceIndex на targetIndex — именно КОПИРУЕТ (у
 * источника порты остаются как есть), а не переносит: id каждого порта сбрасывается, чтобы при
 * сохранении backend/app/services/crud/interfaces.py:_sync_interface_open_ports создал НОВЫЕ записи для
 * целевого интерфейса, а не попытался переприсвоить владельца уже существующих (это отдельно
 * отклоняется как "порт не принадлежит выбранному интерфейсу" — порт физически размещён на
 * одном порту устройства, скопировать можно только сам список технологий/протоколов). Если у
 * получателя уже есть какие-то порты, требует подтверждения — молчаливая замена была бы
 * неожиданной потерей уже введённых данных. */
function copyPortsTo(sourceIndex: number, targetIndex: number) {
  const source = props.modelValue[sourceIndex]
  const target = props.modelValue[targetIndex]
  if (!source || !target || sourceIndex === targetIndex || !source.open_ports.length) return
  const sourceLabel = source.name || `#${sourceIndex + 1}`
  const targetLabel = target.name || `#${targetIndex + 1}`
  if (rowManaged(target).openPorts) {
    notify(groupLockNote(target, `Список открытых портов порта «${targetLabel}»`), 'error')
    return
  }
  if (target.open_ports.length) {
    const ok = confirm(`На порту «${targetLabel}» уже есть открытые порты (${target.open_ports.length} шт.) — заменить их копией с «${sourceLabel}» (${source.open_ports.length} шт.)?`)
    if (!ok) return
  }
  // Копия упорядочивается по номеру порта — как список, к которому пользователь добавил порт кнопкой.
  updateRow(targetIndex, { open_ports: sortOpenPortRows(source.open_ports.map((p) => ({ ...p, id: undefined })), props.protocolPortCatalog) })
  notify(`Открытые порты скопированы с «${sourceLabel}» на «${targetLabel}».`, 'success')
  setCopyTarget(sourceIndex, '')
}

function applyCopyPorts(sourceIndex: number) {
  const targetIndexStr = copyTargetIndex.value[sourceIndex]
  if (!targetIndexStr) return
  copyPortsTo(sourceIndex, Number(targetIndexStr))
}

function toggleVlan(index: number, vlanDefId: string, checked: boolean) {
  const row = props.modelValue[index]
  if (!row) return
  const vlan_ids = checked ? [...row.vlan_ids, vlanDefId] : row.vlan_ids.filter((id) => id !== vlanDefId)
  // Ручной выбор VLAN снимает признак «Все VLAN» — даже если в итоге выбраны все: признак не выводится из числа VLAN.
  updateRow(index, { vlan_ids, all_vlans: false })
}

// п.1.4.3.2: режим порта — access (ровно один VLAN) или trunk (несколько, в т.ч. "все").
function setVlanMode(index: number, mode: 'access' | 'trunk') {
  const row = props.modelValue[index]
  if (!row) return
  if (mode === 'access') {
    // При переключении в access оставляем только первый уже отмеченный VLAN — сохранить
    // несколько было бы некорректным сочетанием (см. validateInterfaceDraftRows).
    updateRow(index, { vlan_mode: 'access', vlan_ids: row.vlan_ids.slice(0, 1), all_vlans: false })
  } else {
    // Фикс п.2.1.1: переключение на trunk сразу отмечает "Все VLAN" — раньше vlan_ids оставался
    // как есть (пустым для новой строки), и пользователю приходилось ещё и сообразить, что нужно
    // отдельно поставить галочку "Все VLAN" самому. Теперь это сохраняемый признак (all_vlans): он ставится
    // сразу, а vlan_ids зеркалит все допустимые VLAN, чтобы форма показывала их отмеченными. Если у устройства
    // VLAN ещё нет, признак не ставится — «всех» пока нет, а порт не должен подхватывать VLAN, которые
    // пользователь потом добавит, не выбирая «Все VLAN» осознанно.
    updateRow(index, { vlan_mode: 'trunk', vlan_ids: props.vlanOptions.map((v) => v.id), all_vlans: props.vlanOptions.length > 0 })
  }
}

function setAccessVlan(index: number, vlanDefId: string) {
  updateRow(index, { vlan_ids: vlanDefId ? [vlanDefId] : [] })
}

// Access-порт: VLAN выбирается из списка с поиском (SearchableSelect) — VLAN у устройства может быть много.
const accessVlanOptions = computed(() => props.vlanOptions.map((v) => ({ value: v.id, label: vlanLabel(v) })))

// Trunk-порт: набор VLAN выбирается во всплывающем окне строки (PortVlanPickerModal). vlanPickerIndex — индекс строки,
// чьё окно открыто; пока окно открыто, форма под ним не редактируется, поэтому индекс остаётся верным.
const vlanPickerIndex = ref<number | null>(null)
const vlanPickerRow = computed(() => (vlanPickerIndex.value === null ? undefined : props.modelValue[vlanPickerIndex.value]))

/** "Все VLAN" в trunk-режиме — сохраняемый признак порта (InterfaceDraftRow.all_vlans, колонка
 * device_interfaces.all_vlans), а НЕ вывод из числа выбранных VLAN: порт, у которого вручную отмечены все VLAN,
 * признака не имеет, и наоборот. Пока признак стоит, vlan_ids зеркалит все допустимые VLAN устройства (так форма
 * показывает их отмеченными), а в БД хранится только признак — набор вычисляется из VLAN устройства. */
function isAllVlansSelected(row: InterfaceDraftRow): boolean {
  return row.all_vlans === true
}

function toggleAllVlans(index: number, checked: boolean) {
  updateRow(index, { all_vlans: checked, vlan_ids: checked ? props.vlanOptions.map((v) => v.id) : [] })
}

const selectedIndices = ref<Set<number>>(new Set())
// п.3.4: какие строки таблицы сейчас показывают развёрнутую панель (VLAN на порту, IP-адреса,
// описание) — вынесены из компактной таблицы под toggle, иначе редко нужные на каждый день поля
// съедали бы всю выгоду от перехода с карточек на таблицу.
const expandedIndices = ref<Set<number>>(new Set())
const bulkTypeId = ref('')
const bulkSpeedId = ref('')
const bulkManagement = ref('') // '' — не менять, 'true'/'false' — включить/выключить
const bulkDataTransfer = ref('')
const bulkVlanMode = ref('') // '' — не менять, 'access'/'trunk' — режим порта (п.1.4.3.2)
const bulkVlanIds = ref<Set<string>>(new Set())
// «Все VLAN» панели — тот же признак, что у порта (all_vlans), а не вывод из набора bulkVlanIds: ставится кликом по чекбоксу и
// снимается любым ручным выбором VLAN.
const bulkAllVlans = ref(false)
// Пункт 3 правки "физическое устройство: массовое редактирование" — при большом числе VLAN на
// устройстве инлайновый список чекбоксов в ячейке "растягивал" всю строку массового
// редактирования (а с ней — и всю таблицу). Список чекбоксов переехал во всплывающее окно,
// открываемое кнопкой; сама ячейка показывает только краткую сводку (сколько выбрано).
const bulkVlanPickerOpen = ref(false)
const bulkVlanSummary = computed(() => (bulkAllVlans.value ? 'Все VLAN' : bulkVlanIds.value.size ? `Выбрано VLAN: ${bulkVlanIds.value.size}` : '— выбрать VLAN —'))
const { onOverlayPointerDown: onVlanPickerOverlayPointerDown, onOverlayClick: onVlanPickerOverlayClick } = useOverlayDismiss(() => (bulkVlanPickerOpen.value = false))

function toggleSelect(index: number, checked: boolean) {
  if (checked) selectedIndices.value.add(index)
  else selectedIndices.value.delete(index)
}

function toggleSelectAll(checked: boolean) {
  selectedIndices.value = checked ? new Set(props.modelValue.map((_, i) => i)) : new Set()
}

function toggleExpand(index: number) {
  if (expandedIndices.value.has(index)) expandedIndices.value.delete(index)
  else expandedIndices.value.add(index)
}

function toggleBulkVlan(vlanDefId: string, checked: boolean) {
  if (checked) bulkVlanIds.value.add(vlanDefId)
  else bulkVlanIds.value.delete(vlanDefId)
  bulkAllVlans.value = false
}

// Пункт 4 правки "создание физического устройства": та же механика "Все VLAN", что и у
// isAllVlansSelected()/toggleAllVlans() для одиночного порта выше, только применительно к панели массового
// редактирования: отмеченные порты получают признак «Все VLAN» (а не просто набор из всех VLAN).
function isBulkAllVlansSelected(): boolean {
  return bulkAllVlans.value
}

function toggleBulkAllVlans(checked: boolean) {
  bulkAllVlans.value = checked
  bulkVlanIds.value = new Set(checked ? props.vlanOptions.map((v) => v.id) : [])
}

// Применяет накопленные в панели правки ко всем отмеченным карточкам разом — портировано из
// applyBulkInterfaceEdit() в vanilla-версии. Поля со значением "— не менять —" (пустая строка)
// не трогают соответствующее поле выбранных строк; VLAN добавляется К уже стоящим на порту
// (объединение множеств, не замена) — так же, как в vanilla, где легко случайно снять чужой VLAN
// массовым действием было бы хуже, чем просто ничего не убрать.
function applyBulkEdit() {
  if (!selectedIndices.value.size) {
    notify('Отметьте хотя бы один интерфейс галочкой "Выбрать".', 'error')
    return
  }
  emit(
    'update:modelValue',
    applyBulkEditToRows(
      props.modelValue,
      selectedIndices.value,
      { typeId: bulkTypeId.value, speedId: bulkSpeedId.value, management: bulkManagement.value, dataTransfer: bulkDataTransfer.value, vlanMode: bulkVlanMode.value, vlanIds: bulkVlanIds.value, allVlans: bulkAllVlans.value },
      props.vlanOptions,
      (row) => rowManaged(row).vlan,
    ),
  )
  // Полный сброс панели после применения — та же логика, что и полная перерисовка после
  // applyBulkInterfaceEdit() в vanilla-версии: без сброса "не менять" select бы продолжал
  // показывать уже применённое значение, будто его можно применить ещё раз.
  selectedIndices.value = new Set()
  bulkTypeId.value = ''
  bulkSpeedId.value = ''
  bulkManagement.value = ''
  bulkDataTransfer.value = ''
  bulkVlanMode.value = ''
  bulkVlanIds.value = new Set()
  bulkAllVlans.value = false
  bulkVlanPickerOpen.value = false
}
</script>

<template>
  <div ref="rootEl" class="nested-editor">
    <div class="nested-head">
      <b>Порты / интерфейсы</b>
      <span class="hint">Управление отмечается на одном или нескольких интерфейсах — все их IP считаются IP управления.</span>
    </div>

    <div v-if="staleSubinterfaceCount" class="stale-bulk" role="status">
      <span>Подинтерфейсов на VLAN, не назначенном устройству: {{ staleSubinterfaceCount }}.</span>
      <select v-model="bulkMoveTargetId" aria-label="Перенести все такие подинтерфейсы на VLAN" :disabled="!vlanOptions.length">
        <option value="">Перенести все на VLAN…</option>
        <option v-for="v in sortedVlanOptions" :key="v.id" :value="v.id">{{ vlanLabel(v) }}</option>
      </select>
      <button type="button" class="btn btn-secondary" :disabled="!bulkMoveTargetId" @click="moveAllStaleSubinterfaces">Перенести</button>
    </div>

    <div class="generator">
      <label>
        <span>Количество</span>
        <input type="number" min="0" v-model="genCount" />
      </label>
      <label>
        <span>Начать нумерацию с</span>
        <input type="number" v-model="genStartAt" placeholder="авто" title="Например, 'Количество: 20' и 'Начать с: 5' сгенерируют порты с номерами 5-24. Пусто — прежнее поведение: 1 при замене, продолжение от количества уже добавленных портов при дополнении." />
      </label>
      <label>
        <span>Шаблон имени <HelpTip :text="TEMPLATE_HELP_TEXT" /></span>
        <input type="text" v-model="genNameTemplate" placeholder="eth{n}" />
      </label>
      <label>
        <span>Тип по умолчанию</span>
        <div class="lookup-row">
          <select v-model="genTypeId">
            <option value="">— не выбрано —</option>
            <option v-for="t in typeOptions" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
          <QuickAddButton resource="interface-types" title="Тип интерфейса" @created="(r) => (genTypeId = r.id)" />
        </div>
      </label>
      <label>
        <span>Скорость по умолчанию</span>
        <div class="lookup-row">
          <select v-model="genSpeedId">
            <option value="">— не выбрано —</option>
            <option v-for="s in speedOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
          <QuickAddButton resource="interface-speeds" title="Скорость интерфейса" @created="(r) => (genSpeedId = r.id)" />
        </div>
      </label>
      <div class="generator-actions">
        <label class="replace-all-check">
          <input type="checkbox" v-model="replaceAllPorts" />
          <span>Заменить все порты</span>
        </label>
        <button type="button" class="btn btn-secondary" @click="applyGenerator">Сгенерировать</button>
      </div>
    </div>
    <span class="hint generator-hint">Без галочки «Заменить все порты» новые интерфейсы добавляются к уже существующим, не изменяя их. С галочкой — все существующие интерфейсы заменяются шаблонными значениями (после подтверждения).</span>

    <!-- Пункт 4 правки "создание физического устройства" ("Массовое редактирование должно быть в
         виде и с такой же разметкой, как таблица Список интерфейсов"): раньше это была отдельная
         flex-панель со своими подписанными полями НАД таблицей (см. историю фикса п.1.3.5 — тогда
         объединили только общую рамку, не разметку). Теперь это первая строка ТОЙ ЖЕ самой
         <table class="iface-table">, с теми же классами колонок col-select/col-index/col-check/
         col-actions — значения читаются по заголовкам <thead> таблицы ниже, отдельных подписей
         полей (бывший <span>Тип интерфейса</span> и т.п.) больше не нужно. -->
    <div v-if="modelValue.length" class="iface-panel">
      <InterfaceGroupsPanel
        :rows="modelValue"
        :groups="groups"
        :vlan-options="vlanOptions"
        :protocol-port-catalog="protocolPortCatalog"
        :selected-indices="[...selectedIndices]"
        :collapse-after="formPreferences.collapseRows"
        @change="onGroupsChange"
      />

      <div class="iface-list-head">
        <b>Список интерфейсов</b>
        <button type="button" class="btn btn-secondary" @click="addRow">
          <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
          Интерфейс
        </button>
      </div>

      <!-- п.3.4: список интерфейсов — компактная таблица вместо карточек на каждый интерфейс;
           редко нужные при первом взгляде поля (VLAN на порту, IP-адреса, описание) убраны под
           toggle в развёрнутую строку, чтобы таблица помещалась на экран без прокрутки даже при
           десятке портов. -->
      <div class="iface-table-wrap">
        <table class="iface-table">
        <thead>
          <tr>
            <th class="col-select">
              <input
                type="checkbox"
                :checked="selectedIndices.size === modelValue.length"
                aria-label="Выбрать все интерфейсы"
                @change="toggleSelectAll(($event.target as HTMLInputElement).checked)"
              />
            </th>
            <th class="col-index">#</th>
            <th class="col-order">Порядок</th>
            <th>Имя</th>
            <th>Тип</th>
            <th>MAC</th>
            <th>Скорость</th>
            <th class="col-check">Упр.</th>
            <th class="col-check">Данные</th>
            <th>VLAN / IP</th>
            <th class="col-actions"></th>
          </tr>
        </thead>
        <tbody>
          <tr class="bulk-edit-row">
            <td class="col-select">—</td>
            <td class="col-index">—</td>
            <td class="col-order">—</td>
            <td><b>Массовое редактирование</b></td>
            <td>
              <select class="cell-input" v-model="bulkTypeId" aria-label="Тип интерфейса — массовое редактирование">
                <option value="">— не менять —</option>
                <option v-for="t in typeOptions" :key="t.id" :value="t.id">{{ t.name }}</option>
              </select>
            </td>
            <td>—</td>
            <td>
              <select class="cell-input" v-model="bulkSpeedId" aria-label="Скорость — массовое редактирование">
                <option value="">— не менять —</option>
                <option v-for="s in speedOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
              </select>
            </td>
            <td class="col-check">
              <select class="cell-input bulk-tri-select" v-model="bulkManagement" aria-label="Управление — массовое редактирование">
                <option value="">—</option>
                <option value="true">Вкл</option>
                <option value="false">Выкл</option>
              </select>
            </td>
            <td class="col-check">
              <select class="cell-input bulk-tri-select" v-model="bulkDataTransfer" aria-label="Передача данных — массовое редактирование">
                <option value="">—</option>
                <option value="true">Вкл</option>
                <option value="false">Выкл</option>
              </select>
            </td>
            <td class="col-vlan-bulk">
              <select class="cell-input" v-model="bulkVlanMode" aria-label="Режим порта — массовое редактирование">
                <option value="">— не менять —</option>
                <option value="trunk">Trunk</option>
                <option value="access">Access</option>
              </select>
              <button
                v-if="vlanOptions.length"
                type="button"
                class="btn btn-secondary vlan-picker-btn"
                @click="bulkVlanPickerOpen = true"
              >
                {{ bulkVlanSummary }}
              </button>
              <span v-else class="empty">VLAN не назначены</span>
            </td>
            <td class="col-actions">
              <button
                type="button"
                class="icon-btn"
                title="Применить заполненные поля этой строки к отмеченным галочкой интерфейсам ниже"
                aria-label="Применить к выбранным"
                @click="applyBulkEdit"
              >
                <svg class="icon"><use href="/icons.svg#i-check" /></svg>
              </button>
            </td>
          </tr>
          <template v-for="(row, i) in modelValue" :key="row.id ?? row.key ?? i">
            <tr class="iface-row">
              <td class="col-select">
                <input
                  type="checkbox"
                  :checked="selectedIndices.has(i)"
                  aria-label="Выбрать интерфейс"
                  @change="toggleSelect(i, ($event.target as HTMLInputElement).checked)"
                />
              </td>
              <td class="col-index">{{ i + 1 }}</td>
              <td class="col-order">
                <button type="button" class="icon-btn order-btn" :disabled="i === 0" title="Выше" aria-label="Переместить интерфейс выше" @click="moveRowBy(i, -1)">
                  <svg class="icon"><use href="/icons.svg#i-chevu" /></svg>
                </button>
                <button type="button" class="icon-btn order-btn" :disabled="i === modelValue.length - 1" title="Ниже" aria-label="Переместить интерфейс ниже" @click="moveRowBy(i, 1)">
                  <svg class="icon"><use href="/icons.svg#i-chevd" /></svg>
                </button>
              </td>
              <td>
                <input type="text" class="cell-input" v-truncate-tooltip="row.name" :value="row.name" @input="renamePort(i, ($event.target as HTMLInputElement).value)" />
              </td>
              <td>
                <select class="cell-input" :value="row.interface_type_id" @change="updateRow(i, { interface_type_id: ($event.target as HTMLSelectElement).value })">
                  <option value="">— не выбрано —</option>
                  <option v-for="t in typeOptions" :key="t.id" :value="t.id">{{ t.name }}</option>
                </select>
              </td>
              <td>
                <input type="text" class="cell-input" v-truncate-tooltip="row.mac_address" :value="row.mac_address" @input="updateRow(i, { mac_address: ($event.target as HTMLInputElement).value })" />
              </td>
              <td>
                <select class="cell-input" :value="row.speed_id" @change="updateRow(i, { speed_id: ($event.target as HTMLSelectElement).value })">
                  <option value="">— не выбрано —</option>
                  <option v-for="s in speedOptions" :key="s.id" :value="s.id">{{ s.name }}</option>
                </select>
              </td>
              <td class="col-check" :class="{ 'has-conflict': rowConflict(row)?.flagsDiffer }">
                <input type="checkbox" :checked="row.is_management" @change="updateRow(i, { is_management: ($event.target as HTMLInputElement).checked })" />
                <button
                  v-if="rowConflict(row)?.flagsDiffer"
                  type="button"
                  class="conflict-icon-btn"
                  :title="conflictSummary(rowConflict(row)!, 'flags')"
                  aria-label="Расхождение с подключённым портом — открыть варианты решения"
                  @click="openConflict(i, 'flags')"
                >
                  <svg class="icon conflict-icon"><use href="/icons.svg#i-alert" /></svg>
                </button>
              </td>
              <td class="col-check" :class="{ 'has-conflict': rowConflict(row)?.flagsDiffer }">
                <input type="checkbox" :checked="row.is_data_transfer" @change="updateRow(i, { is_data_transfer: ($event.target as HTMLInputElement).checked })" />
              </td>
              <td>
                <button type="button" class="expand-toggle" @click="toggleExpand(i)">
                  <svg v-if="duplicatePortsByRow[i]?.length" class="icon conflict-icon ports-dup-icon" :aria-label="duplicatePortsText(duplicatePortsByRow[i])" :title="duplicatePortsText(duplicatePortsByRow[i])"><use href="/icons.svg#i-alert" /></svg>
                  <svg v-if="rowConflict(row)?.vlanModeDiffer" class="icon conflict-icon" aria-label="Расхождение режима порта с подключённым портом" :title="conflictSummary(rowConflict(row)!, 'vlan_mode')"><use href="/icons.svg#i-alert" /></svg>
                  <svg v-if="rowConflict(row)?.allVlansDiffer" class="icon conflict-icon" aria-label="Расхождение «Все VLAN» с подключённым портом" :title="conflictSummary(rowConflict(row)!, 'all_vlans')"><use href="/icons.svg#i-alert" /></svg>
                  <svg v-if="staleSubinterfaceText(row, allowedVlanIds)" class="icon conflict-icon stale-sub-icon" :aria-label="staleSubinterfaceText(row, allowedVlanIds)" :title="staleSubinterfaceText(row, allowedVlanIds)"><use href="/icons.svg#i-alert" /></svg>
                  <span v-truncate-tooltip>{{ vlanCellSummary(row, vlanOptions) }} · {{ row.ips.length }} IP<template v-if="row.subinterfaces?.length"> · {{ row.subinterfaces.length }} подинт.</template><template v-if="row.connection"> · {{ connectionSummary(row, modelValue, deviceId) }}</template><template v-if="rowGroup(row)"> · Группа «{{ rowGroup(row)!.name }}»</template></span>
                  <svg class="icon chev" :class="{ open: expandedIndices.has(i) }"><use href="/icons.svg#i-chevd" /></svg>
                </button>
              </td>
              <td class="col-actions">
                <button type="button" class="icon-btn danger" aria-label="Удалить интерфейс" @click="removeRow(i)">
                  <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                </button>
              </td>
            </tr>
            <tr v-if="expandedIndices.has(i)" class="iface-detail-row">
              <td colspan="11">
                <div class="iface-detail">
                  <label class="field field-wide">
                    <span>Описание</span>
                    <textarea :value="row.description" rows="2" @input="updateRow(i, { description: ($event.target as HTMLTextAreaElement).value })"></textarea>
                  </label>

                  <div class="vlan-block">
                    <div class="vlan-mode-row">
                      <b>Режим порта</b>
                      <span v-if="rowManaged(row).vlan" class="group-lock">{{ groupLockNote(row, 'Режим порта и VLAN') }}</span>
                      <button
                        v-if="rowConflict(row)?.vlanModeDiffer"
                        type="button"
                        class="conflict-icon-btn"
                        :title="conflictSummary(rowConflict(row)!, 'vlan_mode')"
                        aria-label="Расхождение режима порта с подключённым портом — открыть варианты решения"
                        @click="openConflict(i, 'vlan_mode')"
                      >
                        <svg class="icon conflict-icon"><use href="/icons.svg#i-alert" /></svg>
                      </button>
                      <label class="radio-inline">
                        <input
                          type="radio"
                          :name="`vlan-mode-${i}`"
                          :checked="row.vlan_mode !== 'access'"
                          :disabled="rowManaged(row).vlan"
                          @change="setVlanMode(i, 'trunk')"
                        />
                        Trunk
                      </label>
                      <label class="radio-inline">
                        <input
                          type="radio"
                          :name="`vlan-mode-${i}`"
                          :checked="row.vlan_mode === 'access'"
                          :disabled="rowManaged(row).vlan"
                          @change="setVlanMode(i, 'access')"
                        />
                        Access
                      </label>
                    </div>

                    <template v-if="row.vlan_mode === 'access'">
                      <div v-if="vlanOptions.length" class="field">
                        <span>VLAN порта (access — ровно один)</span>
                        <SearchableSelect
                          :model-value="row.vlan_ids[0] ?? ''"
                          :options="accessVlanOptions"
                          :disabled="rowManaged(row).vlan"
                          placeholder="— не выбрано —"
                          @update:model-value="(v) => setAccessVlan(i, v)"
                        />
                      </div>
                      <span v-else class="empty">Для типа устройства VLAN не назначены</span>
                    </template>
                    <template v-else>
                      <!-- Список VLAN trunk-порта вынесен во всплывающее окно (PortVlanPickerModal): при многих VLAN он растягивал
                           карточку порта. Галочка «Все VLAN» остаётся рядом с кнопкой, открывающей окно. -->
                      <div v-if="vlanOptions.length" class="trunk-row">
                        <label class="vlan-check vlan-check-all">
                          <input
                            type="checkbox"
                            :checked="isAllVlansSelected(row)"
                            :disabled="rowManaged(row).vlan"
                            @change="toggleAllVlans(i, ($event.target as HTMLInputElement).checked)"
                          />
                          <b>Все VLAN</b>
                        </label>
                        <button
                          v-if="rowConflict(row)?.allVlansDiffer"
                          type="button"
                          class="conflict-icon-btn"
                          data-testid="all-vlans-conflict"
                          :title="conflictSummary(rowConflict(row)!, 'all_vlans')"
                          aria-label="Расхождение «Все VLAN» с подключённым портом — открыть варианты решения"
                          @click="openConflict(i, 'all_vlans')"
                        >
                          <svg class="icon conflict-icon"><use href="/icons.svg#i-alert" /></svg>
                        </button>
                        <span class="vlan-summary" :title="trunkVlanTitle(row, vlanOptions)">{{ trunkVlanSummary(row, vlanOptions) }}</span>
                        <button type="button" class="btn btn-secondary vlan-picker-btn" @click="vlanPickerIndex = i">
                          {{ rowManaged(row).vlan ? 'Показать VLAN…' : 'Выбрать VLAN…' }}
                        </button>
                      </div>
                      <span v-else class="empty">Для типа устройства VLAN не назначены</span>
                    </template>
                  </div>

                  <div class="ip-block">
                    <div class="ip-head">
                      <b>IP-адреса интерфейса</b>
                      <span v-if="rowManaged(row).ip" class="group-lock">{{ groupLockNote(row, 'IP-адрес и его назначение') }}</span>
                      <button v-else type="button" class="btn btn-secondary" @click="addIp(i)">
                        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
                        IP-адрес
                      </button>
                    </div>
                    <div v-if="!row.ips.length" class="empty">IP-адреса не добавлены</div>
                    <div v-for="(ip, j) in row.ips" :key="ip.id ?? j" class="ip-row">
                      <input type="text" placeholder="IP-адрес" :value="ip.ip_address" :disabled="rowManaged(row).ip" @input="updateIp(i, j, { ip_address: ($event.target as HTMLInputElement).value })" />
                      <input
                        type="number"
                        min="0"
                        max="128"
                        placeholder="Префикс"
                        :value="ip.prefix_length"
                        :disabled="rowManaged(row).ip"
                        @input="updateIp(i, j, { prefix_length: ($event.target as HTMLInputElement).value })"
                      />
                      <input
                        type="text"
                        placeholder="Назначение"
                        :value="ip.purpose"
                        :disabled="rowManaged(row).ip"
                        @input="updateIp(i, j, { purpose: ($event.target as HTMLInputElement).value })"
                      />
                      <button v-if="!rowManaged(row).ip" type="button" class="icon-btn danger" aria-label="Удалить IP интерфейса" @click="removeIp(i, j)">
                        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
                      </button>
                    </div>
                  </div>

                  <!-- Подинтерфейсы порта (как у маршрутизаторов и межсетевых экранов: порт + подинтерфейс на
                       номере VLAN с отдельным IP и параметрами). VLAN подинтерфейса — один из VLAN, выбранных на
                       этом порту. Если порт в группе, которая задаёт подинтерфейсы, список только для просмотра:
                       группа записывает в каждый свой порт полный набор «<порт>.<VLAN>». -->
                  <InterfaceSubinterfacesEditor
                    :model-value="row.subinterfaces ?? []"
                    :parent-name="row.name"
                    :vlan-options="subinterfaceVlanOptions(row)"
                    :vlan-catalog="knownVlans"
                    :device-vlan-ids="allowedVlanIds"
                    :protocol-port-catalog="protocolPortCatalog"
                    :collapse-after="formPreferences.collapseRows"
                    :readonly="rowManaged(row).subinterfaces"
                    :readonly-note="rowManaged(row).subinterfaces ? groupLockNote(row, 'Список подинтерфейсов') : ''"
                    @update:model-value="(v) => updateRow(i, { subinterfaces: v })"
                  />

                  <!-- Подключение порта к порту другого устройства: создаётся здесь же, при
                       создании/редактировании устройства, и сохраняется тем же PUT, что и порты. -->
                  <InterfaceConnectionEditor
                    v-if="editConnections"
                    :model-value="row.connection ?? null"
                    :device-id="deviceId"
                    :device-label="deviceLabel"
                    :config="portConfigOf(row)"
                    :taken-peer-ids="takenPeerIds(modelValue, i)"
                    :self-ports="selfPortCandidates(modelValue, i)"
                    :freed-peer-ids="freedPeerIds"
                    :applying="applyingPeerConfig"
                    :peers-version="peersVersion"
                    @update:model-value="(v) => updateRow(i, { connection: v })"
                    @apply-peer-config="(peer, kinds) => applyPeerConfigToPort(i, peer, kinds)"
                    @apply-config-to-peer="(peer, kinds) => applyPortConfigToPeer(i, peer, kinds)"
                  />

                  <!-- Фикс п.1.4 (батч4): "Открытые порты" — теперь блок КОНКРЕТНОГО интерфейса
                       (был один общий на всё устройство в DeviceFormModal.vue), плюс копирование
                       уже введённого набора на другой интерфейс — типичный случай, когда
                       однотипные порты (uplink-группа, стек коммутаторов) незачем набирать
                       вручную заново на каждом. -->
                  <div class="ports-block">
                    <div class="ports-head">
                      <b>Открытые порты</b>
                      <span v-if="rowManaged(row).openPorts" class="group-lock">{{ groupLockNote(row, 'Список открытых портов') }}</span>
                      <div v-if="modelValue.length > 1 && !rowManaged(row).openPorts" class="copy-ports-row">
                        <select
                          class="copy-target-select"
                          :value="copyTargetIndex[i] ?? ''"
                          aria-label="Скопировать открытые порты на другой интерфейс"
                          @change="setCopyTarget(i, ($event.target as HTMLSelectElement).value)"
                        >
                          <option value="">Скопировать на порт…</option>
                          <template v-for="(other, oi) in modelValue" :key="other.id ?? oi">
                            <option v-if="oi !== i" :value="String(oi)">{{ other.name || `#${oi + 1}` }}</option>
                          </template>
                        </select>
                        <button
                          type="button"
                          class="btn btn-secondary"
                          :disabled="!row.open_ports.length || !copyTargetIndex[i]"
                          title="Скопировать открытые порты этого интерфейса на выбранный"
                          @click="applyCopyPorts(i)"
                        >
                          <svg class="icon"><use href="/icons.svg#i-copy" /></svg>
                          Копировать
                        </button>
                      </div>
                    </div>
                    <OpenPortListEditor
                      :model-value="row.open_ports"
                      :catalog-entries="protocolPortCatalog"
                      :readonly="rowManaged(row).openPorts"
                      :collapse-after="formPreferences.collapseRows"
                      sorted-unique
                      @update:model-value="(v) => updateRow(i, { open_ports: v })"
                    />
                  </div>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      </div>
    </div>

    <div v-else class="empty">
      Интерфейсы не добавлены
      <button type="button" class="btn btn-secondary" @click="addRow">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        Интерфейс
      </button>
    </div>
  </div>

  <!-- Пункт 3 правки "физическое устройство: массовое редактирование" — список VLAN для
       массового назначения вынесен из ячейки таблицы во всплывающее окно (см. bulkVlanPickerOpen
       выше) — сама модалка со своей внутренней прокруткой, а не растягивающийся список в ячейке. -->
  <div v-if="bulkVlanPickerOpen" class="overlay" @mousedown="onVlanPickerOverlayPointerDown" @click="onVlanPickerOverlayClick">
    <div class="vlan-picker-modal card" role="dialog" aria-modal="true">
      <div class="conflict-modal-head">
        <h3>Выбор VLAN — массовое редактирование</h3>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="bulkVlanPickerOpen = false">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <div class="vlan-checks vlan-picker-list">
        <!-- Пункт 4 (предыдущая правка): галочка "Все VLAN" — показывается только при выбранном
             Trunk, т.к. для access (не более одного VLAN) она не имеет смысла. -->
        <label v-if="bulkVlanMode === 'trunk'" class="vlan-check vlan-check-all">
          <input type="checkbox" :checked="isBulkAllVlansSelected()" @change="toggleBulkAllVlans(($event.target as HTMLInputElement).checked)" />
          <b>Все VLAN</b>
        </label>
        <label v-for="v in vlanOptions" :key="v.id" class="vlan-check">
          <input type="checkbox" :checked="bulkVlanIds.has(v.id)" @change="toggleBulkVlan(v.id, ($event.target as HTMLInputElement).checked)" />
          {{ vlanLabel(v) }}
        </label>
      </div>
      <div class="conflict-modal-actions">
        <button type="button" class="btn btn-primary" @click="bulkVlanPickerOpen = false">Готово</button>
      </div>
    </div>
  </div>

  <!-- Выбор VLAN trunk-порта строки таблицы: окно со своим поиском вместо длинного списка чекбоксов в карточке порта. -->
  <PortVlanPickerModal
    v-if="vlanPickerRow"
    :title="`VLAN порта «${vlanPickerRow.name.trim() || 'без имени'}»`"
    :options="vlanOptions"
    :selected-ids="vlanPickerRow.vlan_ids"
    :all-vlans="isAllVlansSelected(vlanPickerRow)"
    :readonly="rowManaged(vlanPickerRow).vlan"
    :readonly-note="rowManaged(vlanPickerRow).vlan ? groupLockNote(vlanPickerRow, 'Режим порта и VLAN') : ''"
    @toggle-vlan="(id, checked) => toggleVlan(vlanPickerIndex!, id, checked)"
    @toggle-all="(checked) => toggleAllVlans(vlanPickerIndex!, checked)"
    @close="vlanPickerIndex = null"
  />

  <!-- Пункты 1-2 правки "физическое устройство: расхождение с соседним портом" — окно решения:
       показывает конфигурацию текущего порта и соседнего рядом, даёт применить любую из двух. -->
  <!-- Проверка расхождений с соседями при нажатии «Сохранить». Стоит ДО окна последствий каскада режима порта
       (VlanModeCascadeModal): оно открывается из этого диалога и должно быть выше него. -->
  <div v-if="reviewOpen" class="overlay" @mousedown="onReviewOverlayPointerDown" @click="onReviewOverlayClick">
    <div class="conflict-modal review-modal card" role="alertdialog" aria-modal="true" aria-labelledby="neighbor-review-title">
      <div class="conflict-modal-head">
        <h3 id="neighbor-review-title">Настройки порта расходятся с соседним портом</h3>
        <button type="button" class="icon-btn" aria-label="Вернуться к форме" @click="finishReview(false)">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <template v-if="reviewItems.length">
        <p class="conflict-modal-desc">
          Назначение («Управление» / «Передача данных»), режим порта (Trunk / Access) или «Все VLAN» отличается от настроек порта на другом конце подключения. Можно
          привести их к одному виду сейчас (для «Все VLAN» значение выбираете вы) или сохранить как есть — расхождение будет отмечено на экране «Подключения».
        </p>
        <ul class="review-list">
          <li v-for="item in reviewItems" :key="item.key" class="review-item">
            <div class="review-item-title">Порт «{{ item.row.name.trim() || 'без имени' }}» ↔ {{ item.peer.label }}</div>
            <div class="review-item-diffs">{{ item.texts.join('; ') }}</div>
            <div class="review-item-actions">
              <button type="button" class="btn btn-secondary" :disabled="applyingPeerConfig || cascadeApplying" title="Этому порту — назначение, режим порта и «Все VLAN» соседа" @click="reviewApplyNeighbor(item)">
                Применить конфигурацию соседа
              </button>
              <button type="button" class="btn btn-secondary" :disabled="applyingPeerConfig || cascadeApplying" title="Соседу — назначение, режим порта и «Все VLAN» этого порта" @click="reviewApplyCurrent(item)">
                Применить текущую конфигурацию
              </button>
            </div>
            <small v-if="!item.peer.isSelf" class="review-item-note">Сосед — порт другого устройства: его настройки изменятся сразу, не дожидаясь сохранения формы.</small>
          </li>
        </ul>
      </template>
      <p v-else class="conflict-modal-desc review-done">Расхождений не осталось.</p>
      <div class="review-footer">
        <button type="button" class="btn btn-secondary" @click="finishReview(false)">Вернуться к форме</button>
        <button type="button" class="btn btn-primary" @click="finishReview(true)">{{ reviewItems.length ? 'Сохранить как есть' : 'Сохранить' }}</button>
      </div>
    </div>
  </div>

  <div v-if="activeConflict" class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="conflict-modal card" role="dialog" aria-modal="true">
      <div class="conflict-modal-head">
        <h3>{{ conflictTitle(activeConflict.kind) }}</h3>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="closeConflict">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <p class="conflict-modal-desc">
        Порт «{{ modelValue[activeConflict.index].name }}» соединён с портом «{{ rowConflict(modelValue[activeConflict.index])?.otherInterfaceName }}» устройства
        «{{ rowConflict(modelValue[activeConflict.index])?.otherDeviceName }}», но их настройки разошлись.
      </p>
      <table class="conflict-compare">
        <thead>
          <tr>
            <th></th>
            <th>Этот порт</th>
            <th>Соседний порт</th>
          </tr>
        </thead>
        <tbody v-if="activeConflict.kind === 'flags'">
          <tr>
            <td>Управление</td>
            <td>{{ modelValue[activeConflict.index].is_management ? 'Да' : 'Нет' }}</td>
            <td>{{ rowConflict(modelValue[activeConflict.index])?.other.is_management ? 'Да' : 'Нет' }}</td>
          </tr>
          <tr>
            <td>Передача данных</td>
            <td>{{ modelValue[activeConflict.index].is_data_transfer ? 'Да' : 'Нет' }}</td>
            <td>{{ rowConflict(modelValue[activeConflict.index])?.other.is_data_transfer ? 'Да' : 'Нет' }}</td>
          </tr>
        </tbody>
        <tbody v-else-if="activeConflict.kind === 'all_vlans'">
          <tr>
            <td>Все VLAN</td>
            <td>{{ carriesAllVlans(modelValue[activeConflict.index]) ? 'Да' : 'Нет' }}</td>
            <td>{{ rowConflict(modelValue[activeConflict.index])?.other.all_vlans ? 'Да' : 'Нет' }}</td>
          </tr>
        </tbody>
        <tbody v-else>
          <tr>
            <td>Режим порта</td>
            <td>{{ modelValue[activeConflict.index].vlan_mode === 'access' ? 'Access' : 'Trunk' }}</td>
            <td>{{ rowConflict(modelValue[activeConflict.index])?.other.vlan_mode === 'access' ? 'Access' : 'Trunk' }}</td>
          </tr>
        </tbody>
      </table>
      <div class="conflict-modal-actions">
        <button type="button" class="btn btn-secondary" :disabled="applyingConflict" @click="applyNeighborConfig">Применить конфигурацию соседа</button>
        <button type="button" class="btn btn-primary" :disabled="applyingConflict" @click="applyCurrentConfigToNeighbor">Применить текущую конфигурацию</button>
      </div>
      <p v-if="activeConflict.kind === 'vlan_mode'" class="conflict-modal-hint">
        Если порт (свой или соседа) входит в группу или связан с другими портами, режим сменится у всей группы и у связанных портов, чтобы расхождения не появились
        в другом месте. Перед применением будет показан список всех последствий. Если после смены режима у портов разойдётся «Все VLAN», предложим выбрать значение.
      </p>
      <p v-if="activeConflict.kind === 'all_vlans'" class="conflict-modal-hint">
        «Все VLAN» у устройств — разные наборы номеров, поэтому значение для порта выбираете вы: как у порта-источника или другое.
      </p>
    </div>
  </div>

  <VlanModeCascadeModal
    v-if="cascadePending"
    :plan="cascadePending.plan"
    :applying="cascadeApplying"
    :port-label="cascadePending.portLabel"
    @confirm="cascadeConfirm"
    @cancel="cancelCascadeReview"
  />

  <!-- «Все VLAN» у порта расходится с соседом: какое значение установить (как у источника или другое). -->
  <AllVlansChoiceModal
    v-if="allVlansPrompt"
    :port-label="allVlansPrompt.portLabel"
    :source-label="allVlansPrompt.sourceLabel"
    :description="allVlansPrompt.description"
    :source-value="allVlansPrompt.sourceValue"
    :missing="allVlansPrompt.missing"
    :options="allVlansPrompt.options"
    @confirm="(value) => answerAllVlansPrompt(value)"
    @cancel="answerAllVlansPrompt(null)"
  />
</template>

<style scoped>
.nested-editor {
  grid-column: 1 / -1;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.nested-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.nested-head b {
  font-size: 12.5px;
}
.hint {
  font-size: 10.5px;
  color: var(--ink-muted);
}
.empty {
  font-size: 12px;
  color: var(--ink-muted);
  padding: 4px 0;
}
.generator {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}
.generator label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
}
.generator label > span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.generator-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.replace-all-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--ink-muted);
  white-space: nowrap;
}
.replace-all-check input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
}
.generator-hint {
  display: block;
  margin-top: -4px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}
.generator input,
.generator select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
  width: 130px;
}
.generator .lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.generator .lookup-row select {
  width: 130px;
}
/* Пункт 4 правки "создание физического устройства": панель массового редактирования стала
   первой строкой той же <table class="iface-table"> ниже (было — отдельная flex-панель со
   своими подписанными полями, см. историю фикса п.1.3.5 выше — тогда объединили только общую
   рамку .iface-panel, не саму разметку). */
.iface-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 10px;
}
.bulk-edit-row {
  background: var(--surface-2);
}
.bulk-edit-row .cell-input {
  width: 100%;
}
/* Тройной выбор "не менять/вкл/выкл" не помещается в узкую .col-check (рассчитанную на один
   чекбокс 14×14) без переноса — расширяем только для этого select, не трогая ширину самой
   колонки у остальных строк (у них там обычный чекбокс, ему запас не нужен). */
.bulk-tri-select {
  min-width: 64px;
}
.col-vlan-bulk {
  min-width: 220px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.vlan-picker-btn {
  white-space: nowrap;
}
.vlan-picker-modal {
  width: 100%;
  max-width: 360px;
  padding: 18px 20px 16px;
  display: flex;
  flex-direction: column;
  max-height: 80vh;
}
.vlan-picker-list {
  overflow-y: auto;
  margin-bottom: 14px;
}
.iface-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.iface-list-head b {
  font-size: 12px;
}
.empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
/* п.3.4/3.5: компактная таблица интерфейсов вместо карточки на каждый порт; кнопка
   "+ Интерфейс" (п.3.5) теперь стоит в шапке этого же блока, а не среди полей генератора
   выше — она относится к списку, а не к настройкам массовой генерации. */
.iface-table-wrap {
  overflow-x: auto;
}
.iface-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.iface-table th {
  text-align: left;
  font-weight: 600;
  color: var(--ink-muted);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  padding: 0 6px 6px;
  white-space: nowrap;
}
.iface-table td {
  padding: 4px 6px;
  vertical-align: middle;
  border-top: 1px solid var(--border);
}
.iface-table .col-select,
.iface-table .col-index,
.iface-table .col-order,
.iface-table .col-check,
.iface-table .col-actions {
  width: 1%;
  white-space: nowrap;
  text-align: center;
}
.iface-table .col-select input,
.iface-table .col-check input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
}
.iface-table .col-index {
  color: var(--ink-muted);
}
/* Столбец порядка: две кнопки-стрелки рядом, чтобы столбец оставался узким. */
.iface-table .col-order .order-btn {
  display: inline-flex;
}
.iface-table .col-order .order-btn:disabled {
  opacity: 0.3;
  cursor: default;
}
/* Фикс п.3.3 (вторая часть): подсвечивает ячейку "Упр."/"Данные" интерфейса, чьё назначение
   разошлось с назначением на связанном (по активному подключению) порту другого устройства. */
.iface-table .col-check.has-conflict {
  background: var(--status-warn-soft);
  position: relative;
}
.conflict-icon {
  width: 11px;
  height: 11px;
  color: var(--status-warn);
  flex-shrink: 0;
}
.iface-table .col-check .conflict-icon-btn {
  position: absolute;
  top: 2px;
  right: 2px;
}
.cell-input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 7px;
  font-size: 12px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
  min-width: 90px;
  box-sizing: border-box;
}
.stale-bulk {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
  padding: 8px 10px;
  border: 1px solid var(--status-warn);
  border-radius: var(--r-s);
  font-size: 12px;
}
.stale-bulk select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 5px 8px;
  font-size: 12px;
  color: var(--ink);
  font-family: inherit;
}
.expand-toggle {
  display: flex;
  align-items: center;
  gap: 5px;
  background: none;
  border: none;
  padding: 4px 2px;
  font-size: 11.5px;
  color: var(--ink-muted);
  cursor: pointer;
  white-space: nowrap;
}
.expand-toggle:hover {
  color: var(--ink);
}
.chev {
  width: 13px;
  height: 13px;
  transition: transform 0.15s;
  flex-shrink: 0;
}
.chev.open {
  transform: rotate(180deg);
}
.iface-detail-row td {
  border-top: none;
  padding: 0 6px 10px;
}
.iface-detail {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
  background: var(--surface-2);
  border-radius: var(--r-s);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
}
.field-wide {
  grid-column: 1 / -1;
}
.field input[type='text'],
.field select,
.field textarea {
  background: var(--surface-1, var(--surface));
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
}
.vlan-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.vlan-block b {
  font-size: 11.5px;
}
.vlan-mode-row {
  display: flex;
  align-items: center;
  gap: 14px;
}
.radio-inline {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--ink);
  cursor: pointer;
}
.radio-inline input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
  margin: 0;
}
.vlan-check-all {
  padding-right: 10px;
  margin-right: 4px;
  border-right: 1px solid var(--border);
}
.trunk-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
}
.trunk-row .vlan-check-all {
  margin-right: 0;
}
.vlan-summary {
  font-size: 12px;
  color: var(--ink-muted);
}
.vlan-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
}
.vlan-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--ink);
}
.vlan-check input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
}
.ip-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ip-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ip-head b {
  font-size: 11.5px;
}
.ip-row {
  display: grid;
  grid-template-columns: 1.4fr 0.7fr 1.4fr auto;
  align-items: center;
  gap: 8px;
}
.ip-row input {
  background: var(--surface-1, var(--surface));
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 8px;
  font-size: 12px;
  color: var(--ink);
  width: 100%;
}
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
}
.icon-btn.danger:hover {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}
.ports-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-top: 1px dashed var(--border);
  padding-top: 10px;
}
.ports-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.ports-head b {
  font-size: 11.5px;
}
.copy-ports-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.copy-target-select {
  background: var(--surface-1, var(--surface));
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 8px;
  font-size: 12px;
  color: var(--ink);
}

@media (max-width: 640px) {
  .ip-row {
    grid-template-columns: 1fr;
  }
  .copy-ports-row {
    flex-wrap: wrap;
    width: 100%;
  }
}

/* Подсказка у заблокированных полей порта, чьи значения задаёт группа портов. */
.group-lock {
  font-size: 11px;
  color: var(--ink-muted);
}

/* Пункты 1-2 правки "физическое устройство: расхождение с соседним портом" — окно решения
   конфликта. .overlay/.modal-head — та же база, что и в остальных модалках приложения (напр.
   ConnectionFormModal.vue), но пошире карточка не нужна — здесь всего сравнительная таблица из
   двух-трёх строк и две кнопки. */
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 70;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 60px 16px;
  overflow-y: auto;
}
.conflict-modal {
  width: 100%;
  max-width: 420px;
  padding: 18px 20px 16px;
}
.conflict-modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.conflict-modal-head h3 {
  font-family: var(--font-display);
  font-size: 14.5px;
  margin: 0;
}
.conflict-modal-desc {
  font-size: 12px;
  color: var(--ink-muted);
  margin: 0 0 12px;
}
.conflict-compare {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
  margin-bottom: 14px;
}
.conflict-compare th {
  text-align: left;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  padding: 4px 8px;
  border-bottom: 1px solid var(--border);
}
.conflict-compare td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}
.conflict-compare tr:last-child td {
  border-bottom: none;
}
.conflict-modal-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.conflict-modal-actions .btn {
  width: 100%;
  justify-content: center;
}
.conflict-modal-hint {
  font-size: 11.5px;
  color: var(--ink-muted);
  margin: 10px 0 0;
}
.review-modal {
  max-width: 560px;
  max-height: 85vh;
  overflow-y: auto;
}
.review-list {
  list-style: none;
  margin: 0 0 14px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.review-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.review-item-title {
  font-size: 12.5px;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.review-item-diffs {
  font-size: 12px;
  color: var(--status-warn);
}
.review-item-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.review-item-actions .btn {
  padding: 5px 9px;
  font-size: 11.5px;
}
.review-item-note {
  font-size: 11px;
  color: var(--ink-muted);
}
.review-done {
  color: var(--ink);
}
.review-footer {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}
.conflict-icon-btn {
  border: none;
  background: transparent;
  padding: 0;
  display: inline-flex;
  cursor: pointer;
}
</style>
