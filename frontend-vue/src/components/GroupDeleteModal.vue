<script setup lang="ts">
// Окно удаления группы портов (InterfaceGroupsPanel.vue): что сделать со значениями, которые группа записала в порты, —
// оставить их или стереть. Само ничего не удаляет: выбор отдаётся родителю событием confirm.
import { computed } from 'vue'
import type { InterfaceGroupDraft } from '../api/types'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { managedFields } from '../utils/interfaceGroups'

const props = defineProps<{
  group: InterfaceGroupDraft
  /** Сколько портов входит в группу. */
  membersCount: number
}>()
const emit = defineEmits<{ close: []; confirm: [choice: 'keep' | 'erase'] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

/** Чем управляла группа — списком через запятую («режим порта и VLAN, IP-адрес, …»). */
const managedText = computed(() => {
  const m = managedFields(props.group)
  return [m.vlan && 'режим порта и VLAN', m.ip && 'IP-адрес', m.openPorts && 'открытые порты', m.subinterfaces && 'подинтерфейсы'].filter(Boolean).join(', ')
})
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="delete-modal card" role="dialog" aria-modal="true" aria-label="Удаление группы портов">
      <div class="modal-head">
        <h2>Удалить группу «{{ group.name }}»?</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <p class="delete-desc">В группе портов: {{ membersCount }}. Группа задавала: {{ managedText }}. Что сделать со значениями в этих портах?</p>
      <div class="delete-actions">
        <button type="button" class="btn btn-primary" @click="emit('confirm', 'keep')">Оставить значения в портах</button>
        <button type="button" class="btn btn-danger danger-btn" @click="emit('confirm', 'erase')">Стереть значения</button>
        <button type="button" class="btn btn-secondary" @click="emit('close')">Отмена</button>
      </div>
    </div>
  </div>
</template>

<style scoped src="../styles/groupModal.css"></style>
<style scoped>
.delete-modal {
  width: 100%;
  padding: 20px 22px 18px;
  max-width: 440px;
}
.delete-desc {
  font-size: 12px;
  color: var(--ink-muted);
  margin: 0 0 14px;
}
.delete-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.delete-actions .btn {
  width: 100%;
  justify-content: center;
}
.btn-danger {
  background: transparent;
  border: 1px solid var(--status-crit);
  color: var(--status-crit);
}
.btn-danger:hover:not(:disabled) {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}
</style>
