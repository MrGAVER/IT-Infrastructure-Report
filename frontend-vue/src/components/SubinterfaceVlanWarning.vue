<script setup lang="ts">
// Предупреждение под строкой подинтерфейса, чей VLAN больше недоступен: снят с устройства либо не выбран на порту / не входит в VLAN
// группы. Строку не теряем молча — объясняем, что делать, и даём перенести подинтерфейс на свободный VLAN одним действием.
import type { VLANDefinition } from '../api/types'
import { vlanLabel } from '../utils/vlan'

defineProps<{
  reason: 'device' | 'owner'
  /** Подпись недоступного VLAN («10 — Серверы»); пусто, если VLAN нет и в справочнике. */
  vlanLabelText: string
  isGroup: boolean
  /** Слово для подсказки: «порта» или «группы». */
  ownerWord: string
  readonly: boolean
  freeVlans: VLANDefinition[]
}>()
const emit = defineEmits<{ move: [vlanId: string] }>()

// Список сразу возвращается в исходное положение: выбор — разовое действие, а не состояние строки.
function onMove(event: Event) {
  const select = event.target as HTMLSelectElement
  const vlanId = select.value
  select.value = ''
  if (vlanId) emit('move', vlanId)
}
</script>

<template>
  <div class="sub-warn" role="alert">
    <span v-if="reason === 'device'">
      VLAN этого подинтерфейса<template v-if="vlanLabelText"> ({{ vlanLabelText }})</template> больше не назначен устройству. Перенесите подинтерфейс на другой
      VLAN или удалите его — иначе сохранить не получится.
    </span>
    <span v-else>
      VLAN этого подинтерфейса<template v-if="vlanLabelText"> ({{ vlanLabelText }})</template>
      {{ isGroup ? 'не входит в VLAN группы' : 'не выбран на этом порту' }}. Перенесите подинтерфейс на другой VLAN или удалите его — иначе сохранить не
      получится.
    </span>
    <select
      v-if="!readonly"
      class="sub-move"
      aria-label="Перенести подинтерфейс на VLAN"
      :disabled="!freeVlans.length"
      :title="freeVlans.length ? undefined : `Нет свободных VLAN ${ownerWord} — выберите VLAN или удалите подинтерфейс`"
      @change="onMove"
    >
      <option value="">Перенести на VLAN…</option>
      <option v-for="v in freeVlans" :key="v.id" :value="v.id">{{ vlanLabel(v) }}</option>
    </select>
  </div>
</template>

<style scoped>
.sub-warn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px 12px;
  font-size: 11.5px;
  color: var(--status-crit);
}
.sub-move {
  background: var(--surface-2);
  border: 1px solid var(--status-crit);
  border-radius: var(--r-s);
  padding: 5px 8px;
  font-size: 12px;
  color: var(--ink);
  font-family: inherit;
}
</style>
