<script setup lang="ts">
// Подтверждение добавления устройства в стек: у стека есть общие настройки VLAN, поэтому устройство получит их значения.
// Окно заранее показывает, что произойдёт с данными устройства — какие VLAN будут назначены и какие значения заменятся
// (было → станет); ничего не записывается, пока пользователь не подтвердит.
import { computed } from 'vue'
import type { StackMemberPreview } from '../api/types'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { describeMemberChange } from '../utils/stackVlans'

const props = defineProps<{ preview: StackMemberPreview; busy: boolean }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('cancel'))
const addedCount = computed(() => props.preview.changes.filter((c) => c.action === 'add').length)
const replacedCount = computed(() => props.preview.changes.filter((c) => c.action === 'update').length)
</script>

<template>
  <Teleport to="body">
    <div class="overlay" data-testid="stack-member-confirm" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
      <div class="dialog card" role="dialog" aria-modal="true">
        <h3>Добавить «{{ preview.device_name }}» в стек «{{ preview.stack_name }}»?</h3>
        <p class="lead">У стека заданы общие настройки VLAN — устройство получит их значения. Данные устройства изменятся так:</p>
        <p class="summary" data-testid="stack-member-confirm-summary">
          VLAN будет назначено: <b>{{ addedCount }}</b
          >, значений будет заменено: <b>{{ replacedCount }}</b
          ><template v-if="preview.unchanged_count">, уже совпадает: {{ preview.unchanged_count }}</template>
        </p>
        <table class="changes">
          <thead>
            <tr>
              <th>VLAN</th>
              <th>Что произойдёт</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in preview.changes" :key="c.vlan_id" :class="`action-${c.action}`" data-testid="stack-member-change">
              <td>{{ c.vlan_number }} — {{ c.vlan_name }}</td>
              <td>{{ describeMemberChange(c) }}</td>
            </tr>
          </tbody>
        </table>
        <div class="foot">
          <button type="button" class="btn btn-secondary" :disabled="busy" data-testid="stack-member-cancel" @click="emit('cancel')">Отказаться</button>
          <button type="button" class="btn btn-primary" :disabled="busy" data-testid="stack-member-accept" @click="emit('confirm')">
            {{ busy ? 'Добавление…' : 'Добавить в стек' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 80;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.dialog {
  width: 100%;
  max-width: 560px;
  max-height: 90vh;
  overflow-y: auto;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
h3 {
  font-family: var(--font-display);
  font-size: 15px;
  margin: 0;
}
.lead,
.summary {
  font-size: 12.5px;
  margin: 0;
}
.changes {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.changes th {
  text-align: left;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}
.changes td {
  padding: 7px 8px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
.action-update td:last-child {
  color: var(--status-warn);
}
.foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
</style>
