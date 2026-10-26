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
import { useFormPreferencesStore } from '../stores/formPreferences'
import type { CatalogItem, InterfaceDraftRow, InterfaceGroupDraft, InterfaceIpDraftRow, PortConflictInfo, ProtocolPortCatalogEntry, VLANDefinition } from '../api/types'
import { useToast } from '../composables/useToast'
import { useBulkEdit } from '../composables/useBulkEdit'
import { useGroupLocks } from '../composables/useGroupLocks'
import { useInterfaceRows } from '../composables/useInterfaceRows'
import { useNeighborSync } from '../composables/useNeighborSync'
import { usePortGenerator } from '../composables/usePortGenerator'
import { usePreSaveReview } from '../composables/usePreSaveReview'
import { useRowUiState } from '../composables/useRowUiState'
import { useVlanSelection } from '../composables/useVlanSelection'
import { vTruncateTooltip } from '../directives/truncateTooltip'
import { vlanLabel } from '../utils/vlan'
import { TEMPLATE_HELP_TEXT } from '../utils/interfaceRowDraft'
import { conflictSummary, connectionSummary, duplicatePortsText, staleSubinterfaceText, trunkVlanSummary, trunkVlanTitle, vlanCellSummary } from '../utils/interfaceRowView'
import { freedPeerIds as computeFreedPeerIds, selfPortCandidates, takenPeerIds } from '../utils/interfacePeers'
import { duplicatePortNumbers } from '../utils/openPorts'
import { moveStaleMessage, moveStaleSubinterfaces, portVlanOptions, staleSubinterfaces } from '../utils/subinterfaces'
import { newRowKey, type ConnectionBaseline } from '../utils/interfaceConnections'
import { portConfigOf } from '../utils/portConflicts'
import QuickAddButton from './QuickAddButton.vue'
import HelpTip from './HelpTip.vue'
import OpenPortListEditor from './OpenPortListEditor.vue'
import InterfaceSubinterfacesEditor from './InterfaceSubinterfacesEditor.vue'
import InterfaceGroupsPanel from './InterfaceGroupsPanel.vue'
import InterfaceConnectionEditor from './InterfaceConnectionEditor.vue'
import AllVlansChoiceModal from './AllVlansChoiceModal.vue'
import BulkVlanPickerModal from './BulkVlanPickerModal.vue'
import InterfaceBulkBar from './InterfaceBulkBar.vue'
import InterfaceStaleBar from './InterfaceStaleBar.vue'
import NeighborReviewModal from './NeighborReviewModal.vue'
import PortConflictModal from './PortConflictModal.vue'
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
const { notify } = useToast()
// Общий порог сворачивания длинных списков (из «Настроек») — передаётся вложенным редакторам открытых портов.
const formPreferences = useFormPreferencesStore()

// Панель групп отдаёт согласованное изменение порт+группа одним событием.
function onGroupsChange(payload: { rows: InterfaceDraftRow[]; groups: InterfaceGroupDraft[] }) {
  emit('update:modelValue', payload.rows)
  emit('update:groups', payload.groups)
  selectedIndices.value = new Set()
}

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

// Группа порта и то, чем она управляет (composables/useGroupLocks.ts).
const { rowGroup, rowManaged, groupLockNote } = useGroupLocks(() => props.groups)

// Список портов — проп родителя: любое изменение уходит наверх событием update:modelValue. Состояние списка (отметки,
// раскрытие, получатель копирования) — useRowUiState, операции над строками — useInterfaceRows, генератор — usePortGenerator,
// массовое редактирование — useBulkEdit, выбор VLAN — useVlanSelection.
const setRows = (rows: InterfaceDraftRow[]) => emit('update:modelValue', rows)
const rowUi = useRowUiState(() => props.modelValue.length)
const { selectedIndices, expandedIndices, copyTargetIndex, toggleSelect, toggleSelectAll, toggleExpand, setCopyTarget } = rowUi
const { emptyRow, addRow, removeRow, moveRowBy, updateRow, renamePort, applyCopyPorts } = useInterfaceRows(
  {
    rows: () => props.modelValue,
    setRows,
    knownVlans: () => knownVlans.value,
    protocolPortCatalog: () => props.protocolPortCatalog,
    editConnections: () => props.editConnections,
    rowManaged,
    groupLockNote,
  },
  rowUi,
)
const { genCount, genStartAt, genNameTemplate, genTypeId, genSpeedId, replaceAllPorts, applyGenerator } = usePortGenerator(
  { rows: () => props.modelValue, setRows, knownVlans: () => knownVlans.value, emptyRow },
  rowUi,
)
const {
  bulkTypeId,
  bulkSpeedId,
  bulkManagement,
  bulkDataTransfer,
  bulkVlanMode,
  bulkVlanIds,
  bulkAllVlans,
  bulkVlanPickerOpen,
  bulkVlanSummary,
  toggleBulkVlan,
  toggleBulkAllVlans,
  applyBulkEdit,
} = useBulkEdit({ rows: () => props.modelValue, setRows, vlanOptions: () => props.vlanOptions, rowManaged }, rowUi)
const { vlanPickerIndex, vlanPickerRow, toggleVlan, setVlanMode, setAccessVlan, toggleAllVlans } = useVlanSelection({
  rows: () => props.modelValue,
  vlanOptions: () => props.vlanOptions,
  updateRow,
})

const staleSubinterfaceCount = computed(() => props.modelValue.reduce((sum, row) => sum + staleSubinterfaces(row.subinterfaces, allowedVlanIds.value).length, 0))

// Массовый перенос (InterfaceStaleBar.vue): все подинтерфейсы на недоступных VLAN — на один выбранный VLAN устройства одним действием
// (вместо правки каждого). Там, где на порту этот VLAN уже занят, подинтерфейс остаётся на месте — о таких говорит предупреждение.
function moveAllStaleSubinterfaces(target: VLANDefinition) {
  const result = moveStaleSubinterfaces(props.modelValue, target, allowedVlanIds.value, knownVlans.value)
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

// Порт, у которого открыто окно решения расхождения (по индексу из activeConflict; пока окно открыто, строки могут измениться).
const conflictRow = computed(() => (activeConflict.value ? props.modelValue[activeConflict.value.index] : undefined))

// Порты соседей, которые эта форма освобождает: подключение порта снято или переставлено на другой порт.
const freedPeerIds = computed(() => computeFreedPeerIds(props.modelValue, props.connectionBaseline))

// Согласование портов с соседними (composables/useNeighborSync.ts): окно решения расхождения по значку, действия блока
// «Подключение», каскад режима порта и сверка «Все VLAN». Проверка расхождений перед сохранением формы — usePreSaveReview.
const {
  activeConflict,
  applyingConflict,
  peersVersion,
  applyingPeerConfig,
  rowConflict,
  openConflict,
  closeConflict,
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
} = useNeighborSync({
  rows: () => props.modelValue,
  groups: () => props.groups,
  deviceId: () => props.deviceId,
  conflicts: () => props.conflicts,
  vlanOptions: () => props.vlanOptions,
  knownVlans: () => knownVlans.value,
  setRows,
  setGroups: (groups: InterfaceGroupDraft[]) => emit('update:groups', groups),
  updateRow,
  setVlanMode,
  rowManaged,
  groupLockNote,
  emitNeighborsChanged: () => emit('neighbors-changed'),
  onCascadeFinished: () => void refreshReviewPeers(),
})

const { reviewOpen, reviewItems, finishReview, reviewApplyNeighbor, reviewApplyCurrent, refreshReviewPeers, reviewNeighborMismatches } = usePreSaveReview({
  rows: () => props.modelValue,
  deviceId: () => props.deviceId,
  editConnections: () => props.editConnections,
  connectionBaseline: () => props.connectionBaseline,
  applyPeerConfigToPort,
  applyPortConfigToPeer,
})

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

// Access-порт: VLAN выбирается из списка с поиском (SearchableSelect) — VLAN у устройства может быть много.
const accessVlanOptions = computed(() => props.vlanOptions.map((v) => ({ value: v.id, label: vlanLabel(v) })))

/** "Все VLAN" в trunk-режиме — сохраняемый признак порта (InterfaceDraftRow.all_vlans, колонка
 * device_interfaces.all_vlans), а НЕ вывод из числа выбранных VLAN: порт, у которого вручную отмечены все VLAN,
 * признака не имеет, и наоборот. Пока признак стоит, vlan_ids зеркалит все допустимые VLAN устройства (так форма
 * показывает их отмеченными), а в БД хранится только признак — набор вычисляется из VLAN устройства. */
function isAllVlansSelected(row: InterfaceDraftRow): boolean {
  return row.all_vlans === true
}

</script>

<template>
  <div ref="rootEl" class="nested-editor">
    <div class="nested-head">
      <b>Порты / интерфейсы</b>
      <span class="hint">Управление отмечается на одном или нескольких интерфейсах — все их IP считаются IP управления.</span>
    </div>

    <InterfaceStaleBar v-if="staleSubinterfaceCount" :count="staleSubinterfaceCount" :vlan-options="vlanOptions" @move="moveAllStaleSubinterfaces" />

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
          <InterfaceBulkBar
            v-model:type-id="bulkTypeId"
            v-model:speed-id="bulkSpeedId"
            v-model:management="bulkManagement"
            v-model:data-transfer="bulkDataTransfer"
            v-model:vlan-mode="bulkVlanMode"
            :type-options="typeOptions"
            :speed-options="speedOptions"
            :has-vlans="vlanOptions.length > 0"
            :vlan-summary="bulkVlanSummary"
            @open-vlan-picker="bulkVlanPickerOpen = true"
            @apply="applyBulkEdit"
          />
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

  <!-- Список VLAN для массового назначения — во всплывающем окне (useBulkEdit: bulkVlanPickerOpen), а не растягивающийся список в ячейке. -->
  <BulkVlanPickerModal
    v-if="bulkVlanPickerOpen"
    :vlan-options="vlanOptions"
    :vlan-mode="bulkVlanMode"
    :all-vlans="bulkAllVlans"
    :selected-ids="bulkVlanIds"
    @toggle-all="toggleBulkAllVlans"
    @toggle-vlan="toggleBulkVlan"
    @close="bulkVlanPickerOpen = false"
  />

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

  <!-- Проверка расхождений с соседями при нажатии «Сохранить». Стоит ДО окна последствий каскада режима порта
       (VlanModeCascadeModal): оно открывается из этого диалога и должно быть выше него. -->
  <NeighborReviewModal
    v-if="reviewOpen"
    :items="reviewItems"
    :busy="applyingPeerConfig || cascadeApplying"
    @finish="finishReview"
    @apply-neighbor="reviewApplyNeighbor"
    @apply-current="reviewApplyCurrent"
  />

  <!-- Окно решения расхождения порта с соседним: конфигурация текущего и соседнего порта рядом, можно применить любую из двух. -->
  <PortConflictModal
    v-if="activeConflict && conflictRow"
    :row="conflictRow"
    :conflict="rowConflict(conflictRow)"
    :kind="activeConflict.kind"
    :applying="applyingConflict"
    @close="closeConflict"
    @apply-neighbor="applyNeighborConfig"
    @apply-current="applyCurrentConfigToNeighbor"
  />

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

<style scoped src="../styles/interfaceTable.css"></style>
<style scoped src="../styles/interfaceCellInput.css"></style>
<style scoped src="../styles/interfaceVlanControls.css"></style>
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
/* Панель массового редактирования — первая строка той же <table class="iface-table"> (InterfaceBulkBar.vue), а не отдельная
   flex-панель; общая рамка — .iface-panel. */
.iface-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 10px;
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
/* Ячейки и колонки таблицы (td, .col-*) — styles/interfaceTable.css, общий с InterfaceBulkBar.vue. */
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

.conflict-icon-btn {
  border: none;
  background: transparent;
  padding: 0;
  display: inline-flex;
  cursor: pointer;
}
</style>
