<script setup lang="ts">
// Список общих IP-адресов группы портов (GroupEditModal.vue): адрес / префикс / назначение в строке, адресов может быть несколько.
// Список приходит свойством и уходит наверх целиком (update:modelValue). Пока адресов нет, показана одна пустая строка —
// «пусто — не задавать»: группа без единого адреса IP-адреса своих портов не трогает. Строка без адреса — плейсхолдер:
// назначение у неё недоступно (оно часть IP), а на сервер она не уходит (api/deviceInterfaces.ts).
import { computed } from 'vue'
import type { InterfaceIpDraftRow } from '../api/types'

const props = defineProps<{ modelValue: InterfaceIpDraftRow[] }>()
const emit = defineEmits<{ 'update:modelValue': [ips: InterfaceIpDraftRow[]] }>()

function emptyIp(): InterfaceIpDraftRow {
  return { ip_address: '', prefix_length: '', purpose: '' }
}

// Видимые строки: у группы без адресов — одна пустая (она появится в списке, только когда в неё что-то введут).
const rows = computed(() => (props.modelValue.length ? props.modelValue : [emptyIp()]))
// Единственная пустая строка удалять нечего.
const canRemove = (ip: InterfaceIpDraftRow) => rows.value.length > 1 || ip.ip_address.trim() !== '' || ip.prefix_length !== '' || ip.purpose !== ''

function addIp() {
  emit('update:modelValue', [...rows.value, emptyIp()])
}

function removeIp(index: number) {
  emit(
    'update:modelValue',
    rows.value.filter((_, j) => j !== index),
  )
}

function updateIp(index: number, patch: Partial<InterfaceIpDraftRow>) {
  emit(
    'update:modelValue',
    rows.value.map((ip, j) => (j === index ? { ...ip, ...patch } : ip)),
  )
}
</script>

<template>
  <div class="group-ips">
    <div v-for="(ip, j) in rows" :key="ip.id ?? j" class="ip-row">
      <input
        type="text"
        placeholder="IP-адрес (пусто — не задавать)"
        aria-label="Общий IP-адрес группы"
        :value="ip.ip_address"
        @input="updateIp(j, { ip_address: ($event.target as HTMLInputElement).value })"
      />
      <!-- Не v-model: на type="number" он записал бы в черновик число, а prefix_length везде в форме —
           строка (как у IP порта), и валидатор префикса вызывает у значения строковые методы. -->
      <input
        type="number"
        min="0"
        max="32"
        placeholder="Префикс"
        aria-label="Префикс общего IP-адреса"
        :value="ip.prefix_length"
        @input="updateIp(j, { prefix_length: ($event.target as HTMLInputElement).value })"
      />
      <input
        type="text"
        maxlength="255"
        placeholder="Назначение"
        aria-label="Назначение общего IP-адреса группы"
        :value="ip.purpose"
        :disabled="!ip.ip_address.trim()"
        :title="ip.ip_address.trim() ? undefined : 'Сначала укажите общий IP-адрес'"
        @input="updateIp(j, { purpose: ($event.target as HTMLInputElement).value })"
      />
      <button v-if="canRemove(ip)" type="button" class="icon-btn danger" aria-label="Удалить общий IP-адрес группы" @click="removeIp(j)">
        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
      </button>
      <span v-else class="ip-row-spacer" />
    </div>
    <div>
      <button type="button" class="btn btn-secondary" @click="addIp">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        IP-адрес
      </button>
    </div>
  </div>
</template>

<style scoped src="../styles/interfaceEditorShared.css"></style>
<style scoped>
.group-ips {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ip-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 120px minmax(0, 1fr) 28px;
  align-items: center;
  gap: 8px;
}
.ip-row input {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 8px;
  font-size: 12px;
  color: var(--ink);
}
.ip-row input:disabled {
  opacity: 0.6;
}

@media (max-width: 520px) {
  .ip-row {
    grid-template-columns: 1fr;
  }
}
</style>
