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
import type { CatalogItem, InterfaceDraftRow, InterfaceGroupDraft, PortConflictInfo, ProtocolPortCatalogEntry, VLANDefinition } from '../api/types'
import { useToast } from '../composables/useToast'
import { useBulkEdit } from '../composables/useBulkEdit'
import { useGroupLocks } from '../composables/useGroupLocks'
import { useInterfaceRows } from '../composables/useInterfaceRows'
import { useNeighborSync } from '../composables/useNeighborSync'
import { usePortGenerator } from '../composables/usePortGenerator'
import { usePreSaveReview } from '../composables/usePreSaveReview'
import { useRowUiState } from '../composables/useRowUiState'
import { useVlanSelection } from '../composables/useVlanSelection'
import { freedPeerIds as computeFreedPeerIds } from '../utils/interfacePeers'
import { moveStaleMessage, moveStaleSubinterfaces, staleSubinterfaces } from '../utils/subinterfaces'
import { isAllVlansSelected } from '../utils/allVlans'
import { newRowKey, type ConnectionBaseline } from '../utils/interfaceConnections'
import InterfaceGroupsPanel from './InterfaceGroupsPanel.vue'
import AllVlansChoiceModal from './AllVlansChoiceModal.vue'
import BulkVlanPickerModal from './BulkVlanPickerModal.vue'
import InterfaceBulkBar from './InterfaceBulkBar.vue'
import InterfaceGeneratorPanel from './InterfaceGeneratorPanel.vue'
import InterfaceRow from './InterfaceRow.vue'
import InterfaceStaleBar from './InterfaceStaleBar.vue'
import NeighborReviewModal from './NeighborReviewModal.vue'
import PortConflictModal from './PortConflictModal.vue'
import PortVlanPickerModal from './PortVlanPickerModal.vue'
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
const { rowManaged, groupLockNote } = useGroupLocks(() => props.groups)

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
</script>

<template>
  <div ref="rootEl" class="nested-editor">
    <div class="nested-head">
      <b>Порты / интерфейсы</b>
      <span class="hint">Управление отмечается на одном или нескольких интерфейсах — все их IP считаются IP управления.</span>
    </div>

    <InterfaceStaleBar v-if="staleSubinterfaceCount" :count="staleSubinterfaceCount" :vlan-options="vlanOptions" @move="moveAllStaleSubinterfaces" />

    <InterfaceGeneratorPanel
      v-model:count="genCount"
      v-model:start-at="genStartAt"
      v-model:name-template="genNameTemplate"
      v-model:type-id="genTypeId"
      v-model:speed-id="genSpeedId"
      v-model:replace-all="replaceAllPorts"
      :type-options="typeOptions"
      :speed-options="speedOptions"
      @generate="applyGenerator"
    />

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
          <InterfaceRow
            v-for="(row, i) in modelValue"
            :key="row.id ?? row.key ?? i"
            :row="row"
            :index="i"
            :rows="modelValue"
            :groups="groups"
            :selected="selectedIndices.has(i)"
            :expanded="expandedIndices.has(i)"
            :copy-target="copyTargetIndex[i] ?? ''"
            :type-options="typeOptions"
            :speed-options="speedOptions"
            :vlan-options="vlanOptions"
            :vlan-catalog="knownVlans"
            :allowed-vlan-ids="allowedVlanIds"
            :protocol-port-catalog="protocolPortCatalog"
            :collapse-after="formPreferences.collapseRows"
            :conflict="rowConflict(row)"
            :edit-connections="editConnections"
            :device-id="deviceId"
            :device-label="deviceLabel"
            :freed-peer-ids="freedPeerIds"
            :applying-peer-config="applyingPeerConfig"
            :peers-version="peersVersion"
            @select="(checked) => toggleSelect(i, checked)"
            @toggle-expand="toggleExpand(i)"
            @move="(delta) => moveRowBy(i, delta)"
            @remove="removeRow(i)"
            @rename="(name) => renamePort(i, name)"
            @update="(patch) => updateRow(i, patch)"
            @open-conflict="(kind) => openConflict(i, kind)"
            @set-vlan-mode="(mode) => setVlanMode(i, mode)"
            @set-access-vlan="(vlanId) => setAccessVlan(i, vlanId)"
            @toggle-all-vlans="(checked) => toggleAllVlans(i, checked)"
            @open-vlan-picker="vlanPickerIndex = i"
            @set-copy-target="(value) => setCopyTarget(i, value)"
            @apply-copy="applyCopyPorts(i)"
            @apply-peer-config="(peer, kinds) => applyPeerConfigToPort(i, peer, kinds)"
            @apply-config-to-peer="(peer, kinds) => applyPortConfigToPeer(i, peer, kinds)"
          />
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
<style scoped src="../styles/interfaceEditorShared.css"></style>
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
</style>
