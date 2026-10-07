<script setup lang="ts">
// Протоколы передачи данных ИС. protocol_catalog_id — обязательная ссылка на справочник (тот же
// protocol-port-catalog, что в OpenPortListEditor.vue); protocol/port больше не отдельные поля ни
// в форме, ни в backend-модели (см. models.py, миграция b7f2c1e5a904) — их показывает
// SearchableSelect из caталога, а бэкенд резолвит их join'ом на каждое чтение.
import type { ISProtocolDraftRow, ProtocolPortCatalogEntry, CatalogItem } from '../api/types'
import QuickAddButton from './QuickAddButton.vue'
import SearchableSelect from './SearchableSelect.vue'
import type { SearchableSelectOption } from './SearchableSelect.vue'

const props = defineProps<{ modelValue: ISProtocolDraftRow[]; catalogEntries: ProtocolPortCatalogEntry[] }>()
const emit = defineEmits<{ 'update:modelValue': [rows: ISProtocolDraftRow[]] }>()

// catalogEntries приходит уже отсортированным (catalogs.protocolPortCatalog, см. фикс п.4.2 в
// stores/catalogs.ts) — здесь только маппинг в плоский формат SearchableSelect, без
// пересортировки, тем же приёмом, что и в OpenPortListEditor.vue для того же справочника.
const catalogOptions = (): SearchableSelectOption[] => props.catalogEntries.map((e) => ({ value: e.id, label: `${e.port} / ${e.protocol_type}` }))

function addRow() {
  emit('update:modelValue', [...props.modelValue, { protocol_catalog_id: '', description: '' }])
}

function removeRow(index: number) {
  emit(
    'update:modelValue',
    props.modelValue.filter((_, i) => i !== index),
  )
}

function updateField(index: number, patch: Partial<ISProtocolDraftRow>) {
  emit(
    'update:modelValue',
    props.modelValue.map((row, i) => (i === index ? { ...row, ...patch } : row)),
  )
}

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
      <b>Протоколы передачи данных</b>
    </div>

    <div v-if="!modelValue.length" class="empty">Не добавлено</div>

    <div v-for="(row, i) in modelValue" :key="row.id ?? i" class="nested-row">
      <div class="col-catalog lookup-row">
        <SearchableSelect
          :model-value="row.protocol_catalog_id"
          :options="catalogOptions()"
          placeholder="— протокол / порт —"
          @update:model-value="(v) => onCatalogChange(i, v)"
        />
        <QuickAddButton resource="protocol-port-catalog" title="Протокол / порт" @created="(r) => onQuickAdded(i, r)" />
      </div>
      <input
        class="col-desc"
        type="text"
        placeholder="Описание"
        :value="row.description"
        @input="updateField(i, { description: ($event.target as HTMLInputElement).value })"
      />
      <button type="button" class="icon-btn danger" aria-label="Удалить протокол" @click="removeRow(i)">
        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
      </button>
    </div>

    <button type="button" class="btn btn-secondary add-btn" @click="addRow">
      <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
      Протокол
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
.nested-head b {
  font-size: 12.5px;
}
.empty {
  font-size: 12px;
  color: var(--ink-muted);
  padding: 4px 0;
}
/* Строка: [протокол / порт] [+] [описание] [удалить]. Обёртка .lookup-row — display: contents,
   поэтому её дочерние элементы (SearchableSelect и кнопка «+») становятся ячейками этого же
   грида: две колонки minmax(0, 1fr) делят всё свободное место поровну, и «протокол / порт» и
   «Описание» получаются строго одной ширины на всю ширину модалки (кнопка «+» не отнимает
   ширину у селекта, как было бы при вложенном flex-контейнере). */
.nested-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}
.lookup-row {
  display: contents;
}
/* Размер и шрифт — как у input внутри SearchableSelect, чтобы поля совпадали и по высоте. */
.nested-row input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
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

/* Узкий экран: в первой строке селект, «+» и удаление, описание — на всю ширину второй строки. */
@media (max-width: 560px) {
  .nested-row {
    grid-template-columns: minmax(0, 1fr) auto auto;
  }
  .nested-row .col-desc {
    grid-column: 1 / -1;
    grid-row: 2;
  }
  .nested-row .icon-btn {
    grid-column: 3;
    grid-row: 1;
  }
}
</style>
