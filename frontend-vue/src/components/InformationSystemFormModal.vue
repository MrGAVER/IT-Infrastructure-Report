<script setup lang="ts">
// Форма покрывает только собственные поля InformationSystem — те же, что
// сохраняет базовое сохранение в vanilla-фронтенде (frontend/static/information-systems.js:
// saveInformationSystemForm, первый PUT/POST до синхронизации /details). Вложенные
// связи (подразделения, IP, протоколы, источники размещения) требуют отдельного
// редактора над /resources/information-systems/{id}/details — не реализовано в этой
// итерации, см. README "Ещё не сделано".
import { computed, reactive, ref, watch } from 'vue'
import { createResource, updateResource } from '../api/client'
import type { InformationSystem } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'

const props = defineProps<{ system: InformationSystem | null }>()
const emit = defineEmits<{ close: []; saved: [system: InformationSystem] }>()

const catalogs = useCatalogsStore()
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.system !== null)

function emptyForm() {
  return {
    name: '',
    description: '',
    purpose: '',
    localization: '',
    support_organization_id: '',
    support_method_id: '',
    process_description: '',
    crypto_protection_enabled: false,
    crypto_protection_description_id: '',
    siem_enabled: false,
  }
}

const form = reactive(emptyForm())

watch(
  () => props.system,
  (s) => {
    Object.assign(form, emptyForm())
    if (s) {
      for (const key of Object.keys(form) as (keyof typeof form)[]) {
        const value = s[key as keyof InformationSystem]
        if (typeof form[key] === 'boolean') {
          ;(form[key] as boolean) = Boolean(value)
        } else {
          ;(form[key] as string) = (value as string) ?? ''
        }
      }
    }
  },
  { immediate: true },
)

function toPayload() {
  const payload: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(form)) {
    payload[key] = value === '' ? null : value
  }
  return payload
}

async function submit() {
  errorMessage.value = null
  if (!form.name.trim()) {
    errorMessage.value = 'Укажите наименование информационной системы.'
    return
  }
  saving.value = true
  try {
    const payload = toPayload()
    const saved = isEdit.value
      ? await updateResource<InformationSystem>('information-systems', props.system!.id, payload)
      : await createResource<InformationSystem>('information-systems', payload)
    emit('saved', saved)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить информационную систему'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="modal card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Редактировать информационную систему' : 'Добавить информационную систему' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <p class="scope-hint">
        Форма охватывает основные поля ИС. Связанные подразделения, IP-адреса, протоколы и
        источники размещения пока редактируются только в текущем vanilla-интерфейсе.
      </p>

      <form class="form-grid" @submit.prevent="submit">
        <label class="field field-wide">
          <span>Наименование *</span>
          <input v-model.trim="form.name" type="text" required maxlength="500" />
        </label>

        <label class="field field-wide">
          <span>Общее описание</span>
          <textarea v-model.trim="form.description" rows="2" maxlength="4000"></textarea>
        </label>

        <label class="field field-wide">
          <span>Назначение использования</span>
          <textarea v-model.trim="form.purpose" rows="2" maxlength="4000"></textarea>
        </label>

        <label class="field field-wide">
          <span>Локализация</span>
          <textarea v-model.trim="form.localization" rows="2" maxlength="4000"></textarea>
        </label>

        <label class="field">
          <span>Организация технической поддержки</span>
          <select v-model="form.support_organization_id">
            <option value="">— не указана —</option>
            <option v-for="o in catalogs.items['support-organizations'] ?? []" :key="o.id" :value="o.id">{{ o.name }}</option>
          </select>
        </label>

        <label class="field">
          <span>Способ оказания техподдержки</span>
          <select v-model="form.support_method_id">
            <option value="">— не указан —</option>
            <option v-for="m in catalogs.items['support-methods'] ?? []" :key="m.id" :value="m.id">{{ m.name }}</option>
          </select>
        </label>

        <label class="field field-wide">
          <span>Описание процесса функционирования</span>
          <textarea v-model.trim="form.process_description" rows="2" maxlength="4000"></textarea>
        </label>

        <label class="field checkbox-field">
          <input v-model="form.siem_enabled" type="checkbox" />
          <span>Отправляет события в SIEM</span>
        </label>

        <label class="field checkbox-field">
          <input v-model="form.crypto_protection_enabled" type="checkbox" />
          <span>Применяются сертифицированные СКЗИ</span>
        </label>

        <label class="field field-wide">
          <span>Средство криптографической защиты</span>
          <select v-model="form.crypto_protection_description_id" :disabled="!form.crypto_protection_enabled">
            <option value="">— не указано —</option>
            <option v-for="c in catalogs.items['crypto-protection-means'] ?? []" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </label>
      </form>

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">Отмена</button>
        <button type="button" class="btn btn-primary" :disabled="saving" @click="submit">
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
  max-width: 640px;
  padding: 20px 22px 18px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.modal-head h2 {
  font-family: var(--font-display);
  font-size: 16px;
  margin: 0;
}
.scope-hint {
  font-size: 11.5px;
  color: var(--ink-muted);
  line-height: 1.5;
  margin: 0 0 14px;
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
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 14px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
  color: var(--ink-muted);
}
.field-wide {
  grid-column: 1 / -1;
}
.field input[type='text'],
.field select,
.field textarea {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
  resize: vertical;
}
.field select:disabled {
  opacity: 0.5;
}
.checkbox-field {
  flex-direction: row;
  align-items: center;
  gap: 8px;
  margin-top: 18px;
}
.checkbox-field input {
  accent-color: var(--brand);
  width: 15px;
  height: 15px;
}
.checkbox-field span {
  color: var(--ink);
  font-size: 12.5px;
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

@media (max-width: 640px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
