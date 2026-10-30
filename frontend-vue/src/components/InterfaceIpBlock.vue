<script setup lang="ts">
// Блок «IP-адреса интерфейса» раскрытой строки порта: список адрес / префикс / назначение. Список приходит свойством и уходит
// наверх целиком (update:ips) — родитель записывает его в порт; если IP порта задаёт группа портов, поля только для просмотра.
import type { InterfaceIpDraftRow } from '../api/types'

const props = defineProps<{
  ips: InterfaceIpDraftRow[]
  /** IP-адреса порта задаёт группа портов: поля только для просмотра. */
  managed: boolean
  /** Подсказка о группе, показывается вместо кнопки добавления. */
  lockNote: string
}>()
const emit = defineEmits<{
  'update:ips': [ips: InterfaceIpDraftRow[]]
}>()

function addIp() {
  emit('update:ips', [...props.ips, { ip_address: '', prefix_length: '', purpose: '' }])
}

function removeIp(index: number) {
  emit(
    'update:ips',
    props.ips.filter((_, j) => j !== index),
  )
}

function updateIp(index: number, patch: Partial<InterfaceIpDraftRow>) {
  emit(
    'update:ips',
    props.ips.map((ip, j) => (j === index ? { ...ip, ...patch } : ip)),
  )
}
</script>

<template>
  <div class="ip-block">
    <div class="ip-head">
      <b>IP-адреса интерфейса</b>
      <span v-if="managed" class="group-lock">{{ lockNote }}</span>
      <button v-else type="button" class="btn btn-secondary" @click="addIp">
        <svg class="icon"><use href="/icons.svg#i-plus" /></svg>
        IP-адрес
      </button>
    </div>
    <div v-if="!ips.length" class="empty">IP-адреса не добавлены</div>
    <div v-for="(ip, j) in ips" :key="ip.id ?? j" class="ip-row">
      <input
        type="text"
        placeholder="IP-адрес"
        :value="ip.ip_address"
        :disabled="managed"
        @input="updateIp(j, { ip_address: ($event.target as HTMLInputElement).value })"
      />
      <input
        type="number"
        min="0"
        max="128"
        placeholder="Префикс"
        :value="ip.prefix_length"
        :disabled="managed"
        @input="updateIp(j, { prefix_length: ($event.target as HTMLInputElement).value })"
      />
      <input
        type="text"
        placeholder="Назначение"
        :value="ip.purpose"
        :disabled="managed"
        @input="updateIp(j, { purpose: ($event.target as HTMLInputElement).value })"
      />
      <button v-if="!managed" type="button" class="icon-btn danger" aria-label="Удалить IP интерфейса" @click="removeIp(j)">
        <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
      </button>
    </div>
  </div>
</template>

<style scoped src="../styles/interfaceEditorShared.css"></style>
<style scoped>
.ip-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ip-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ip-head b {
  font-size: 11.5px;
}
.ip-row {
  display: grid;
  grid-template-columns: 1.4fr 0.7fr 1.4fr auto;
  align-items: center;
  gap: 8px;
}
.ip-row input {
  background: var(--surface-1, var(--surface));
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 8px;
  font-size: 12px;
  color: var(--ink);
  width: 100%;
}

@media (max-width: 640px) {
  .ip-row {
    grid-template-columns: 1fr;
  }
}
</style>
