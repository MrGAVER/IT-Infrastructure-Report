<script setup lang="ts">
// Редактор вложенного списка открытых портов/протоколов (OpenPort — полиморфная
// таблица, см. api/types.ts). Сознательно не знает про owner_type/owner_id и не
// обращается к API сам — те же причины, что в VmIpListEditor.vue. Благодаря этому
// один и тот же компонент уже сегодня закрывает ВМ (VMFormModal.vue) и без
// изменений годится для физических устройств, когда до них дойдёт очередь (см.
// "Ещё не сделано" в frontend-vue/README.md: "привязка ... открытых портов к
// устройству" — в vanilla-фронтенде это saveDeviceOpenPorts в vm-editors.js,
// почти дословно совпадающий с saveVMOpenPorts).
import type { OpenPortDraftRow, ProtocolPortCatalogEntry } from '../api/types'

const props = defineProps<{ modelValue: OpenPortDraftRow[]; catalogEntries: ProtocolPortCatalogEntry[] }>()
const emit = defineEmits<{ 'update:modelValue': [rows: OpenPortDraftRow[]] }>()

const TRANSPORT_OPTIONS = ['TCP', 'UDP', 'TCP/UDP']

function emptyRow(): OpenPortDraftRow {
  return { protocol_catalog_id: '', port: '', protocol: '', transport_protocol: 'TCP', description: '' }
}

function catalogLabel(entry: ProtocolPortCatalogEntry): string {
  return `${entry.port} / ${entry.protocol_type}`
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

function updateField(index: number, patch: Partial<OpenPortDraftRow>) {
  const next = props.modelValue.map((row, i) => (i === index ? { ...row, ...patch } : row))
  emit('update:modelValue', next)
}

// Выбор записи справочника подставляет порт и протокол — как onVMOpenPortCatalogChanged()
// в vanilla-версии (frontend/static/vm-editors.js). Пользователь может отредактировать
// оба поля вручную после — справочник только ускоряет типичный случай.
function onCatalogChange(index: number, catalogId: string) {
  const entry = props.catalogEntries.find((e) => e.id === catalogId)
  updateField(index, {
    protocol_catalog_id: catalogId,
    ...(entry ? { port: String(entry.port), protocol: entry.protocol_type } : {}),
  })
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
      <select
        class="col-catalog"
        :value="row.protocol_catalog_id"
        @change="onCatalogChange(i, ($event.target as HTMLSelectElement).value)"
      >
        <option value="">— справочник —</option>
        <option v-for="entry in catalogEntries" :key="entry.id" :value="entry.id">{{ catalogLabel(entry) }}</option>
      </select>
      <input
        class="col-port"
        type="number"
        min="1"
        max="65535"
        placeholder="Порт"
        :value="row.port"
        @input="updateField(i, { port: ($event.target as HTMLInputElement).value })"
      />
      <input
        class="col-protocol"
        type="text"
        placeholder="Протокол"
        :value="row.protocol"
        @input="updateField(i, { protocol: ($event.target as HTMLInputElement).value })"
      />
      <select
        class="col-transport"
        :value="row.transport_protocol"
        @change="updateField(i, { transport_protocol: ($event.target as HTMLSelectElement).value })"
      >
        <option v-for="t in TRANSPORT_OPTIONS" :key="t" :value="t">{{ t }}</option>
      </select>
      <input
        class="col-desc"
        type="text"
        placeholder="Описание"
        :value="row.description"
        @input="updateField(i, { description: ($event.target as HTMLInputElement).value })"
      />
      <button type="button" class="icon-btn danger" aria-label="Удалить открытый порт" @click="removeRow(i)">
        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
      </button>
    </div>

    <button type="button" class="btn btn-secondary add-btn" @click="addRow">
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
  grid-template-columns: 1.3fr 0.7fr 1fr 0.9fr 1.3fr auto;
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
