<script setup lang="ts">
// Окно одобрения проблемы проверки данных (ConsistencyView.vue): человек признаёт находку допустимой и по желанию объясняет, почему.
// Само ничего не отправляет: комментарий отдаётся родителю событием confirm, а родитель закрывает окно после успешного ответа.
import { ref } from 'vue'
import { MAX_APPROVAL_COMMENT_LENGTH } from '../api/consistency'
import type { ConsistencyFinding } from '../api/consistency'
import BaseModal from './BaseModal.vue'

defineProps<{ finding: ConsistencyFinding; busy: boolean }>()
const emit = defineEmits<{ close: []; confirm: [comment: string | null] }>()

const comment = ref('')
</script>

<template>
  <BaseModal align="center" @close="emit('close')">
    <div class="approve-modal card" role="dialog" aria-modal="true" aria-label="Одобрение проблемы">
      <div class="modal-head">
        <h2>Одобрить проблему?</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <p class="problem">{{ finding.message }}</p>
      <p class="hint">
        Проблема перестанет требовать внимания. Одобрение действует, пока она остаётся такой же: если изменится (например, адрес появится у ещё одного
        устройства), она вернётся в список.
      </p>
      <label class="comment-label" for="approve-comment">Комментарий — почему это допустимо (необязательно)</label>
      <textarea
        id="approve-comment"
        v-model="comment"
        rows="3"
        :maxlength="MAX_APPROVAL_COMMENT_LENGTH"
        placeholder="Например: общий виртуальный адрес VRRP"
      ></textarea>
      <div class="actions">
        <button type="button" class="btn btn-secondary" :disabled="busy" @click="emit('close')">Отмена</button>
        <button type="button" class="btn btn-primary" :disabled="busy" @click="emit('confirm', comment.trim() || null)">Одобрить</button>
      </div>
    </div>
  </BaseModal>
</template>

<style scoped>
.approve-modal {
  width: 100%;
  max-width: 480px;
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
.problem {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 500;
}
.hint {
  margin: 0 0 14px;
  font-size: 12px;
  color: var(--ink-muted);
}
.comment-label {
  display: block;
  margin-bottom: 6px;
  font-size: 12px;
  color: var(--ink-muted);
}
textarea {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 8px 10px;
  color: var(--ink);
  font: inherit;
  font-size: 12.5px;
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
</style>
