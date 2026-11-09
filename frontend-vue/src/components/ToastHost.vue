<script setup lang="ts">
import { computed } from 'vue'
import { useToast, type Toast } from '../composables/useToast'

const { toasts, dismiss } = useToast()

interface ToastGroup {
  key: string
  role: 'status' | 'alert'
  live: 'polite' | 'assertive'
  items: Toast[]
}

// Уведомления озвучиваются скринридером (WCAG 2.2, 4.1.3 «Status Messages»). Живая область должна существовать в DOM ДО появления
// сообщения, иначе часть скринридеров его не объявит, поэтому обе области рисуются всегда, даже пустыми. Ошибки — в «настойчивой»
// области (role="alert" прерывает чтение), остальное — в вежливой (role="status" ждёт паузы). aria-atomic="false": объявляется только
// добавленное уведомление, а не весь список заново.
const groups = computed<ToastGroup[]>(() => [
  { key: 'status', role: 'status', live: 'polite', items: toasts.filter((t) => t.type !== 'error') },
  { key: 'alert', role: 'alert', live: 'assertive', items: toasts.filter((t) => t.type === 'error') },
])

function runAction(toast: Toast) {
  dismiss(toast.id)
  toast.action?.run()
}
</script>

<template>
  <div class="toast-host">
    <div v-for="group in groups" :key="group.key" class="toast-list" :role="group.role" :aria-live="group.live" aria-atomic="false">
      <TransitionGroup name="toast">
        <div v-for="t in group.items" :key="t.id" class="toast" :class="t.type">
          <span>{{ t.message }}</span>
          <button v-if="t.action" type="button" class="toast-action" @click="runAction(t)">{{ t.action.label }}</button>
          <button type="button" aria-label="Закрыть" @click="dismiss(t.id)">×</button>
        </div>
      </TransitionGroup>
    </div>
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
  max-width: 360px;
}
/* Зазор между уведомлениями — внутри каждой области; между самими областями он нужен, только когда в верхней есть карточки, поэтому
   не `gap` у .toast-host: он оставлял бы 8 px пустоты рядом с пустой областью. */
.toast-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.toast-list + .toast-list > .toast:first-child {
  margin-top: 8px;
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
