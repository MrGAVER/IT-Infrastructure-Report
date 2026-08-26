<script setup lang="ts">
// Протоколы передачи данных ИС. protocol/port не показаны отдельными полями — подставляются
// из выбранной записи справочника (тот же protocol-port-catalog, что в OpenPortListEditor.vue),
// но обязаны уйти в payload при сохранении: ISProtocol.protocol — обязательное поле на бэкенде
// (см. комментарий к ISProtocolDraftRow в api/types.ts).
import type { ISProtocolDraftRow, ProtocolPortCatalogEntry } from '../api/types'

const props = defineProps<{ modelValue: ISProtocolDraftRow[]; catalogEntries: ProtocolPortCatalogEntry[] }>()
const emit = defineEmits<{ 'update:modelValue': [rows: ISProtocolDraftRow[]] }>()

function addRow() {
  emit('update:modelValue', [...props.modelValue, { protocol_catalog_id: '', protocol: '', port: null, description: '' }])
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
  const entry = props.catalogEntries.find((e) => e.id === catalogId)
  updateField(index, {
    protocol_catalog_id: catalogId,
    ...(entry ? { protocol: entry.protocol_type, port: entry.port } : {}),
  })
}
</script>

<template>
  <div class="nested-editor">
    <div class="nested-head">
      <b>Протоколы передачи данных</b>
    </div>

    <div v-if="!modelValue.length" class="empty">Не добавлено</div>

    <div v-for="(row, i) in modelValue" :key="row.id ?? i" class="nested-row">
      <select class="col-catalog" :value="row.protocol_catalog_id" @change="onCatalogChange(i, ($event.target as HTMLSelectElement).value)">
        <option value="">— протокол / порт —</option>
        <option v-for="entry in catalogEntries" :key="entry.id" :value="entry.id">{{ `${entry.port} / ${entry.protocol_type}` }}</option>
      </select>
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
.nested-row {
  display: grid;
  grid-template-columns: 1fr 1.6fr auto;
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
