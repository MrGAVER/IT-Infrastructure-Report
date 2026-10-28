<script setup lang="ts">
// Редактор вложенного списка IP-адресов виртуальной машины (Лист 4: "IP-адрес
// виртуальной машины/контейнера" — у одной ВМ их может быть несколько). Строки
// живут в родителе (VMFormModal.vue) как VmIpDraftRow[] и передаются через
// v-model — сам список не знает о vm_id и не обращается к API, персистентность
// (создание/удаление через /resources/vm-ips) — забота вызывающего кода, ровно
// так же как saveVMIPs() отделён от рендеринга формы в vanilla-фронтенде
// (до 2.60.0).
import type { VmIpDraftRow } from '../api/types'

const props = defineProps<{ modelValue: VmIpDraftRow[] }>()
const emit = defineEmits<{ 'update:modelValue': [rows: VmIpDraftRow[]] }>()

function emptyRow(): VmIpDraftRow {
  return { ip_address: '', prefix_length: '', purpose: '', is_management: false }
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

function updateField(index: number, patch: Partial<VmIpDraftRow>) {
  const next = props.modelValue.map((row, i) => (i === index ? { ...row, ...patch } : row))
  emit('update:modelValue', next)
}
</script>

<template>
  <div class="nested-editor">
    <div class="nested-head">
      <b>IP-адреса виртуальной машины</b>
      <span class="hint">Отметьте один или несколько IP как «IP администрирования» — используется в отчёте по информационным системам.</span>
    </div>

    <div v-if="!modelValue.length" class="empty">IP-адреса не добавлены</div>

    <div v-for="(row, i) in modelValue" :key="row.id ?? i" class="nested-row">
      <input
        class="col-ip"
        type="text"
        placeholder="IP-адрес"
        :value="row.ip_address"
        @input="updateField(i, { ip_address: ($event.target as HTMLInputElement).value })"
      />
      <input
        class="col-prefix"
        type="number"
        min="0"
        max="128"
        placeholder="Префикс"
        :value="row.prefix_length"
        @input="updateField(i, { prefix_length: ($event.target as HTMLInputElement).value })"
      />
      <input
        class="col-purpose"
        type="text"
        placeholder="Назначение"
        :value="row.purpose"
        @input="updateField(i, { purpose: ($event.target as HTMLInputElement).value })"
      />
      <label class="col-mgmt">
        <input
          type="checkbox"
          :checked="row.is_management"
          @change="updateField(i, { is_management: ($event.target as HTMLInputElement).checked })"
        />
        IP администрирования
      </label>
      <button type="button" class="icon-btn danger" aria-label="Удалить IP-адрес" @click="removeRow(i)">
        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
      </button>
    </div>

    <button type="button" class="btn btn-secondary add-btn" @click="addRow">
      <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
      IP-адрес
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
  grid-template-columns: 1.4fr 0.7fr 1.4fr auto auto;
  align-items: center;
  gap: 8px;
}
.nested-row input[type='text'],
.nested-row input[type='number'] {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 8px;
  font-size: 12.5px;
  color: var(--ink);
  width: 100%;
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

@media (max-width: 640px) {
  .nested-row {
    grid-template-columns: 1fr;
  }
}
</style>
