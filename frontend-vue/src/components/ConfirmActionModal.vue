<script setup lang="ts">
// Окно подтверждения действия над данными проверки (ConsistencyView.vue): заголовок, пояснение последствий и две кнопки. Само ничего не
// выполняет: подтверждение отдаётся родителю событием confirm, а родитель закрывает окно после ответа сервера.
import BaseModal from './BaseModal.vue'

defineProps<{ title: string; message: string; confirmLabel: string; busy: boolean }>()
const emit = defineEmits<{ close: []; confirm: [] }>()
</script>

<template>
  <BaseModal align="center" @close="emit('close')">
    <div class="confirm-modal card" role="dialog" aria-modal="true" :aria-label="title">
      <div class="modal-head">
        <h2>{{ title }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <p class="message">{{ message }}</p>
      <div class="actions">
        <button type="button" class="btn btn-secondary" :disabled="busy" @click="emit('close')">Отмена</button>
        <button type="button" class="btn btn-primary" :disabled="busy" @click="emit('confirm')">{{ confirmLabel }}</button>
      </div>
    </div>
  </BaseModal>
</template>

<style scoped>
.confirm-modal {
  width: 100%;
  max-width: 460px;
  padding: 20px 22px 18px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 14px;
}
.modal-head h2 {
  font-family: var(--font-display);
  font-size: 15px;
  margin: 0;
}
.message {
  margin: 0;
  font-size: 12.5px;
  color: var(--ink-muted);
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
</style>
