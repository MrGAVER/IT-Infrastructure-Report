<script setup lang="ts">
// Обобщённый редактор вложенного списка "одна запись справочника на строку" — не знает, какой
// именно каталог и какое бэкенд-поле за ним стоит (передаются через props), поэтому один и тот
// же компонент используется для подразделений ИС (department_id) и мест размещения ИС
// (placement_asset_id) в InformationSystemFormModal.vue — обе связи имеют одинаковую форму.
import { computed } from 'vue'
import type { CatalogItem, CatalogPickerDraftRow } from '../api/types'
import QuickAddButton from './QuickAddButton.vue'
import SearchableSelect from './SearchableSelect.vue'
import type { SearchableSelectOption } from './SearchableSelect.vue'

const props = defineProps<{
  modelValue: CatalogPickerDraftRow[]
  catalogEntries: CatalogItem[]
  title: string
  placeholder: string
  addLabel: string
  /** Ключ ресурса для кнопки "+" быстрого добавления (quickAdd/schema.ts). Если не передан,
   * кнопка не показывается — не каждый вызывающий код обязан поддерживать быстрое добавление. */
  quickAddResource?: string
}>()
const emit = defineEmits<{ 'update:modelValue': [rows: CatalogPickerDraftRow[]] }>()

// Порядок записей — как пришёл от родителя (справочник уже отсортирован стором), здесь только
// маппинг в плоский формат SearchableSelect, чтобы список можно было фильтровать вводом текста.
const catalogOptions = computed<SearchableSelectOption[]>(() => props.catalogEntries.map((e) => ({ value: e.id, label: e.name as string })))

function addRow() {
  emit('update:modelValue', [...props.modelValue, { catalogId: '' }])
}

function removeRow(index: number) {
  emit(
    'update:modelValue',
    props.modelValue.filter((_, i) => i !== index),
  )
}

function updateRow(index: number, catalogId: string) {
  emit(
    'update:modelValue',
    props.modelValue.map((row, i) => (i === index ? { ...row, catalogId } : row)),
  )
}
</script>

<template>
  <div class="nested-editor">
    <div class="nested-head">
      <b>{{ title }}</b>
    </div>

    <div v-if="!modelValue.length" class="empty">Не добавлено</div>

    <div v-for="(row, i) in modelValue" :key="row.id ?? i" class="nested-row">
      <SearchableSelect :model-value="row.catalogId" :options="catalogOptions" :placeholder="placeholder" @update:model-value="(v) => updateRow(i, v)" />
      <QuickAddButton v-if="quickAddResource" :resource="quickAddResource" :title="addLabel" @created="(r) => updateRow(i, r.id)" />
      <button type="button" class="icon-btn danger" aria-label="Удалить" @click="removeRow(i)">
        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
      </button>
    </div>

    <button type="button" class="btn btn-secondary add-btn" @click="addRow">
      <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
      {{ addLabel }}
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
/* minmax(0, 1fr): без нулевого минимума длинная подпись выбранной записи распирала бы колонку
   шире модалки. SearchableSelect — обычный grid-item и сам растягивается на всю колонку. */
.nested-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 8px;
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
</style>
