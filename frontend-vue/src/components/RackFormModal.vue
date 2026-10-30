<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { createResource, updateResource } from '../api/client'
import type { Rack } from '../api/types'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { useReadOnlyForm } from '../composables/useReadOnlyForm'

// Роль без права записи (viewer) видит карточку в режиме просмотра: поля отключены, кнопки «Сохранить» нет.
const { readOnly } = useReadOnlyForm()

const props = defineProps<{ rack: Rack | null; roomId: string }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.rack !== null)

const form = reactive({ name: '', height_u: '' })

watch(
  () => props.rack,
  (r) => {
    form.name = r?.name ?? ''
    form.height_u = r?.height_u != null ? String(r.height_u) : ''
  },
  { immediate: true },
)

async function submit() {
  if (readOnly.value) return
  errorMessage.value = null
  if (!form.name.trim()) {
    errorMessage.value = 'Укажите наименование стойки.'
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      room_id: props.roomId,
      height_u: form.height_u ? Number(form.height_u) : null,
    }
    if (isEdit.value) await updateResource('racks', props.rack!.id, payload)
    else await createResource('racks', payload)
    emit('saved')
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить стойку'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Редактировать стойку' : 'Добавить стойку' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>
      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>
      <fieldset class="readonly-fieldset" :disabled="readOnly">
        <form class="form-grid" @submit.prevent="submit">
          <label class="field">
            <span>Наименование *</span>
            <input v-model.trim="form.name" type="text" required maxlength="255" autofocus />
          </label>
          <label class="field">
            <span>Высота, U</span>
            <!-- Без .trim: на type="number" Vue и так приводит значение к числу при вводе
               (см. подробный комментарий в VLANFormModal.vue) — .trim здесь ничего не давал,
               кроме риска того же TypeError'а, если бы форма когда-нибудь начала звать
               .trim() на form.height_u, как раньше было с form.vlan_id в VLANFormModal.vue. -->
            <input v-model="form.height_u" type="number" min="1" max="60" />
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
  color: var(--status-crit);
  border-radius: var(--r-m);
  padding: 9px 12px;
  font-size: 12.5px;
  margin-bottom: 14px;
}
.form-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
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
