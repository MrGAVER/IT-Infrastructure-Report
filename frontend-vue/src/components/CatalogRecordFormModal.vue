<script setup lang="ts">
// Модалка создания/редактирования записи справочника для OtherCatalogsView.vue (п.6). Намеренно
// НЕ переиспользует QuickAddModal.vue напрямую (хотя поля рендерятся по той же схеме из
// quickAdd/schema.ts и шаблон почти идентичен) — а отдельный компонент: QuickAddModal.vue не
// поддерживает режим редактирования (только создание, PUT там просто нет) и активно используется
// как есть ~в 20 местах приложения с своим набором тестов; встраивать туда ветвление
// create/edit ради одного экрана — больше риска регресса, чем пользы от устранения дублирования
// разметки полей (тот же компромисс, что уже сделан для SearchableSelect.vue при выборе точки
// применения, см. README).
import { computed, reactive, ref, useId } from 'vue'
import { createResource, deleteResource, updateResource } from '../api/client'
import { useCatalogsStore } from '../stores/catalogs'
import { sortOptionsByLabel } from '../utils/selectOptions'
import { useDevicesStore } from '../stores/devices'
import { QUICK_ADD_FIELDS, QUICK_ADD_LABELS } from '../quickAdd/schema'
import type { QuickField } from '../quickAdd/schema'
import type { CatalogItem } from '../api/types'
import BaseModal from './BaseModal.vue'
import { vTruncateTooltip } from '../directives/truncateTooltip'
import QuickAddButton from './QuickAddButton.vue'
import SearchableSelect from './SearchableSelect.vue'
import type { SearchableSelectOption } from './SearchableSelect.vue'
import DeviceIconPicker from './DeviceIconPicker.vue'
import { useReadOnlyForm } from '../composables/useReadOnlyForm'

// Роль без права записи (viewer) видит карточку в режиме просмотра: поля отключены, кнопки «Сохранить» нет.
const { readOnly } = useReadOnlyForm()

const props = defineProps<{
  resource: string
  /** null — создание новой записи; объект — редактирование существующей (должен содержать id). */
  item: Record<string, unknown> | null
}>()
const emit = defineEmits<{ close: []; saved: [record: CatalogItem]; deleted: [id: string] }>()
// Доступное имя диалога — его заголовок (UI-04): скринридер озвучивает название при открытии окна.
const titleId = useId()

const catalogs = useCatalogsStore()
const devicesStore = useDevicesStore()
const fields = QUICK_ADD_FIELDS[props.resource] ?? []
const isEdit = computed(() => props.item !== null)
// Общий human-readable ярлык ресурса — используется и в заголовке, и в сообщении "форма не
// настроена" ниже. Раньше последнее показывало props.resource как есть (технический ключ вроде
// device-types), а заголовок тут же рядом — уже с fallback на QUICK_ADD_LABELS; несогласованность
// нашлась при ревизии фронтенда на предмет технических записей, показываемых пользователю.
const resourceLabel = computed(() => QUICK_ADD_LABELS[props.resource] ?? props.resource)
const title = computed(() => `${isEdit.value ? 'Редактировать' : 'Добавить'}: ${resourceLabel.value}`)

function initialValue(name: string, type: string): string | boolean {
  if (!props.item) return type === 'checkbox' ? false : ''
  const raw = props.item[name]
  if (type === 'checkbox') return Boolean(raw)
  return raw === null || raw === undefined ? '' : String(raw)
}
const values = reactive<Record<string, string | boolean>>(Object.fromEntries(fields.map((f) => [f.name, initialValue(f.name, f.type)])))

const saving = ref(false)
const deleting = ref(false)
const errorMessage = ref<string | null>(null)

function fkSelectOptions(f: QuickField): SearchableSelectOption[] {
  // fkSource='devices' — физические устройства не входят в catalogs.items (см. комментарий у
  // QuickField.fkSource в quickAdd/schema.ts), опции берём из отдельного стора устройств.
  // Он уже загружен родительским экраном (OtherCatalogsView.vue дожидается ensureLoaded() до
  // открытия этой модалки), сортируем по совпадению с общим принципом "выпадающие списки
  // отсортированы" (фикс п.4.2 в stores/catalogs.ts), т.к. порядок в devicesStore.all —
  // порядок ответа API, а не алфавитный.
  if (f.fkSource === 'devices') {
    return sortOptionsByLabel(devicesStore.all.map((d) => ({ value: d.id, label: d.system_name || d.serial_number })))
  }
  const fkResource = f.fkResource
  if (!fkResource) return []
  const items = catalogs.items[fkResource as keyof typeof catalogs.items] ?? []
  // Self-referencing fk (parent_id у иерархических справочников, напр. departments): при
  // редактировании запись не может быть родителем самой себе — иначе зациклит дерево (тот же
  // приём, что и в StructuralUnitFormModal.vue:availableParents). Проверка общая для любого
  // fk-поля, где fkResource совпадает с редактируемым resource — не завязана на имя поля
  // parent_id конкретно, сработает для любого будущего self-referencing справочника.
  const selfId = isEdit.value ? String(props.item!.id) : null
  const options = fkResource === props.resource && selfId !== null ? items.filter((opt) => opt.id !== selfId) : items
  return options.map((opt) => ({ value: opt.id, label: opt.name }))
}
function onNestedCreated(fieldName: string, record: CatalogItem) {
  values[fieldName] = record.id
}

async function submit() {
  if (readOnly.value) return
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
    const saved = isEdit.value
      ? await updateResource<CatalogItem>(props.resource, String(props.item!.id), payload)
      : await createResource<CatalogItem>(props.resource, payload)
    emit('saved', saved)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить запись'
  } finally {
    saving.value = false
  }
}

async function removeItem() {
  if (!props.item) return
  const id = String(props.item.id)
  if (!confirm(`Удалить запись «${props.item.name ?? id}»? Действие необратимо.`)) return
  deleting.value = true
  errorMessage.value = null
  try {
    await deleteResource(props.resource, id)
    emit('deleted', id)
  } catch (err) {
    // REFERENCED_BY_OTHER_RECORDS и подобные коды бэкенд уже сопровождает понятным message —
    // показываем его как есть, не подменяя собственной универсальной формулировкой.
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось удалить запись'
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <BaseModal @close="emit('close')">
    <div class="modal card" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <div class="modal-head">
        <h2 :id="titleId">{{ title }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>
      <div v-if="!fields.length" class="form-error">Для «{{ resourceLabel }}» форма не настроена.</div>

      <fieldset v-else class="readonly-fieldset" :disabled="readOnly">
        <form class="form-grid" @submit.prevent="submit">
          <label v-for="f in fields" :key="f.name" class="field" :class="{ 'field-wide': f.type === 'textarea' || f.type === 'diagram-icon' }">
            <span v-if="f.type !== 'diagram-icon'">{{ f.label }}{{ f.required ? ' *' : '' }}</span>
            <div v-if="f.type === 'fk'" class="fk-row">
              <SearchableSelect
                :model-value="(values[f.name] as string) ?? ''"
                :options="fkSelectOptions(f)"
                @update:model-value="(v) => (values[f.name] = v)"
              />
              <QuickAddButton
                v-if="f.nestedQuickAdd && f.fkResource"
                :resource="f.fkResource"
                :title="QUICK_ADD_LABELS[f.fkResource]"
                @created="(record) => onNestedCreated(f.name, record)"
              />
            </div>
            <textarea
              v-else-if="f.type === 'textarea'"
              v-model="values[f.name] as string"
              v-truncate-tooltip="String(values[f.name] ?? '')"
              rows="2"
            ></textarea>
            <label v-else-if="f.type === 'checkbox'" class="checkbox-inline">
              <input type="checkbox" :checked="values[f.name] as boolean" @change="values[f.name] = ($event.target as HTMLInputElement).checked" />
            </label>
            <!-- Поле без своей <span>-подписи внутри <label>: DeviceIconPicker уже рендерит
                 собственную подпись "Иконка на диаграмме топологии сети" в своём шаблоне,
                 повторять её здесь через внешний <span> означало бы дублирование текста. -->
            <DeviceIconPicker
              v-else-if="f.type === 'diagram-icon'"
              :model-value="(values[f.name] as string) || null"
              @update:model-value="(v) => (values[f.name] = v ?? '')"
            />
            <input v-else v-model="values[f.name] as string" v-truncate-tooltip="String(values[f.name] ?? '')" :type="f.type" :required="f.required" />
          </label>
        </form>
      </fieldset>

      <div class="modal-foot">
        <button v-if="isEdit && !readOnly" type="button" class="btn btn-danger" :disabled="saving || deleting" @click="removeItem">
          {{ deleting ? 'Удаление…' : 'Удалить' }}
        </button>
        <div class="spacer" />
        <button type="button" class="btn btn-secondary" :disabled="saving || deleting" @click="$emit('close')">{{ readOnly ? 'Закрыть' : 'Отмена' }}</button>
        <button v-if="!readOnly" type="button" class="btn btn-primary" :disabled="saving || deleting || !fields.length" @click="submit">
          {{ saving ? 'Сохранение…' : isEdit ? 'Сохранить' : 'Добавить' }}
        </button>
      </div>
    </div>
  </BaseModal>
</template>

<style scoped>
.modal {
  width: 100%;
  /* Фикс п.1.3.6: тот же узкий 460px и та же причина обрезки текста в fk-полях, что и в
     QuickAddModal.vue (см. её комментарий) — это тот же класс форм ("Другие справочники"),
     страдающий от той же формы-грида 1fr 1fr. */
  max-width: clamp(460px, 34vw, 640px);
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
  color: var(--crit-ink);
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
.field textarea {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 8px 9px;
  font-size: 13px;
  color: var(--ink);
  font-family: inherit;
  resize: vertical;
}
.fk-row {
  display: flex;
  align-items: stretch;
  gap: 6px;
  min-width: 0;
}
.fk-row .searchable-select {
  flex: 1;
  min-width: 0;
}
.checkbox-inline input {
  width: 15px;
  height: 15px;
  accent-color: var(--brand);
}
.modal-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
.spacer {
  flex: 1;
}
.btn-danger {
  background: transparent;
  border: 1px solid var(--status-crit);
  color: var(--status-crit);
}
.btn-danger:hover:not(:disabled) {
  background: var(--status-crit-soft, rgba(229, 72, 77, 0.12));
}

@media (max-width: 520px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
