<script setup lang="ts">
// Универсальная модалка быстрого добавления записи справочника — форма строится динамически
// по схеме из quickAdd/schema.ts, без отдельного Vue-компонента на каждый из полутора десятков
// справочников. Портировано с openQuickModal()/saveQuickForm() прежнего vanilla-фронтенда (до 2.60.0)
// (см. schema.ts про то, что сознательно не перенесено).
import { computed, reactive, ref, useId } from 'vue'
import { createResource } from '../api/client'
import { useCatalogsStore, sortProtocolPortCatalog } from '../stores/catalogs'
import { sortOptionsByLabel } from '../utils/selectOptions'
import { useDevicesStore } from '../stores/devices'
import { QUICK_ADD_FIELDS, QUICK_ADD_LABELS, QUICK_ADD_SINGLE_COLUMN } from '../quickAdd/schema'
import type { QuickAddFkScope, QuickField } from '../quickAdd/schema'
import type { CatalogItem, ProtocolPortCatalogEntry } from '../api/types'
import BaseModal from './BaseModal.vue'
import { vTruncateTooltip } from '../directives/truncateTooltip' // Кнопка "+" для вложенного быстрого добавления (см. nestedQuickAdd в quickAdd/schema.ts).
// Циклический импорт (QuickAddButton.vue сам рендерит QuickAddModal.vue) безопасен: обе стороны
// используются только в шаблоне/во время рендера, а не в теле модуля при загрузке — к моменту
// первого рендера оба модуля уже полностью инициализированы. Второй уровень вложенности не
// возникает: вложенная QuickAddModal открывается для fkResource, у которого своих fk-полей с
// nestedQuickAdd в схеме нет (см. комментарий в schema.ts).
import QuickAddButton from './QuickAddButton.vue'
import SearchableSelect from './SearchableSelect.vue'
import type { SearchableSelectOption } from './SearchableSelect.vue'
import DeviceIconPicker from './DeviceIconPicker.vue'

const props = defineProps<{ resource: string; initialValues?: Record<string, string>; fkScope?: QuickAddFkScope }>()
const emit = defineEmits<{
  close: []
  created: [record: CatalogItem]
  // Пункт 2/3 правки "создание физического устройства": родителю нужно знать не только что
  // текущее поле заполнилось (это values[fieldName] уже делает ниже), но и КАКОЙ РЕСУРС был
  // только что создан вложенным "+" — чтобы, например, DeviceVlanListEditor.vue отличил
  // "заведён новый VLAN" от "внутри этого — ещё и заведён новый Домен VLAN" и среагировал на
  // домен отдельно (см. DeviceFormModal.vue:onVlanDomainCreated). Второй уровень вложенности
  // сюда не добавляется (см. комментарий у импорта QuickAddButton выше) — это просто трансляция
  // уже существующего вложенного события дальше вверх по цепочке компонентов.
  'nested-created': [fieldName: string, fkResource: string, record: CatalogItem]
}>()
// Доступное имя диалога — его заголовок (UI-04): скринридер озвучивает название при открытии окна.
const titleId = useId()

const catalogs = useCatalogsStore()
const devicesStore = useDevicesStore()
const fields = QUICK_ADD_FIELDS[props.resource] ?? []
const title = computed(() => QUICK_ADD_LABELS[props.resource] ?? props.resource)
// Расширенное окно с полями друг под другом — см. QUICK_ADD_SINGLE_COLUMN в quickAdd/schema.ts.
const singleColumn = QUICK_ADD_SINGLE_COLUMN.has(props.resource)

// Фикс п.2.2: initialValues — предзаполнение поля значением, которое почти наверняка и так
// нужно пользователю в текущем контексте (напр. domain_id уже известного домена устройства при
// добавлении VLAN из формы этого устройства — см. DeviceVlanListEditor.vue). Пользователь может
// изменить значение как обычно, это только стартовое состояние поля, а не заморозка.
const values = reactive<Record<string, string | boolean>>(
  Object.fromEntries(fields.map((f) => [f.name, props.initialValues?.[f.name] ?? (f.type === 'checkbox' ? false : '')])),
)
const saving = ref(false)
const errorMessage = ref<string | null>(null)

function fkOptions(fkResource: string | undefined): CatalogItem[] {
  if (!fkResource) return []
  return catalogs.items[fkResource as keyof typeof catalogs.items] ?? []
}

/** п.4: опции fk-поля в формате SearchableSelect. fkSource='devices' — см. комментарий у
 * QuickField.fkSource в quickAdd/schema.ts: устройства не входят в catalogs.items, опции берём
 * из useDevicesStore().all и сортируем вручную (devicesStore.all не отсортирован, в отличие от
 * уже отсортированных catalogs.items — фикс п.4.2). Единственный вызывающий эту схему для
 * fkSource='devices' на сегодня — crypto-protection-means, открываемый из
 * InformationSystemFormModal.vue, где devicesStore уже загружен родительским
 * InformationSystemsView.vue. */
function fkSelectOptions(f: QuickField): SearchableSelectOption[] {
  if (f.fkSource === 'devices') {
    return sortOptionsByLabel(devicesStore.all.map((d) => ({ value: d.id, label: d.system_name || d.serial_number })))
  }
  const scope = props.fkScope?.[f.name]
  const options = fkOptions(f.fkResource)
  // fkScope: например, при добавлении стойки из формы устройства — только помещения выбранного там здания.
  const scoped = scope?.value ? options.filter((opt) => (opt as unknown as Record<string, unknown>)[scope.field] === scope.value) : options
  return scoped.map((opt) => ({ value: opt.id, label: opt.name }))
}

/** Запись, созданная через вложенную QuickAddModal (кнопка "+" у fk-поля), сразу подставляется
 * в это поле текущей формы — так же, как QuickAddButton.vue делает для полей вызывающих форм.
 * Событие транслируется и наверх (nested-created) — см. его комментарий у defineEmits выше. */
function onNestedCreated(fieldName: string, fkResource: string, record: CatalogItem) {
  values[fieldName] = record.id
  emit('nested-created', fieldName, fkResource, record)
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
    if (props.resource === 'protocol-port-catalog') {
      // Особый случай: у ProtocolPortCatalogEntry нет поля name, поэтому он живёт не в
      // общем catalogs.items, а в отдельном catalogs.protocolPortCatalog — см. комментарий
      // к типу в api/types. sortProtocolPortCatalog() — общая с catalogs.ts:reload()
      // точка сортировки по (port, protocol_type), фикс п.4.2.
      const entry = created as unknown as ProtocolPortCatalogEntry
      catalogs.protocolPortCatalog = sortProtocolPortCatalog([...catalogs.protocolPortCatalog, entry])
    } else {
      // Точечно добавляем в уже загруженный каталог вместо полного catalogs.reload() —
      // справочник, в который только что что-то добавили, почти наверняка сейчас показан
      // где-то в выпадающем списке на экране, и должен обновиться сразу же (см.
      // catalogs.addCatalogItem() — она же сохраняет сортировку, фикс п.4.2).
      catalogs.addCatalogItem(props.resource as keyof typeof catalogs.items, created)
    }
    emit('created', created)
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить запись'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <!-- BaseModal выносит окно в <body>: иначе при использовании внутри QuickAddButton, вложенном в форму вызывающего
       компонента (DeviceFormModal.vue и т.п.), получился бы <form> внутри <form> — HTML не допускает вложенные формы,
       вложенный submit мог бы всплыть и отправить ВНЕШНЮЮ форму вместо этой. -->
  <BaseModal @close="emit('close')">
    <div class="modal card" :class="{ 'modal-wide': singleColumn }" role="dialog" aria-modal="true" :aria-labelledby="titleId">
      <div class="modal-head">
        <h2 :id="titleId">Добавить: {{ title }}</h2>
        <button type="button" class="icon-btn" aria-label="Закрыть" @click="$emit('close')">
          <svg class="icon"><use href="/icons.svg#i-x" /></svg>
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>
      <div v-if="!fields.length" class="form-error">Для «{{ resource }}» быстрое добавление не настроено.</div>

      <form v-else class="form-grid" :class="{ 'form-grid-single': singleColumn }" @submit.prevent="submit">
        <label v-for="f in fields" :key="f.name" class="field" :class="{ 'field-wide': f.type === 'textarea' || f.type === 'diagram-icon' }">
          <!-- Правка "иконка вместо текстового блока в 'Добавить: Модель устройства'": та же
                 причина без <span>-подписи здесь, что и в аналогичном месте
                 CatalogRecordFormModal.vue — DeviceIconPicker уже рендерит собственную подпись
                 "Иконка на диаграмме топологии сети" в своём шаблоне. -->
          <span v-if="f.type !== 'diagram-icon'">{{ f.label }}{{ f.required ? ' *' : '' }}</span>
          <div v-if="f.type === 'fk'" class="fk-row">
            <SearchableSelect :model-value="(values[f.name] as string) ?? ''" :options="fkSelectOptions(f)" @update:model-value="(v) => (values[f.name] = v)" />
            <QuickAddButton
              v-if="f.nestedQuickAdd && f.fkResource"
              :resource="f.fkResource"
              :title="QUICK_ADD_LABELS[f.fkResource]"
              @created="(record) => onNestedCreated(f.name, f.fkResource ?? '', record)"
            />
          </div>
          <textarea v-else-if="f.type === 'textarea'" v-model="values[f.name] as string" rows="2"></textarea>
          <label v-else-if="f.type === 'checkbox'" class="checkbox-inline">
            <input type="checkbox" :checked="values[f.name] as boolean" @change="values[f.name] = ($event.target as HTMLInputElement).checked" />
          </label>
          <DeviceIconPicker
            v-else-if="f.type === 'diagram-icon'"
            :model-value="(values[f.name] as string) || null"
            @update:model-value="(v) => (values[f.name] = v ?? '')"
          />
          <input v-else v-model="values[f.name] as string" v-truncate-tooltip="String(values[f.name] ?? '')" :type="f.type" :required="f.required" />
        </label>
      </form>

      <div class="modal-foot">
        <button type="button" class="btn btn-secondary" :disabled="saving" @click="$emit('close')">Отмена</button>
        <button type="button" class="btn btn-primary" :disabled="saving || !fields.length" @click="submit">
          {{ saving ? 'Сохранение…' : 'Добавить' }}
        </button>
      </div>
    </div>
  </BaseModal>
</template>

<style scoped>
.modal {
  width: 100%;
  /* Фикс п.1.3.6: было 460px фиксированных — при form-grid: 1fr 1fr (см. ниже) каждое fk-поле
     получало только половину этой ширины, и длинные подписи (напр. "Тип устройства" после
     выбора, особенно с учётом фикса п.1.3.7 — "Cisco WS-C2960-48TD-L") обрезались. Верхняя
     граница текущего минимума не меняется (460px — тот же, что и раньше, на узких окнах), но
     теперь растёт вместе с viewport и на обычных десктопных экранах даёт полям вдвое больше
     места, не разрастаясь безгранично для типично короткой формы в 2-5 полей (в отличие от
     DeviceFormModal.vue, где clamp() уместен куда шире — там форма кардинально длиннее). */
  max-width: clamp(460px, 34vw, 640px);
  padding: 20px 22px 18px;
}
/* Одноколоночные формы (QUICK_ADD_SINGLE_COLUMN): окно шире стандартного, чтобы длинные подписи
   fk-полей (например, помещение в форме стойки) читались целиком. Объявлено после .modal — при
   равной специфичности побеждает более поздний блок. */
.modal-wide {
  max-width: clamp(520px, 44vw, 760px);
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
.form-grid-single {
  grid-template-columns: 1fr;
}
.field {
  /* min-width: 0 переопределяет дефолтный min-width: auto грид-элемента — без этого поле
     не может сжаться ниже intrinsic-ширины своего содержимого (см. ниже про select/input), и
     вся колонка, а с ней и .modal, распирает за пределы max-width. Тот же баг и тот же фикс,
     что в DeviceFormModal.vue (см. тамошний комментарий "без min-width:0..."). */
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
  /* width: 100% — без него input/textarea сами по себе не растягиваются на всю ширину ячейки
     грида, а берут intrinsic-ширину по содержимому, из-за чего поле физически вылезало за
     подложку модалки вбок вместо переноса текста/сжатия. Fk-поля стилизует сам SearchableSelect
     (см. SearchableSelect.vue) — обычный <select> в этой форме с п.4 больше не используется. */
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
