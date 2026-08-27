<script setup lang="ts">
// Универсальная модалка быстрого добавления записи справочника — форма строится динамически
// по схеме из quickAdd/schema.ts, без отдельного Vue-компонента на каждый из полутора десятков
// справочников. Портировано с openQuickModal()/saveQuickForm() в frontend/static/core.js/app.js
// (см. schema.ts про то, что сознательно не перенесено).
import { computed, reactive, ref } from 'vue'
import { createResource } from '../api/client'
import { useCatalogsStore } from '../stores/catalogs'
import { QUICK_ADD_FIELDS, QUICK_ADD_LABELS } from '../quickAdd/schema'
import type { CatalogItem } from '../api/types'

const props = defineProps<{ resource: string }>()
const emit = defineEmits<{ close: []; created: [record: CatalogItem] }>()

const catalogs = useCatalogsStore()
const fields = QUICK_ADD_FIELDS[props.resource] ?? []
const title = computed(() => QUICK_ADD_LABELS[props.resource] ?? props.resource)

const values = reactive<Record<string, string | boolean>>(
  Object.fromEntries(fields.map((f) => [f.name, f.type === 'checkbox' ? false : ''])),
)
const saving = ref(false)
const errorMessage = ref<string | null>(null)

function fkOptions(fkResource: string | undefined): CatalogItem[] {
  if (!fkResource) return []
  return catalogs.items[fkResource as keyof typeof catalogs.items] ?? []
}

async function submit() {
  errorMessage.value = null
  for (const f of fields) {
    if (f.required && !String(values[f.name] ?? '').trim()) {
      errorMessage.value = `Заполните поле «${f.label}».`
      return
    }
  }
  saving.value = true
  try {
    const payload: Record<string, unknown> = {}
    for (const f of fields) {
      const v = values[f.name]
      if (f.type === 'number') payload[f.name] = v === '' ? null : Number(v)
      else if (f.type === 'checkbox') payload[f.name] = Boolean(v)
      else payload[f.name] = v === '' ? null : v
    }
    const created = await createResource<CatalogItem>(props.resource, payload)
    // Точечно добавляем в уже загруженный каталог вместо полного catalogs.reload() —
    // справочник, в который только что что-то добавили, почти наверняка сейчас показан
    // где-то в выпадающем списке на экране, и должен обновиться сразу же. Без ?? [] здесь:
    // если каталог ещё не был загружен (items[key] === undefined, а не пустой массив — так
    // бывает, если форма открылась раньше catalogs.ensureLoaded()), просто ничего не
    // добавится, а выбор в вызывающем select'е молча не сработает — value без
    // соответствующего <option> браузер/jsdom игнорирует.
    const key = props.resource as keyof typeof catalogs.items
    catalogs.items[key] = [...(catalogs.items[key] ?? []), created]
    emit('created', created)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить запись'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <!-- Teleport в body: без него, при использовании внутри QuickAddButton, вложенном в форму
       вызывающего компонента (DeviceFormModal.vue и т.п.), получился бы <form> внутри <form> —
       HTML не допускает вложенные формы, браузер обработал бы это непредсказуемо (вложенный
       submit мог бы всплыть и отправить ВНЕШНЮЮ форму вместо этой). -->
  <Teleport to="body">
    <div class="overlay" @click.self="$emit('close')">
      <div class="modal card" role="dialog" aria-modal="true">
        <div class="modal-head">
          <h2>Добавить: {{ title }}</h2>
          <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
            <svg class="icon"><use href="/icons.svg#i-x" /></svg>
          </button>
        </div>

        <div v-if="errorMessage" class="form-error">
          <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
          {{ errorMessage }}
        </div>
        <div v-if="!fields.length" class="form-error">Для «{{ resource }}» быстрое добавление не настроено.</div>

        <form v-else class="form-grid" @submit.prevent="submit">
          <label v-for="f in fields" :key="f.name" class="field" :class="{ 'field-wide': f.type === 'textarea' }">
            <span>{{ f.label }}{{ f.required ? ' *' : '' }}</span>
            <select v-if="f.type === 'fk'" v-model="values[f.name] as string" :required="f.required">
              <option value="">— не выбрано —</option>
              <option v-for="opt in fkOptions(f.fkResource)" :key="opt.id" :value="opt.id">{{ opt.name }}</option>
            </select>
            <textarea v-else-if="f.type === 'textarea'" v-model="values[f.name] as string" rows="2"></textarea>
            <label v-else-if="f.type === 'checkbox'" class="checkbox-inline">
              <input
                type="checkbox"
                :checked="values[f.name] as boolean"
                @change="values[f.name] = ($event.target as HTMLInputElement).checked"
              />
            </label>
            <input v-else v-model="values[f.name] as string" :type="f.type" :required="f.required" />
          </label>
        </form>

        <div class="modal-foot">
          <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">Отмена</button>
          <button type="button" class="btn btn-primary" :disabled="saving || !fields.length" @click="submit">
            {{ saving ? 'Сохранение…' : 'Добавить' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 70;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 16px;
  overflow-y: auto;
}
.modal {
  width: 100%;
  max-width: 460px;
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
  font-size: 15px;
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
.checkbox-inline input {
  width: 15px;
  height: 15px;
  accent-color: var(--brand);
}
.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}

@media (max-width: 520px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
