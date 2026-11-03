<script setup lang="ts">
import { computed, reactive, ref, watch, useId } from 'vue'
import { createResource, updateResource } from '../api/client'
import type { Room } from '../api/types'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { useReadOnlyForm } from '../composables/useReadOnlyForm'

// Роль без права записи (viewer) видит карточку в режиме просмотра: поля отключены, кнопки «Сохранить» нет.
const { readOnly } = useReadOnlyForm()

const props = defineProps<{ room: Room | null; buildingId: string }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))
// Доступное имя диалога — его заголовок (UI-04): скринридер озвучивает название при открытии окна.
const titleId = useId()

const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.room !== null)

const form = reactive({ name: '' })

watch(
  () => props.room,
  (r) => {
    form.name = r?.name ?? ''
  },
  { immediate: true },
)

async function submit() {
  if (readOnly.value) return
  errorMessage.value = null
  if (!form.name.trim()) {
    errorMessage.value = 'Укажите наименование помещения.'
    return
  }
  saving.value = true
  try {
    const payload = { name: form.name.trim(), building_id: props.buildingId }
    if (isEdit.value) await updateResource('rooms', props.room!.id, payload)
    else await createResource('rooms', payload)
    emit('saved')
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить помещение'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <div class="modal-head">
        <h2 :id="titleId">{{ isEdit ? 'Редактировать помещение' : 'Добавить помещение' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>
      <fieldset class="readonly-fieldset" :disabled="readOnly">
        <form @submit.prevent="submit">
          <label class="field">
            <span>Наименование *</span>
            <input v-model.trim="form.name" type="text" required maxlength="255" autofocus />
          </label>
        </form>
      </fieldset>
      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">{{ readOnly ? 'Закрыть' : 'Отмена' }}</button>
        <button v-if="!readOnly" type="button" class="btn btn-primary" :disabled="saving" @click="submit">
          {{ saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Добавить' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 60;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
  overflow-y: auto;
}
.modal {
  width: 100%;
  max-width: 380px;
  padding: 20px 22px 18px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.modal-head h2 {
  font-family: var(--font-display);
  font-size: 16px;
  margin: 0;
}
.form-error {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
  color: var(--crit-ink);
  border-radius: var(--r-m);
  padding: 9px 12px;
  font-size: 12.5px;
  margin-bottom: 14px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-muted);
}
.field input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
  width: 100%;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
</style>
