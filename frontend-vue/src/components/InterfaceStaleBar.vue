<script setup lang="ts">
// Плашка над списком портов: «Подинтерфейсов на VLAN, не назначенном устройству: N» с массовым переносом их на один VLAN
// устройства. Подинтерфейс молча не удаляется — на нём IP-адреса и открытые порты, — а сохранение с таким VLAN сервер отклонит.
// Сам перенос выполняет родитель (utils/subinterfaces.ts: moveStaleSubinterfaces): плашка только выбирает целевой VLAN.
import { computed, ref } from 'vue'
import type { VLANDefinition } from '../api/types'
import { vlanLabel } from '../utils/vlan'

const props = defineProps<{
  /** Сколько подинтерфейсов стоит на недоступных устройству VLAN. */
  count: number
  /** VLAN устройства — из них выбирается целевой. */
  vlanOptions: VLANDefinition[]
}>()
const emit = defineEmits<{
  /** Нажато «Перенести»: перенести все такие подинтерфейсы на этот VLAN. */
  move: [target: VLANDefinition]
}>()

const targetId = ref('')
const sortedVlanOptions = computed(() => [...props.vlanOptions].sort((a, b) => a.vlan_id - b.vlan_id))

function move() {
  const target = props.vlanOptions.find((v) => v.id === targetId.value)
  if (!target) return
  targetId.value = ''
  emit('move', target)
}
</script>

<template>
  <div class="stale-bulk" role="status">
    <span>Подинтерфейсов на VLAN, не назначенном устройству: {{ count }}.</span>
    <select v-model="targetId" aria-label="Перенести все такие подинтерфейсы на VLAN" :disabled="!vlanOptions.length">
      <option value="">Перенести все на VLAN…</option>
      <option v-for="v in sortedVlanOptions" :key="v.id" :value="v.id">{{ vlanLabel(v) }}</option>
    </select>
    <button type="button" class="btn btn-secondary" :disabled="!targetId" @click="move">Перенести</button>
  </div>
</template>

<style scoped>
.stale-bulk {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
  padding: 8px 10px;
  border: 1px solid var(--status-warn);
  border-radius: var(--r-s);
  font-size: 12px;
}
.stale-bulk select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 5px 8px;
  font-size: 12px;
  color: var(--ink);
  font-family: inherit;
}
</style>
