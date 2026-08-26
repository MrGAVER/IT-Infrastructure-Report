<script setup lang="ts">
// Назначение VLAN устройству (device-vlans) — в отличие от interface_vlans (см.
// DeviceInterfacesEditor.vue), не привязано к конкретному порту, а к устройству в целом.
// Портировано с loadDeviceVlanEditor()/saveDeviceVlans() в
// frontend/static/device-interfaces.js.
//
// СОЗНАТЕЛЬНО НЕ ПЕРЕНЕСЕНО: "Создать домен VLAN" и "Скопировать VLAN с другого устройства" —
// в vanilla-версии оба построены на нативных window.prompt(), что не вписывается в стиль этого
// интерфейса (все остальные формы — модалки/инлайн-поля, не браузерные prompt-диалоги), а
// сделать их прилично здесь — уже отдельная задача, не часть базового CRUD. Домены VLAN
// по-прежнему управляются только через /legacy, см. "Ещё не сделано" во frontend-vue/README.md.
import type { DeviceVlanDraftRow, VLANDefinition } from '../api/types'

const props = defineProps<{ modelValue: DeviceVlanDraftRow[]; vlanOptions: VLANDefinition[] }>()
const emit = defineEmits<{ 'update:modelValue': [rows: DeviceVlanDraftRow[]] }>()

function vlanLabel(v: VLANDefinition): string {
  return v.domain_name ? `${v.vlan_id} — ${v.name} [${v.domain_name}]` : `${v.vlan_id} — ${v.name}`
}

function emptyRow(): DeviceVlanDraftRow {
  return { vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' }
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

function updateField(index: number, patch: Partial<DeviceVlanDraftRow>) {
  emit(
    'update:modelValue',
    props.modelValue.map((row, i) => (i === index ? { ...row, ...patch } : row)),
  )
}
</script>

<template>
  <div class="nested-editor">
    <div class="nested-head">
      <b>VLAN устройства</b>
      <span class="hint">VLAN может быть локальным для устройства или принадлежать общему домену. Один VLAN ID может иметь разные названия на разных устройствах.</span>
    </div>

    <div v-if="!modelValue.length" class="empty">VLAN не назначены</div>

    <div v-for="(row, i) in modelValue" :key="row.id ?? i" class="nested-row">
      <select class="col-vlan" :value="row.vlan_id" @change="updateField(i, { vlan_id: ($event.target as HTMLSelectElement).value })">
        <option value="">— VLAN —</option>
        <option v-for="v in vlanOptions" :key="v.id" :value="v.id">{{ vlanLabel(v) }}</option>
      </select>
      <input class="col-ip" type="text" placeholder="IP VLAN" :value="row.ip_address" @input="updateField(i, { ip_address: ($event.target as HTMLInputElement).value })" />
      <input
        class="col-prefix"
        type="number"
        min="0"
        max="128"
        placeholder="Префикс"
        :value="row.prefix_length"
        @input="updateField(i, { prefix_length: ($event.target as HTMLInputElement).value })"
      />
      <label class="col-mgmt">
        <input type="checkbox" :checked="row.is_management" @change="updateField(i, { is_management: ($event.target as HTMLInputElement).checked })" />
        Управление
      </label>
      <button type="button" class="icon-btn danger" aria-label="Удалить VLAN" @click="removeRow(i)">
        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
      </button>
    </div>

    <button type="button" class="btn btn-secondary add-btn" @click="addRow">
      <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
      VLAN
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

@media (max-width: 700px) {
  .nested-row {
    grid-template-columns: 1fr;
  }
}
</style>
