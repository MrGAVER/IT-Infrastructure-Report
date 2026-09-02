<script setup lang="ts">
// Создание/переименование шаблона отчёта — только метаданные (название, описание, при создании
// ещё и формат). Визуальное редактирование содержимого (config.sheets/blocks) сюда не входит —
// см. комментарий в api/reportTemplates.ts и frontend-vue/README.md. При создании бэкенду
// отправляется автоматически сгенерированный минимальный валидный каркас config (иначе POST
// отклонится структурной валидацией); при переименовании существующий config округляется как
// есть, без изменений — формат тоже нельзя менять при редактировании (это изменило бы схему,
// которой должен соответствовать УЖЕ существующий config, и почти наверняка сделало бы его
// невалидным).
import { computed, reactive, ref, watch } from 'vue'
import { createReportTemplate, renameReportTemplate } from '../api/reportTemplates'
import type { ReportTemplate } from '../api/types'

const props = defineProps<{ template: ReportTemplate | null }>()
const emit = defineEmits<{ close: []; saved: [template: ReportTemplate] }>()

const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.template !== null)

function emptyForm() {
  return { name: '', description: '', format: 'xlsx' as 'xlsx' | 'docx' }
}
const form = reactive(emptyForm())

watch(
  () => props.template,
  (t) => {
    Object.assign(form, emptyForm())
    if (t) {
      form.name = t.name
      form.description = t.description ?? ''
      form.format = t.format
    }
  },
  { immediate: true },
)

async function submit() {
  errorMessage.value = null
  if (!form.name.trim()) {
    errorMessage.value = 'Укажите название шаблона.'
    return
  }
  saving.value = true
  try {
    const saved = isEdit.value
      ? await renameReportTemplate(props.template!, { name: form.name.trim(), description: form.description.trim() || null })
      : await createReportTemplate({ name: form.name.trim(), description: form.description.trim() || null, format: form.format })
    emit('saved', saved)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить шаблон отчёта'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="modal card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Переименовать шаблон' : 'Новый шаблон отчёта' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <p v-if="!isEdit" class="hint">
        Создастся заготовка с минимальным содержимым (одна ячейка/блок с названием) — раскладку
        листов и полей можно донастроить в конструкторе сразу после создания.
      </p>

      <form class="form-grid" @submit.prevent="submit">
        <label class="field field-wide">
          <span>Название *</span>
          <input v-model.trim="form.name" type="text" required maxlength="255" />
        </label>

        <label class="field field-wide">
          <span>Описание</span>
          <textarea v-model.trim="form.description" rows="2" maxlength="2000"></textarea>
        </label>

        <label class="field">
          <span>Формат файла</span>
          <select v-model="form.format" :disabled="isEdit">
            <option value="xlsx">Excel (.xlsx)</option>
            <option value="docx">Word (.docx)</option>
          </select>
          <small v-if="isEdit" class="hint-small">Формат нельзя изменить у существующего шаблона.</small>
        </label>
      </form>

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">Отмена</button>
        <button type="button" class="btn btn-primary" :disabled="saving" @click="submit">
          {{ saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Создать' }}
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
.hint {
  font-size: 11.5px;
  color: var(--ink-muted);
  background: var(--surface-2);
  border-radius: var(--r-s);
  padding: 9px 11px;
  margin: 0 0 14px;
}
.hint code {
  font-family: var(--font-mono);
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
.field input,
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
  opacity: 0.45;
}
.hint-small {
  font-size: 10.5px;
  color: var(--ink-muted);
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

@media (max-width: 560px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
