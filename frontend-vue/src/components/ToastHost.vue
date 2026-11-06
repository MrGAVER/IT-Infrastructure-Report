<script setup lang="ts">
import { useToast, type Toast } from '../composables/useToast'

const { toasts, dismiss } = useToast()

function runAction(toast: Toast) {
  dismiss(toast.id)
  toast.action?.run()
}
</script>

<template>
  <div class="toast-host">
    <TransitionGroup name="toast">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type">
        <span>{{ t.message }}</span>
        <button v-if="t.action" type="button" class="toast-action" @click="runAction(t)">{{ t.action.label }}</button>
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
  z-index: var(--z-toast);
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
.toast.warning {
  border-left-color: var(--status-warn);
}
.toast span {
  flex: 1;
  line-height: 1.5;
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
.toast .toast-action {
  color: var(--brand);
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
  text-decoration: underline;
  cursor: pointer;
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
