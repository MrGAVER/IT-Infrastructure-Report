<script setup lang="ts">
import { useId } from 'vue'
// Окно выбора VLAN для массового редактирования портов: список VLAN вынесен из ячейки таблицы во всплывающее окно со своей
// внутренней прокруткой (а не растягивающийся список в ячейке). Отмеченные VLAN хранит useBulkEdit — окно только показывает их
// и сообщает о кликах.
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import type { VLANDefinition } from '../api/types'
import { vlanLabel } from '../utils/vlan'

defineProps<{
  vlanOptions: VLANDefinition[]
  /** Режим порта панели: галочка «Все VLAN» показывается только при Trunk — для access (не более одного VLAN) она не имеет смысла. */
  vlanMode: string
  allVlans: boolean
  selectedIds: Set<string>
}>()
const emit = defineEmits<{
  close: []
  'toggle-all': [checked: boolean]
  'toggle-vlan': [vlanId: string, checked: boolean]
}>()

const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))
// Доступное имя диалога — его заголовок (UI-04): скринридер озвучивает название при открытии окна.
const titleId = useId()
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="vlan-picker-modal card" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <div class="conflict-modal-head">
        <h3 :id="titleId">Выбор VLAN — массовое редактирование</h3>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <div class="vlan-checks vlan-picker-list">
        <label v-if="vlanMode === 'trunk'" class="vlan-check vlan-check-all">
          <input type="checkbox" :checked="allVlans" @change="emit('toggle-all', ($event.target as HTMLInputElement).checked)" />
          <b>Все VLAN</b>
        </label>
        <label v-for="v in vlanOptions" :key="v.id" class="vlan-check">
          <input type="checkbox" :checked="selectedIds.has(v.id)" @change="emit('toggle-vlan', v.id, ($event.target as HTMLInputElement).checked)" />
          {{ vlanLabel(v) }}
        </label>
      </div>
      <div class="conflict-modal-actions">
        <button type="button" class="btn btn-primary" @click="emit('close')">Готово</button>
      </div>
    </div>
  </div>
</template>

<style scoped src="../styles/interfaceModal.css"></style>
<style scoped src="../styles/interfaceVlanControls.css"></style>
<style scoped>
.vlan-picker-modal {
  width: 100%;
  max-width: 360px;
  padding: 18px 20px 16px;
  display: flex;
  flex-direction: column;
  max-height: 80vh;
}
.vlan-picker-list {
  overflow-y: auto;
  margin-bottom: 14px;
}
.vlan-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
}
</style>
