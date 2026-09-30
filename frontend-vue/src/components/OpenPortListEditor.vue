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
import type { OpenPortDraftRow, ProtocolPortCatalogEntry, CatalogItem } from '../api/types'
import QuickAddButton from './QuickAddButton.vue'
import SearchableSelect from './SearchableSelect.vue'
import type { SearchableSelectOption } from './SearchableSelect.vue'

// readonly — значения задаются не здесь, а извне (например, группой портов, см.
// utils/interfaceGroups.ts): все поля выключены, добавление/удаление скрыто.
const props = defineProps<{ modelValue: OpenPortDraftRow[]; catalogEntries: ProtocolPortCatalogEntry[]; readonly?: boolean }>()
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

function addRow() {
  emit('update:modelValue', [...props.modelValue, emptyRow()])
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
function onCatalogChange(index: number, catalogId: string) {
  updateField(index, { protocol_catalog_id: catalogId })
}

function onQuickAdded(index: number, record: CatalogItem) {
  const entry = record as unknown as ProtocolPortCatalogEntry
  updateField(index, { protocol_catalog_id: entry.id })
}
</script>

<template>
  <div class="nested-editor">
    <div class="nested-head">
      <b>Открытые порты / протоколы</b>
      <span class="hint">Используются при заполнении соответствующего поля отчёта.</span>
    </div>

    <div v-if="!modelValue.length" class="empty">Открытые порты не добавлены</div>

    <div v-for="(row, i) in modelValue" :key="row.id ?? i" class="nested-row">
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
  flex-direction: column;
  gap: 2px;
  margin-bottom: 2px;
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
