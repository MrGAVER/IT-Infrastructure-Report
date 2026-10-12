<script setup lang="ts">
// Назначение VLAN устройству (device-vlans) — в отличие от interface_vlans (см.
// DeviceInterfacesEditor.vue), не привязано к конкретному порту, а к устройству в целом.
// Портировано с loadDeviceVlanEditor()/saveDeviceVlans() в
// frontend/static/device-interfaces.js.
//
// СОЗНАТЕЛЬНО НЕ ПЕРЕНЕСЕНО: "Создать домен VLAN" и "Скопировать VLAN с другого устройства" —
// в vanilla-версии оба построены на нативных window.prompt(), что не вписывается в стиль этого
// интерфейса (все остальные формы — модалки/инлайн-поля, не браузерные prompt-диалоги), а
// сделать их прилично здесь — уже отдельная задача, не часть базового CRUD. Домены VLAN как
// таковые уже полностью управляются в новом UI через VLANDomainsPanel.vue (см. VLANsView.vue);
// не перенесены только эти два узкоспециализированных сценария быстрого доступа прямо из формы
// устройства, см. "Ещё не сделано" во frontend-vue/README.md.
import type { CatalogItem, DeviceMemberDomain, DeviceVlanDraftRow, VLANDefinition, VLANDomain } from '../api/types'
import { computed, ref } from 'vue'
import { vlanLabel } from '../utils/vlan'
import { DEFAULT_COLLAPSE_ROWS } from '../utils/collapseLimit'
import { useCollapsibleRows } from '../composables/useCollapsibleRows'
import {
  duplicateVlanRowIndexes,
  duplicateVlansMessage,
  sortDeviceVlanRows,
  sortVlanDefinitions,
  usedVlanIds,
  vlanOptionsForRow,
} from '../utils/deviceVlans'
import QuickAddButton from './QuickAddButton.vue'
import SearchableSelect from './SearchableSelect.vue'
import type { SearchableSelectOption } from './SearchableSelect.vue'

// Фикс п.2.2: "если устройство уже использует домен vlan, добавляемый vlan также автоматически
// должен быть в этом домене" — deviceDomainId передаётся родителем (DeviceFormModal.vue) только
// когда устройство состоит РОВНО в одном домене (Set с одним элементом): если доменов несколько
// или ни одного, однозначно предположить, какой из них имелся в виду, нельзя — тогда поле
// остаётся пустым, как раньше, и пользователь выбирает домен сам.
//
// joinableDomains — пункт 3 правки "домен VLAN": домены, в которые устройство ЕЩЁ не входит (ни
// сохранённым членством, ни уже отложенным до сохранения) — список уже отфильтрован родителем
// (DeviceFormModal.vue:joinableDomains), этому компоненту не нужно знать о членстве вообще, он
// только показывает то, что ему передали, и сообщает о выборе наружу.
//
// memberDomains — пункт 3 правки "включение в домен VLAN": домены, в которые устройство уже входит
// (pending: false) либо будет включено при сохранении формы (pending: true). Без этого списка после
// нажатия "Включить" в блоке ничего не менялось: домен просто пропадал из выпадающего списка, а
// факт включения виден был только после перезагрузки страницы (на экране доменов VLAN).
//
// collapseAfter — порог сворачивания блока: когда строк БОЛЬШЕ этого числа, список строк скрыт за
// кнопкой «Развернуть» (значение задаётся пользователем в «Настройках», родитель берёт его из
// stores/formPreferences.ts; сам редактор о сторе не знает).
const props = withDefaults(
  defineProps<{
    modelValue: DeviceVlanDraftRow[]
    vlanOptions: VLANDefinition[]
    // Полный справочник VLAN (без фильтра по домену устройства) — нужен только чтобы подписать УЖЕ
    // выбранный в строке VLAN, который фильтр vlanOptions скрыл (например, VLAN без домена,
    // назначенный до включения устройства в домен): иначе поле строки выглядело бы пустым, хотя
    // значение в черновике осталось. Не расширяет список выбора — см. rowOptions().
    allVlanDefinitions?: VLANDefinition[]
    deviceDomainId?: string | null
    joinableDomains?: VLANDomain[]
    memberDomains?: DeviceMemberDomain[]
    collapseAfter?: number
    // VLAN, значения которых заданы общей настройкой стека (id VLAN → причина). У такой строки IP-адрес, префикс,
    // «Управление» и сам VLAN не редактируются и строка не удаляется: меняется это в блоке общих настроек стека (сервер
    // тоже отклоняет такую правку). Пусто/не передано — устройство вне стека или настроек нет.
    lockedVlans?: Record<string, string>
  }>(),
  { collapseAfter: DEFAULT_COLLAPSE_ROWS },
)
// vlan-created: полный список VLAN (vlanOptions) собирается родителем из useVLANsStore(), а не
// из catalogs — generic QuickAddModal.vue пишет созданную запись только в catalogs.items['vlans'],
// поэтому родителю нужно узнать о создании и перезагрузить vlansStore (см. DeviceFormModal.vue),
// иначе только что заведённый VLAN пропадёт из этого же select'а сразу после выбора: у него не
// будет совпадающего <option> в vlanOptions, пока vlansStore не подтянет его самостоятельно.
// Полная запись (не просто факт создания) — родителю нужен её domain_id, чтобы при необходимости
// добавить устройство в участники этого домена (фикс п.1.3.8, см. комментарий в DeviceFormModal.vue).
// vlan-domain-created: пункт 3 правки "создание физического устройства" — если ВНУТРИ формы
// добавления VLAN пользователь вложенным "+" завёл ещё и НОВЫЙ Домен VLAN (см. domain_id в схеме
// 'vlans' в quickAdd/schema.ts), родителю нужно узнать об этом отдельно от самого VLAN, чтобы
// подставить текущее устройство источником синхронизации этого домена (см.
// DeviceFormModal.vue:onVlanDomainCreated) — то, что VLAN уже выбрал этот домен, тут не годится:
// пользователь мог выбрать и уже СУЩЕСТВУЮЩИЙ домен, трогать чужую настройку источника нельзя.
// join-domain: пункт 3 правки "домен VLAN" — прямой запрос "включить устройство в этот
// СУЩЕСТВУЮЩИЙ домен", без создания нового VLAN (в отличие от vlan-domain-created выше).
const emit = defineEmits<{
  'update:modelValue': [rows: DeviceVlanDraftRow[]]
  'vlan-created': [record: CatalogItem]
  'vlan-domain-created': [record: CatalogItem]
  'join-domain': [domainId: string]
  'cancel-join-domain': [domainId: string]
}>()

const selectedJoinDomainId = ref('')
function joinDomain() {
  if (!selectedJoinDomainId.value) return
  emit('join-domain', selectedJoinDomainId.value)
  selectedJoinDomainId.value = ''
}

// Справочник для сортировки строк и подписей: все определения VLAN (allVlanDefinitions), а если они не
// переданы — хотя бы доступные для выбора (vlanOptions).
const definitions = computed<VLANDefinition[]>(() => {
  const byId = new Map<string, VLANDefinition>()
  for (const d of props.vlanOptions) byId.set(d.id, d)
  for (const d of props.allVlanDefinitions ?? []) byId.set(d.id, d)
  return [...byId.values()]
})

// Правило «как у открытых портов»: уже добавленный VLAN повторно не предлагается, а список выбора
// упорядочен по номеру VLAN. Считается один раз на изменение черновика, а не на каждую строку.
const usedIds = computed(() => usedVlanIds(props.modelValue))
const sortedVlanOptions = computed(() => sortVlanDefinitions(props.vlanOptions))
// Все доступные VLAN уже добавлены — выбирать не из чего (подсказка вместо «Ничего не найдено»).
const allVlansTaken = computed(() => props.vlanOptions.length > 0 && props.vlanOptions.every((v) => usedIds.value.has(v.id)))

/** Опции SearchableSelect для строки: доступные VLAN БЕЗ уже выбранных в других строках, плюс сам
 * выбранный в этой строке VLAN, если фильтр домена его скрыл — чтобы не терять видимость уже
 * сделанного выбора. Другие строки такой "лишний" VLAN в своих опциях не получают. */
function rowOptions(row: DeviceVlanDraftRow): SearchableSelectOption[] {
  const options = vlanOptionsForRow(sortedVlanOptions.value, usedIds.value, row.vlan_id).map((v) => ({ value: v.id, label: vlanLabel(v) }))
  if (row.vlan_id && !options.some((o) => o.value === row.vlan_id)) {
    const selected = props.allVlanDefinitions?.find((v) => v.id === row.vlan_id)
    if (selected) options.unshift({ value: selected.id, label: vlanLabel(selected) })
  }
  return options
}

// Повторы подсвечиваются, а само сохранение блокирует форма-владелец (utils/deviceVlans.ts:duplicateVlansMessage).
const duplicateIndexes = computed(() => duplicateVlanRowIndexes(props.modelValue))
const duplicateMessage = computed(() => duplicateVlansMessage(props.modelValue, definitions.value))

// Сворачивание — общая логика с редактором открытых портов (composables/useCollapsibleRows.ts): свёрнуто,
// когда строк больше порога и пользователь не развернул блок вручную.
const { exceedsLimit, collapsed, expand, toggle, expandForAdd } = useCollapsibleRows(
  () => props.modelValue.length,
  () => props.collapseAfter,
)

const SUMMARY_LIMIT = 12
// Номера VLAN выбранных строк — краткая сводка вместо скрытого списка (по порядку строк).
const collapsedSummary = computed(() => {
  const byId = new Map(definitions.value.map((d) => [d.id, d]))
  const numbers = props.modelValue.filter((r) => r.vlan_id).map((r) => byId.get(r.vlan_id)?.vlan_id)
  const shown = numbers.slice(0, SUMMARY_LIMIT).map((n) => (n === undefined ? '?' : String(n)))
  return numbers.length > SUMMARY_LIMIT ? `${shown.join(', ')}, …` : shown.join(', ')
})

/** Развернуть блок — форма вызывает это, когда ошибка сохранения относится к скрытой строке. */
defineExpose({ expand })

function lockReason(row: DeviceVlanDraftRow): string | undefined {
  return row.vlan_id ? props.lockedVlans?.[row.vlan_id] : undefined
}
const lockedCount = computed(() => props.modelValue.filter((row) => lockReason(row)).length)

function emptyRow(): DeviceVlanDraftRow {
  return { vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' }
}

// Список упорядочивается по номеру VLAN не в момент правки строки (иначе заполняемая строка «уезжала» бы
// из-под курсора), а когда пользователь добавляет следующую: заполненные строки встают по возрастанию,
// новая пустая — в конец. Как у открытых портов (OpenPortListEditor.vue:addRow).
function addRow() {
  expandForAdd() // пользователь работает со списком — новая строка не должна тут же скрыться из-за порога
  emit('update:modelValue', [...sortDeviceVlanRows(props.modelValue, definitions.value), emptyRow()])
}

function removeRow(index: number) {
  if (lockReason(props.modelValue[index])) return
  emit(
    'update:modelValue',
    props.modelValue.filter((_, i) => i !== index),
  )
}

function updateField(index: number, patch: Partial<DeviceVlanDraftRow>) {
  if (lockReason(props.modelValue[index])) return
  emit(
    'update:modelValue',
    props.modelValue.map((row, i) => (i === index ? { ...row, ...patch } : row)),
  )
}

function onVlanCreated(index: number, created: CatalogItem) {
  updateField(index, { vlan_id: created.id })
  emit('vlan-created', created)
}

function onNestedCreated(_fieldName: string, fkResource: string, record: CatalogItem) {
  if (fkResource === 'vlan-domains') emit('vlan-domain-created', record)
}
</script>

<template>
  <div class="nested-editor">
    <div class="nested-head">
      <div class="nested-title">
        <b>VLAN устройства</b>
        <span class="hint">VLAN может быть локальным для устройства или принадлежать общему домену. Один VLAN ID может иметь разные названия на разных устройствах.</span>
      </div>
      <!-- Кнопка видна только когда строк больше порога: иначе сворачивать нечего. -->
      <button
        v-if="exceedsLimit"
        type="button"
        class="btn btn-secondary collapse-toggle"
        :aria-expanded="!collapsed"
        data-testid="vlan-collapse-toggle"
        @click="toggle"
      >
        <svg class="icon chev" :class="{ open: !collapsed }"><use href="/icons.svg#i-chevd" /></svg>
        {{ collapsed ? `Развернуть (${modelValue.length})` : 'Свернуть' }}
      </button>
    </div>

    <div v-if="memberDomains && memberDomains.length" class="member-domains" data-testid="member-domains">
      <span class="member-domains-label">Домены VLAN:</span>
      <span v-for="d in memberDomains" :key="d.id" class="domain-chip" :class="{ pending: d.pending }" data-testid="member-domain">
        {{ d.name }}
        <em v-if="d.pending">— будет включено при сохранении</em>
        <button
          v-if="d.pending"
          type="button"
          class="chip-cancel"
          :aria-label="`Отменить включение в домен «${d.name}»`"
          :title="`Отменить включение в домен «${d.name}»`"
          data-testid="cancel-join-domain"
          @click="emit('cancel-join-domain', d.id)"
        >×</button>
      </span>
    </div>

    <div v-if="lockedCount" class="locked-note" data-testid="vlan-locked-note">
      VLAN, заданных общими настройками стека: {{ lockedCount }}. IP-адрес, префикс и «Управление» у них меняются в блоке общих настроек стека ниже.
    </div>

    <div v-if="!modelValue.length" class="empty">VLAN не назначены</div>

    <!-- Свёрнуто: вместо строк — сводка с номерами VLAN. -->
    <div v-else-if="collapsed" class="collapsed-summary" data-testid="vlan-collapsed">
      <span>Назначено VLAN: <b>{{ modelValue.length }}</b></span>
      <span v-if="collapsedSummary" class="summary-numbers" :title="collapsedSummary">{{ collapsedSummary }}</span>
      <span class="hint">Список свёрнут (порог — {{ collapseAfter }} строк, меняется в «Настройках»).</span>
    </div>

    <template v-else>
      <div
        v-for="(row, i) in modelValue"
        :key="row.id ?? i"
        class="nested-row"
        :class="{ 'row-duplicate': duplicateIndexes.has(i), 'row-locked': !!lockReason(row) }"
        :title="lockReason(row)"
        :data-locked="lockReason(row) ? 'true' : undefined"
      >
        <div class="col-vlan lookup-row">
          <SearchableSelect
            :model-value="row.vlan_id"
            :options="rowOptions(row)"
            placeholder="— VLAN —"
            :empty-text="allVlansTaken ? 'Все доступные VLAN уже добавлены' : undefined"
            :disabled="!!lockReason(row)"
            @update:model-value="(value) => updateField(i, { vlan_id: value })"
          />
          <QuickAddButton
            v-if="!lockReason(row)"
            resource="vlans"
            title="VLAN"
            :initial-values="deviceDomainId ? { domain_id: deviceDomainId } : undefined"
            @created="(r: CatalogItem) => onVlanCreated(i, r)"
            @nested-created="onNestedCreated"
          />
        </div>
        <input class="col-ip" type="text" placeholder="IP VLAN" :value="row.ip_address" :disabled="!!lockReason(row)" @input="updateField(i, { ip_address: ($event.target as HTMLInputElement).value })" />
        <input
          class="col-prefix"
          type="number"
          min="0"
          max="128"
          placeholder="Префикс"
          :value="row.prefix_length"
          :disabled="!!lockReason(row)"
          @input="updateField(i, { prefix_length: ($event.target as HTMLInputElement).value })"
        />
        <label class="col-mgmt">
          <input type="checkbox" :checked="row.is_management" :disabled="!!lockReason(row)" @change="updateField(i, { is_management: ($event.target as HTMLInputElement).checked })" />
          Управление
        </label>
        <button type="button" class="icon-btn danger" aria-label="Удалить VLAN" :disabled="!!lockReason(row)" @click="removeRow(i)">
          <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
        </button>
      </div>
    </template>

    <div v-if="duplicateMessage" class="dup-error" role="alert">{{ duplicateMessage }}</div>

    <button type="button" class="btn btn-secondary add-btn" @click="addRow">
      <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
      VLAN
    </button>

    <!-- Пункт 3 правки "домен VLAN": прямое включение устройства в уже существующий домен, без
         необходимости сперва заводить новый VLAN (в отличие от вложенного "+" у поля VLAN выше,
         которое присоединяет к домену лишь как побочный эффект). Раздел не показывается, если
         устройство уже состоит во всех существующих доменах (или доменов ещё нет вовсе) —
         joinableDomains тогда пуст. -->
    <div v-if="joinableDomains && joinableDomains.length" class="join-domain-row">
      <select v-model="selectedJoinDomainId">
        <option value="">— включить в домен —</option>
        <option v-for="d in joinableDomains" :key="d.id" :value="d.id">{{ d.name }}</option>
      </select>
      <button type="button" class="btn btn-secondary" :disabled="!selectedJoinDomainId" @click="joinDomain">Включить</button>
    </div>
  </div>
</template>

<style scoped>
.nested-editor {
  grid-column: 1 / -1;
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.nested-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.nested-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.collapse-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
  font-size: 12px;
  padding: 4px 9px;
}
.collapse-toggle .chev {
  transition: transform 0.15s;
}
.collapse-toggle .chev.open {
  transform: rotate(180deg);
}
.collapsed-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
  font-size: 12px;
  color: var(--ink);
  background: var(--surface-2);
  border: 1px dashed var(--border);
  border-radius: var(--r-s);
  padding: 7px 9px;
}
.summary-numbers {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-muted);
}
.row-duplicate :deep(.searchable-select input) {
  border-color: var(--status-crit);
}
.locked-note {
  font-size: 11.5px;
  color: var(--ink-muted);
  background: var(--surface-2);
  border: 1px dashed var(--border);
  border-radius: var(--r-s);
  padding: 7px 9px;
}
.row-locked input:disabled,
.row-locked :deep(.searchable-select input:disabled) {
  opacity: 0.65;
  cursor: not-allowed;
}
.dup-error {
  font-size: 11.5px;
  color: var(--status-crit);
}
.nested-head b {
  font-size: 12.5px;
}
.hint {
  font-size: 10.5px;
  color: var(--ink-muted);
}
.member-domains {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
}
.member-domains-label {
  color: var(--ink-muted);
}
.domain-chip {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 2px 9px;
  color: var(--ink);
}
.domain-chip.pending {
  border-style: dashed;
  border-color: var(--brand);
}
.chip-cancel {
  background: none;
  border: none;
  padding: 0 0 0 4px;
  margin: 0;
  color: var(--ink-muted);
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
}
.chip-cancel:hover {
  color: var(--status-crit);
}
.domain-chip em {
  font-style: normal;
  color: var(--ink-muted);
  font-size: 10.5px;
}
.empty {
  font-size: 12px;
  color: var(--ink-muted);
  padding: 4px 0;
}
.nested-row {
  display: grid;
  grid-template-columns: 1.6fr 1fr 0.7fr auto auto;
  align-items: center;
  gap: 8px;
}
.nested-row input,
.nested-row select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
  min-width: 0;
}
.col-vlan.lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.col-vlan.lookup-row .searchable-select {
  flex: 1;
  min-width: 0;
}
.col-mgmt {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  color: var(--ink-muted);
  white-space: nowrap;
}
.icon-btn.danger {
  color: var(--status-crit);
  border-color: transparent;
  background: transparent;
}
.icon-btn.danger:hover {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}
.add-btn {
  align-self: flex-start;
}
.join-domain-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 6px;
  border-top: 1px dashed var(--border);
}
.join-domain-row select {
  flex: 1;
  min-width: 0;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
}

@media (max-width: 700px) {
  .nested-row {
    grid-template-columns: 1fr;
  }
  .join-domain-row {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
