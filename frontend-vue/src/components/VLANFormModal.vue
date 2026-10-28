<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { createResource, updateResource } from '../api/client'
import type { CatalogItem, VLANDefinition } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import QuickAddButton from './QuickAddButton.vue'
import { useOverlayDismiss } from '../composables/useOverlayDismiss'
import { useReadOnlyForm } from '../composables/useReadOnlyForm'

// Роль без права записи (viewer) видит карточку в режиме просмотра: поля отключены, кнопки «Сохранить» нет.
const { readOnly } = useReadOnlyForm()

const props = defineProps<{ definition: VLANDefinition | null }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))

const catalogs = useCatalogsStore()
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.definition !== null)

// vlan_id хранится как string | number, не просто string: на <input type="number"> Vue
// автоматически приводит значение из v-model к числу при вводе (looseToNumber в runtime-directive
// vModelText — встроенное поведение специально для type="number"/"range", срабатывает вне
// зависимости от модификатора .number на самом v-model), а при программном заполнении формы
// (watch ниже, emptyForm()) в это же поле кладётся строка. Раньше здесь стоял .trim() без учёта
// этого: form.vlan_id.trim() падал TypeError'ом, как только form.vlan_id успевал побывать числом
// (т.е. после первого же ввода пользователем) — необработанное исключение вылетало ДО
// errorMessage.value = ... и ДО try/catch вокруг saving, так что клик "Добавить" внешне выглядел
// как "ничего не происходит". Валидация ниже поэтому работает через Number(...), не .trim().
function emptyForm(): { vlan_id: string | number; name: string; description: string; domain_id: string } {
  return { vlan_id: '', name: '', description: '', domain_id: '' }
}
const form = reactive(emptyForm())

watch(
  () => props.definition,
  (d) => {
    Object.assign(form, emptyForm())
    if (d) {
      form.vlan_id = String(d.vlan_id)
      form.name = d.name
      form.description = d.description ?? ''
      form.domain_id = d.domain_id ?? ''
    }
  },
  { immediate: true },
)

async function submit() {
  if (readOnly.value) return
  errorMessage.value = null
  const vlanIdEmpty = typeof form.vlan_id === 'string' && form.vlan_id.trim() === ''
  const vlanIdNum = Number(form.vlan_id)
  if (vlanIdEmpty || !Number.isInteger(vlanIdNum) || vlanIdNum < 1 || vlanIdNum > 4094) {
    errorMessage.value = 'Укажите корректный VLAN ID (целое число от 1 до 4094).'
    return
  }
  if (!form.name.trim()) {
    errorMessage.value = 'Укажите имя VLAN.'
    return
  }

  saving.value = true
  try {
    const payload = {
      vlan_id: vlanIdNum,
      name: form.name.trim(),
      description: form.description || null,
      domain_id: form.domain_id || null,
    }
    if (isEdit.value) await updateResource('vlans', props.definition!.id, payload)
    else await createResource('vlans', payload)
    emit('saved')
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить VLAN'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Редактировать VLAN' : 'Добавить VLAN' }}</h2>
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
          <span>VLAN ID *</span>
          <input v-model="form.vlan_id" type="number" min="1" max="4094" required />
        </label>

        <label class="field">
          <span>Имя *</span>
          <input v-model.trim="form.name" type="text" required maxlength="255" />
        </label>

        <label class="field">
          <span>Домен VLAN</span>
          <div class="lookup-row">
            <select v-model="form.domain_id">
              <option value="">— локальный (без домена) —</option>
              <option v-for="d in catalogs.items['vlan-domains'] ?? []" :key="d.id" :value="d.id">{{ d.name }}</option>
            </select>
            <QuickAddButton resource="vlan-domains" title="Домен VLAN" @created="(r: CatalogItem) => (form.domain_id = r.id)" />
          </div>
        </label>

        <label class="field field-wide">
          <span>Описание</span>
          <textarea v-model.trim="form.description" rows="2" maxlength="2000"></textarea>
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
  min-width: 0;
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
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
.lookup-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.lookup-row select {
  flex: 1;
  min-width: 0;
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
