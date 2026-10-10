<script setup lang="ts">
// Редактор вложенного списка открытых портов/протоколов (OpenPort — полиморфная
// таблица, см. api/types.ts). Сознательно не знает про owner_type/owner_id и не
// обращается к API сам — те же причины, что в VmIpListEditor.vue. Благодаря этому
// один и тот же компонент уже сегодня закрывает ВМ (VMFormModal.vue) и без
// изменений годится для физических устройств, когда до них дойдёт очередь (см.
// "Ещё не сделано" в frontend-vue/README.md: "привязка ... открытых портов к
// устройству" — в vanilla-фронтенде это saveDeviceOpenPorts в vm-editors.js,
// почти дословно совпадающий с saveVMOpenPorts).
//
// Правка "убрать текстовые поля Порт/Протокол — эта информация уже есть в справочнике
// портов": раньше здесь были ещё два <input> (номер порта и протокол прикладного уровня),
// которые пользователь мог отредактировать вручную ПОСЛЕ выбора записи справочника — то
// самое "поле дублирует справочник и может с ним разойтись", убранное этой правкой. Теперь
// единственный вход — выбор записи (SearchableSelect ниже, фикс п.2 — сортировка и поиск
// вводом текста, как и у остальных подобных полей, см. catalogEntries prop и
// stores/catalogs.ts:sortProtocolPortCatalog), а сервер сам подставляет порт/протокол из
// справочника при сохранении (backend/app/services/crud.py:_apply_open_port_catalog) —
// хранить их в черновике смысла больше нет, см. OpenPortDraftRow в api/types.ts.
import { computed } from 'vue'
import type { OpenPortDraftRow, ProtocolPortCatalogEntry, CatalogItem } from '../api/types'
import { useUniquePortRows } from '../composables/useUniquePortRows'
import { useCollapsibleRows } from '../composables/useCollapsibleRows'
import QuickAddButton from './QuickAddButton.vue'
import SearchableSelect from './SearchableSelect.vue'
import type { SearchableSelectOption } from './SearchableSelect.vue'

// readonly — значения задаются не здесь, а извне (например, группой портов, см.
// utils/interfaceGroups.ts): все поля выключены, добавление/удаление скрыто.
// sortedUnique — правило «номера портов не повторяются и список упорядочен по номеру порта»:
// редактор подсвечивает повторы (само сохранение не блокирует — это делает форма-владелец через
// utils/openPorts.ts:duplicatePortNumbers) и упорядочивает строки по номеру порта, но НЕ в момент
// правки строки, а только когда пользователь добавляет следующий порт (кнопка «+ Открытый порт»,
// см. addRow) или заново открывает форму (загрузчики данных отдают уже отсортированный список).
// Иначе только что добавленная строка «уезжала» бы из-под курсора сразу после выбора записи
// справочника, и пользователю было бы неудобно заполнять её транспорт и описание.
// Выключено по умолчанию: порядок строк остаётся как ввёл пользователь.
// collapseAfter — порог сворачивания: когда строк БОЛЬШЕ этого числа, список скрыт за сводкой и кнопкой
// «Развернуть» (порог задаёт пользователь в «Настройках», родитель берёт его из stores/formPreferences.ts; сам
// редактор о сторе не знает). Не передан — сворачивания нет. Список с повторами портов не сворачивается:
// иначе подсветка повторов была бы скрыта.
const props = defineProps<{
  modelValue: OpenPortDraftRow[]
  catalogEntries: ProtocolPortCatalogEntry[]
  readonly?: boolean
  sortedUnique?: boolean
  collapseAfter?: number
}>()
const emit = defineEmits<{ 'update:modelValue': [rows: OpenPortDraftRow[]] }>()

const TRANSPORT_OPTIONS = ['TCP', 'UDP', 'TCP/UDP']

function emptyRow(): OpenPortDraftRow {
  return { protocol_catalog_id: '', transport_protocol: 'TCP', description: '' }
}

function catalogLabel(entry: ProtocolPortCatalogEntry): string {
  return `${entry.port} / ${entry.protocol_type}`
}

// catalogEntries приходит уже отсортированным (catalogs.protocolPortCatalog, см. фикс п.4.2 в
// stores/catalogs.ts) — здесь только маппинг в плоский формат SearchableSelect, без пересортировки,
// тем же принципом, что и у остальных select'ов, читающих catalogs.items[key] как есть.
const catalogOptions = (): SearchableSelectOption[] => props.catalogEntries.map((e) => ({ value: e.id, label: catalogLabel(e) }))

// Единственный момент, когда список упорядочивается по номеру порта: пользователь добавляет
// очередной порт. Уже заполненные строки встают по возрастанию, а новая пустая строка — в конец
// и остаётся там, пока пользователь её заполняет (выбор записи справочника, транспорт, описание
// порядок не меняют). sortOpenPortRows ставит строки без выбранной записи после выбранных.
// Сортировка и поиск повторов — общее правило с редактором протоколов ИС (composables/useUniquePortRows.ts).
const { duplicateIndexes, duplicateMessage, sortedForAdd } = useUniquePortRows(
  () => props.modelValue,
  () => props.catalogEntries,
  () => !!props.sortedUnique,
)

// Сворачивание — общая логика с блоком «VLAN устройства» (composables/useCollapsibleRows.ts).
const { exceedsLimit, collapsed: belowLimitCollapsed, toggle, expandForAdd } = useCollapsibleRows(
  () => props.modelValue.length,
  () => props.collapseAfter,
)
const collapsed = computed(() => belowLimitCollapsed.value && duplicateIndexes.value.size === 0)

const SUMMARY_LIMIT = 12
// Номера портов выбранных строк — краткая сводка вместо скрытого списка (по порядку строк).
const collapsedSummary = computed(() => {
  const portById = new Map(props.catalogEntries.map((e) => [e.id, e.port]))
  const ports = props.modelValue.filter((r) => r.protocol_catalog_id).map((r) => portById.get(r.protocol_catalog_id))
  const shown = ports.slice(0, SUMMARY_LIMIT).map((p) => (p === undefined ? '?' : String(p)))
  return ports.length > SUMMARY_LIMIT ? `${shown.join(', ')}, …` : shown.join(', ')
})

function addRow() {
  expandForAdd() // пользователь работает со списком — новая строка не должна тут же скрыться из-за порога
  emit('update:modelValue', [...sortedForAdd(), emptyRow()])
}

function removeRow(index: number) {
  emit(
    'update:modelValue',
    props.modelValue.filter((_, i) => i !== index),
  )
}

function updateField(index: number, patch: Partial<OpenPortDraftRow>) {
  const next = props.modelValue.map((row, i) => (i === index ? { ...row, ...patch } : row))
  emit('update:modelValue', next)
}

// Выбор (или снятие — catalogId === '', крестик очистки SearchableSelect) записи справочника.
// Явный сброс port/protocol здесь больше не нужен: их не осталось в OpenPortDraftRow вовсе —
// достаточно записать сам protocol_catalog_id, сервер выведет из него порт/протокол при сохранении.
// Порядок строк не меняется (см. addRow).
function onCatalogChange(index: number, catalogId: string) {
  updateField(index, { protocol_catalog_id: catalogId })
}

// Запись, только что созданная через быстрое добавление, подставляется в ту же строку, из которой
// вызвано добавление; порядок строк, как и при обычном выборе, не меняется.
function onQuickAdded(index: number, record: CatalogItem) {
  updateField(index, { protocol_catalog_id: record.id })
}
</script>

<template>
  <div class="nested-editor">
    <div class="nested-head">
      <div class="nested-title">
        <b>Открытые порты / протоколы</b>
        <span class="hint">Используются при заполнении соответствующего поля отчёта.</span>
      </div>
      <!-- Кнопка видна только когда строк больше порога: иначе сворачивать нечего. -->
      <button
        v-if="exceedsLimit"
        type="button"
        class="btn btn-secondary collapse-toggle"
        :aria-expanded="!collapsed"
        data-testid="ports-collapse-toggle"
        @click="toggle"
      >
        <svg class="icon chev" :class="{ open: !collapsed }"><use href="/icons.svg#i-chevd" /></svg>
        {{ collapsed ? `Развернуть (${modelValue.length})` : 'Свернуть' }}
      </button>
    </div>

    <div v-if="!modelValue.length" class="empty">Открытые порты не добавлены</div>

    <!-- Свёрнуто: вместо строк — сводка с номерами портов. -->
    <div v-else-if="collapsed" class="collapsed-summary" data-testid="ports-collapsed">
      <span>Открытых портов: <b>{{ modelValue.length }}</b></span>
      <span v-if="collapsedSummary" class="summary-numbers" :title="collapsedSummary">{{ collapsedSummary }}</span>
      <span class="hint">Список свёрнут (порог — {{ collapseAfter }} строк, меняется в «Настройках»).</span>
    </div>

    <template v-else>
      <div v-for="(row, i) in modelValue" :key="row.id ?? i" class="nested-row" :class="{ 'row-duplicate': duplicateIndexes.has(i) }">
        <div class="col-catalog lookup-row">
          <SearchableSelect
            :model-value="row.protocol_catalog_id"
            :options="catalogOptions()"
            placeholder="— справочник —"
            :disabled="readonly"
            @update:model-value="(v) => onCatalogChange(i, v)"
          />
          <QuickAddButton v-if="!readonly" resource="protocol-port-catalog" title="Протокол / порт" @created="(r) => onQuickAdded(i, r)" />
        </div>
        <select
          class="col-transport"
          title="Транспортный протокол (TCP/UDP) — отдельно от прикладного протокола, который несёт запись справочника слева"
          :value="row.transport_protocol"
          :disabled="readonly"
          @change="updateField(i, { transport_protocol: ($event.target as HTMLSelectElement).value })"
        >
          <option v-for="t in TRANSPORT_OPTIONS" :key="t" :value="t">{{ t }}</option>
        </select>
        <input
          class="col-desc"
          type="text"
          placeholder="Описание"
          :value="row.description"
          :disabled="readonly"
          @input="updateField(i, { description: ($event.target as HTMLInputElement).value })"
        />
        <button v-if="!readonly" type="button" class="icon-btn danger" aria-label="Удалить открытый порт" @click="removeRow(i)">
          <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
        </button>
      </div>
    </template>

    <div v-if="duplicateMessage" class="dup-error" role="alert">{{ duplicateMessage }}</div>

    <button v-if="!readonly" type="button" class="btn btn-secondary add-btn" @click="addRow">
      <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
      Открытый порт
    </button>
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
  margin-bottom: 2px;
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
.nested-row {
  display: grid;
  grid-template-columns: 1.8fr 0.9fr 1.3fr auto;
  align-items: center;
  gap: 8px;
}
.lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.lookup-row .searchable-select {
  flex: 1;
  min-width: 0;
}
.nested-row input,
.nested-row select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  width: 100%;
  font-family: inherit;
}
.row-duplicate :deep(.searchable-select input) {
  border-color: var(--status-crit);
}
.dup-error {
  font-size: 11.5px;
  color: var(--status-crit);
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

@media (max-width: 720px) {
  .nested-row {
    grid-template-columns: 1fr;
  }
}
</style>
