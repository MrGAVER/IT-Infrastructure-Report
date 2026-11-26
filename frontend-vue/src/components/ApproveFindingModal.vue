<script setup lang="ts">
// Окно одобрения проблемы (или нескольких сразу) в проверке данных (ConsistencyView.vue): человек признаёт находки допустимыми и по желанию
// объясняет, почему. Само ничего не отправляет: комментарий отдаётся родителю событием confirm, а родитель закрывает окно после ответа.
import { computed, ref } from 'vue'
import { MAX_APPROVAL_COMMENT_LENGTH } from '../api/consistency'
import type { ConsistencyFinding } from '../api/consistency'
import { pluralRu } from '../utils/plural'
import BaseModal from './BaseModal.vue'

const props = defineProps<{ findings: ConsistencyFinding[]; busy: boolean }>()
const emit = defineEmits<{ close: []; confirm: [comment: string | null] }>()

const comment = ref('')
const many = computed(() => props.findings.length > 1)
// В списке — первые проблемы, остальные числом: окно не должно вырастать на сотни строк.
const SHOWN = 5
const shown = computed(() => props.findings.slice(0, SHOWN))
const hidden = computed(() => Math.max(0, props.findings.length - SHOWN))
const count = computed(() => `${props.findings.length} ${pluralRu(props.findings.length, ['проблему', 'проблемы', 'проблем'])}`)
</script>

<template>
  <BaseModal align="center" @close="emit('close')">
    <div class="approve-modal card" role="dialog" aria-modal="true" :aria-label="many ? 'Одобрение проблем' : 'Одобрение проблемы'">
      <div class="modal-head">
        <h2>{{ many ? `Одобрить ${count}?` : 'Одобрить проблему?' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <p v-if="!many" class="problem">{{ findings[0].message }}</p>
      <template v-else>
        <p class="scope">Будут одобрены все найденные проблемы, подходящие под текущие фильтры, а не только показанные на этой странице.</p>
        <ul class="problems">
          <li v-for="item in shown" :key="item.fingerprint">{{ item.message }}</li>
          <li v-if="hidden > 0" class="more">и ещё {{ hidden }}</li>
        </ul>
      </template>
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
        <button type="button" class="btn btn-primary" :disabled="busy" @click="emit('confirm', comment.trim() || null)">
          {{ many ? `Одобрить все (${findings.length})` : 'Одобрить' }}
        </button>
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
.scope {
  margin: 0 0 8px;
  font-size: 12.5px;
  font-weight: 600;
}
.problems {
  margin: 0 0 10px;
  padding-left: 18px;
  font-size: 12.5px;
}
.problems .more {
  color: var(--ink-muted);
  list-style: none;
  margin-left: -18px;
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
