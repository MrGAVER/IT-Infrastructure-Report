<script setup lang="ts">
// Редактор вложенного списка развёрнутых программных активов (1С, веб-сервер, файловый
// сервер, AD и т.п. — Лист 4 отчёта требует это поле у ВМ, но то же самое поле есть и у
// физического устройства, см. backend/app/models.py:DeviceSoftware/VMSoftware). Как и
// VmIpListEditor/OpenPortListEditor — контролируемый компонент, не знает о владельце
// (переиспользуется VMFormModal.vue и DeviceFormModal.vue без изменений).
import type { CatalogItem, SoftwareAssetDraftRow } from '../api/types'
import QuickAddButton from './QuickAddButton.vue'

const props = defineProps<{ modelValue: SoftwareAssetDraftRow[]; catalogEntries: CatalogItem[] }>()
const emit = defineEmits<{ 'update:modelValue': [rows: SoftwareAssetDraftRow[]] }>()

function emptyRow(): SoftwareAssetDraftRow {
  return { software_asset_id: '', version: '' }
}

function addRow() {
  emit('update:modelValue', [...props.modelValue, emptyRow()])
}

function removeRow(index: number) {
  emit(
    'update:modelValue',
    props.modelValue.filter((_, i) => i !== index),
  )
}

function updateField(index: number, patch: Partial<SoftwareAssetDraftRow>) {
  const next = props.modelValue.map((row, i) => (i === index ? { ...row, ...patch } : row))
  emit('update:modelValue', next)
}

// Id записи напрямую из уже полученного record — тот же приём и то же обоснование про тайминг
// реактивности пропа, что в OpenPortListEditor.vue:onQuickAdded.
function onQuickAdded(index: number, record: CatalogItem) {
  updateField(index, { software_asset_id: record.id })
}
</script>

<template>
  <div class="nested-editor">
    <div class="nested-head">
      <b>Программные активы</b>
      <span class="hint">1С, веб-сервер, файловый сервер, AD и т. п. — используется в отчёте.</span>
    </div>

    <div v-if="!modelValue.length" class="empty">Программные активы не добавлены</div>

    <div v-for="(row, i) in modelValue" :key="row.id ?? i" class="nested-row">
      <div class="col-asset lookup-row">
        <select
          :value="row.software_asset_id"
          @change="updateField(i, { software_asset_id: ($event.target as HTMLSelectElement).value })"
        >
          <option value="">— выберите ПО —</option>
          <option v-for="entry in catalogEntries" :key="entry.id" :value="entry.id">{{ entry.name }}</option>
        </select>
        <QuickAddButton resource="software-assets" title="Программный актив" @created="(r) => onQuickAdded(i, r)" />
      </div>
      <input
        class="col-version"
        type="text"
        placeholder="Версия"
        :value="row.version"
        @input="updateField(i, { version: ($event.target as HTMLInputElement).value })"
      />
      <button type="button" class="icon-btn danger" aria-label="Удалить программный актив" @click="removeRow(i)">
        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
      </button>
    </div>

    <button type="button" class="btn btn-secondary add-btn" @click="addRow">
      <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
      Программный актив
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
  grid-template-columns: 2fr 1fr auto;
  align-items: center;
  gap: 8px;
}
.lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.lookup-row select {
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

@media (max-width: 560px) {
  .nested-row {
    grid-template-columns: 1fr;
  }
}
</style>
