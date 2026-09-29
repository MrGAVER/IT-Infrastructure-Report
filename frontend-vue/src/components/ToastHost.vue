<script setup lang="ts">
import { useToast } from '../composables/useToast'

const { toasts, dismiss } = useToast()
</script>

<template>
  <div class="toast-host">
    <TransitionGroup name="toast">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type">
        <span>{{ t.message }}</span>
        <button type="button" aria-label="Закрыть" @click="dismiss(t.id)">×</button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 100;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 360px;
}
.toast {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--brand);
  border-radius: var(--r-m);
  padding: 11px 12px;
  font-size: 12.5px;
  color: var(--ink);
  box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.5);
}
.toast.success {
  border-left-color: var(--status-ok);
}
.toast.error {
  border-left-color: var(--status-crit);
}
.toast span {
  flex: 1;
  line-height: 1.5;
  /* Многострочные уведомления (напр. список портов с расхождением, utils/portConflicts.ts). */
  white-space: pre-line;
  white-space: pre-line;
}
.toast button {
  background: none;
  border: none;
  color: var(--ink-muted);
  font-size: 16px;
  line-height: 1;
  padding: 0;
}
.toast-enter-active,
.toast-leave-active {
  transition: all 0.2s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
