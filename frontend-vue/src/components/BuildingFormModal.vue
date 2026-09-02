<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { createResource, updateResource } from '../api/client'
import type { Building, CatalogItem } from '../api/types'
import { useCatalogsStore } from '../stores/catalogs'
import QuickAddButton from './QuickAddButton.vue'

const props = defineProps<{ building: Building | null }>()
const emit = defineEmits<{ close: []; saved: [] }>()

const catalogs = useCatalogsStore()
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const isEdit = computed(() => props.building !== null)

function emptyForm() {
  return { name: '', address: '', structural_unit_id: '' }
}
const form = reactive(emptyForm())

watch(
  () => props.building,
  (b) => {
    Object.assign(form, emptyForm())
    if (b) {
      form.name = b.name
      form.address = b.address ?? ''
      form.structural_unit_id = b.structural_unit_id ?? ''
    }
  },
  { immediate: true },
)

async function submit() {
  errorMessage.value = null
  if (!form.name.trim()) {
    errorMessage.value = 'Укажите наименование здания.'
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      address: form.address || null,
      structural_unit_id: form.structural_unit_id || null,
    }
    if (isEdit.value) await updateResource('buildings', props.building!.id, payload)
    else await createResource('buildings', payload)
    emit('saved')
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить здание'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="modal card" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h2>{{ isEdit ? 'Редактировать здание' : 'Добавить здание' }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <form class="form-grid" @submit.prevent="submit">
        <label class="field field-wide">
          <span>Наименование *</span>
          <input v-model.trim="form.name" type="text" required maxlength="255" />
        </label>
        <label class="field field-wide">
          <span>Адрес</span>
          <input v-model.trim="form.address" type="text" maxlength="500" />
        </label>
        <label class="field field-wide">
          <span>Структурная единица</span>
          <div class="lookup-row">
            <select v-model="form.structural_unit_id">
              <option value="">— не указана —</option>
              <option v-for="u in catalogs.items['structural-units'] ?? []" :key="u.id" :value="u.id">{{ u.name }}</option>
            </select>
            <QuickAddButton
              resource="structural-units"
              title="Структурная единица"
              @created="(r: CatalogItem) => (form.structural_unit_id = r.id)"
            />
          </div>
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
.overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.55); z-index: 60; display: flex; align-items: flex-start; justify-content: center; padding: 40px 16px; overflow-y: auto; }
.modal { width: 100%; max-width: 480px; padding: 20px 22px 18px; }
.modal-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.modal-head h2 { font-family: var(--font-display); font-size: 16px; margin: 0; }
.form-error { display: flex; align-items: center; gap: 8px; background: var(--status-crit-soft, rgba(229, 72, 77, 0.12)); color: var(--status-crit); border-radius: var(--r-m); padding: 9px 12px; font-size: 12.5px; margin-bottom: 14px; }
.form-grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
.field { display: flex; flex-direction: column; gap: 5px; font-size: 11.5px; color: var(--ink-muted); min-width: 0; }
.field input, .field select { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r-s); padding: 8px 9px; font-size: 13px; color: var(--ink); font-family: inherit; width: 100%; min-width: 0; box-sizing: border-box; }
.lookup-row { display: flex; align-items: center; gap: 6px; min-width: 0; }
.lookup-row select { flex: 1; min-width: 0; }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border); }
</style>
