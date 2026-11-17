<script setup lang="ts">
// Форма «Настройки аудита»: срок хранения журнала. Открывается кнопкой из экрана «Журнал аудита»
// и из «Настроек» (AuditSettingsButton.vue). Записи старше срока удаляются безвозвратно — сразу после сохранения и затем не чаще
// раза в сутки; 0 — не удалять. Перед сохранением положительного срока форма просит подтверждение: опечатка («7» вместо «700»)
// иначе молча стёрла бы журнал.
//
// Права. Форму открывает только тот, кому доступен сам журнал (auth.canViewAuditLog — кнопки без права не рисуются), а решает
// сервер: viewer получает 403 и на чтение, и на запись. Здесь это учтено на случай, если роль изменили, пока экран был открыт:
// ошибка загрузки или сохранения показывается текстом сервера, а не молча.
import { computed, onMounted, ref, watch } from 'vue'
import { ApiError } from '../api/client'
import type { AuditSettingsSaveResult } from '../api/types'
import { useToast } from '../composables/useToast'
import { useAuditSettingsStore } from '../stores/auditSettings'
import { describeRetention, parseRetentionDays } from '../utils/auditRetention'
import { formatServerDateTime } from '../utils/dateTime'
import BaseModal from './BaseModal.vue'

const emit = defineEmits<{ close: []; saved: [result: AuditSettingsSaveResult] }>()

const store = useAuditSettingsStore()
const toast = useToast()

const draft = ref('')
const errorMessage = ref<string | null>(null)

const settings = computed(() => store.settings)
const parsed = computed(() => (settings.value ? parseRetentionDays(draft.value, settings.value.max_retention_days) : null))
const draftError = computed(() => (parsed.value && !parsed.value.ok ? parsed.value.error : null))
const unchanged = computed(() => !!settings.value && !!parsed.value?.ok && parsed.value.days === settings.value.retention_days)
const canSave = computed(() => !store.saving && !!parsed.value?.ok && !unchanged.value)
const canReset = computed(() => !store.saving && !!settings.value && !settings.value.is_default)

// Поле заполняется значением с сервера — и сразу из кэша стора, и после свежей загрузки, но только пока пользователь ничего не ввёл.
const touched = ref(false)
watch(
  () => store.settings,
  (value) => {
    if (value && !touched.value) draft.value = String(value.retention_days)
  },
  { immediate: true },
)
watch(draft, () => (errorMessage.value = null))

onMounted(() => void store.load())

function confirmPurge(days: number): boolean {
  if (days === 0) return true
  return confirm(`Записи журнала аудита старше ${days} дн. будут удалены безвозвратно — сразу после сохранения. Продолжить?`)
}

async function apply(days: number | null) {
  if (!settings.value) return
  // null — сброс к значению по умолчанию: удаление произойдёт по нему, его и показываем в подтверждении.
  if (!confirmPurge(days ?? settings.value.default_retention_days)) return
  errorMessage.value = null
  try {
    const result = await store.save(days)
    if (result.cleanup_failed) {
      toast.notify('Срок хранения сохранён, но очистка не удалась. Она повторится при следующем запуске.', 'warning')
    } else {
      const removed = result.removed_now > 0 ? ` Удалено записей: ${result.removed_now}.` : ''
      toast.notify(`Настройки аудита сохранены.${removed}`, 'success')
    }
    emit('saved', result)
    emit('close')
  } catch (err) {
    errorMessage.value = err instanceof ApiError ? err.message : 'Не удалось сохранить настройки аудита'
  }
}

function submit() {
  if (parsed.value?.ok && canSave.value) void apply(parsed.value.days)
}
</script>

<template>
  <BaseModal @close="emit('close')">
    <div class="modal card" role="dialog" aria-modal="true" aria-labelledby="audit-settings-title" data-testid="audit-settings-modal">
      <div class="modal-head">
        <h2 id="audit-settings-title">Настройки аудита</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="store.error && !settings" class="form-error" role="alert" data-testid="audit-settings-load-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ store.error }}
      </div>
      <p v-else-if="!settings" class="loading" data-testid="audit-settings-loading">Загрузка настроек…</p>

      <form v-else @submit.prevent="submit">
        <label class="field" for="audit-retention-days">
          <span>Срок хранения журнала, дней</span>
          <input
            id="audit-retention-days"
            v-model="draft"
            type="number"
            inputmode="numeric"
            min="0"
            :max="settings.max_retention_days"
            step="1"
            data-field="retention-days"
            @input="touched = true"
            :aria-invalid="draftError ? 'true' : undefined"
            :disabled="store.saving"
          />
        </label>
        <p class="hint">
          0 — хранить без ограничения: записи не удаляются. Записи старше указанного срока удаляются безвозвратно — сразу после сохранения, а затем не чаще раза
          в сутки (при запуске сервера и при открытии журнала). Об изменении срока и о каждой очистке остаётся запись в самом журнале.
        </p>
        <p v-if="draftError" class="field-error" role="alert" data-testid="audit-settings-field-error">{{ draftError }}</p>
        <p v-else-if="unchanged" class="hint" data-testid="audit-settings-unchanged">Значение совпадает с действующим — сохранять нечего.</p>

        <dl class="status">
          <dt>Сейчас</dt>
          <dd data-testid="audit-settings-current">
            {{ describeRetention(settings.retention_days) }}<span v-if="settings.is_default"> (значение по умолчанию)</span>
          </dd>
          <dt>Последняя очистка</dt>
          <dd data-testid="audit-settings-last-cleanup">
            {{ settings.last_cleanup_at ? formatServerDateTime(settings.last_cleanup_at) : 'ещё не выполнялась' }}
          </dd>
        </dl>

        <div v-if="errorMessage" class="form-error" role="alert" data-testid="audit-settings-save-error">
          <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
          {{ errorMessage }}
        </div>

        <div class="modal-foot">
          <button type="button" class="btn btn-secondary" @click="emit('close')">Отмена</button>
          <button
            type="button"
            class="btn btn-secondary"
            data-testid="audit-settings-reset"
            :disabled="!canReset"
            :title="`Вернуть значение по умолчанию: ${describeRetention(settings.default_retention_days)}`"
            @click="apply(null)"
          >
            Сбросить
          </button>
          <button type="submit" class="btn btn-primary" data-testid="audit-settings-save" :disabled="!canSave">
            {{ store.saving ? 'Сохранение…' : 'Сохранить' }}
          </button>
        </div>
      </form>
    </div>
  </BaseModal>
</template>

<style scoped>
.modal {
  width: 100%;
  max-width: 520px;
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
.loading {
  margin: 0 0 12px;
  font-size: 12.5px;
  color: var(--ink-muted);
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
  margin-bottom: 10px;
}
.field input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
  max-width: 160px;
}
.field input[aria-invalid='true'] {
  border-color: var(--status-crit, #e5484d);
}
.hint {
  margin: 0 0 12px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--ink-muted);
}
.field-error {
  margin: -4px 0 12px;
  font-size: 12px;
  color: var(--crit-ink);
}
.status {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 4px 14px;
  margin: 0 0 14px;
  padding: 9px 12px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  font-size: 12.5px;
}
.status dt {
  color: var(--ink-muted);
}
.status dd {
  margin: 0;
  color: var(--ink);
}
</style>
