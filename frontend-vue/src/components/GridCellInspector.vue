<script setup lang="ts">
// Панель свойств справа от сетки — показывает либо настройки выбранной ЯЧЕЙКИ (тип содержимого,
// текст/путь поля, стиль), либо настройки выбранной СТРОКИ целиком (высота, повторение и источник
// данных). "Глупый" props-in/events-out компонент: не мутирует row/cell сам, только эмитит патчи —
// вся мутация состояния листа (sheets) остаётся в ReportGridEditorView.vue, как и updateRow() в
// DeviceInterfacesEditor.vue. Портировано из панели свойств в rbRenderGridEditor()
// (frontend/static/report_builder.js).
import { computed } from 'vue'
import type { GridCell, GridDataSource, GridDataSourceFilter, GridFilterOp, GridRow, ReportEntityMeta } from '../api/types'
import { entityLabel, flattenEntityPaths, indexEntitiesByKey } from '../utils/reportEntityPaths'

const props = defineProps<{
  mode: 'cell' | 'row'
  row: GridRow
  cell: GridCell // для mode='cell' — уже "ensured" родителем (может быть ещё не в row.cells, если позиция пуста)
  entities: ReportEntityMeta[]
}>()
const emit = defineEmits<{
  'update-row': [patch: Partial<GridRow>]
  'update-cell': [patch: Partial<GridCell>]
  'delete-cell': []
}>()

const entitiesByKey = computed(() => indexEntitiesByKey(props.entities))
const fieldPaths = computed(() => (props.row.data_source?.root_entity ? flattenEntityPaths(entitiesByKey.value, props.row.data_source.root_entity) : []))
const expandOptions = computed(() => {
  const rootEntity = props.row.data_source?.root_entity
  return rootEntity ? (entitiesByKey.value[rootEntity]?.to_many ?? []) : []
})

const FILTER_OPS: Array<[GridFilterOp, string]> = [
  ['eq', 'равно'],
  ['ne', 'не равно'],
  ['contains', 'содержит'],
  ['not_contains', 'не содержит'],
  ['not_empty', 'не пусто'],
  ['is_true', 'да/включено'],
  ['is_false', 'нет/выключено'],
]

function patchDataSource(patch: Partial<GridDataSource>) {
  if (!props.row.data_source) return
  emit('update-row', { data_source: { ...props.row.data_source, ...patch } })
}
function addFilter() {
  if (!props.row.data_source) return
  patchDataSource({ filters: [...props.row.data_source.filters, { path: '', op: 'eq', value: '' }] })
}
function removeFilter(fi: number) {
  if (!props.row.data_source) return
  patchDataSource({ filters: props.row.data_source.filters.filter((_, i) => i !== fi) })
}
function updateFilter(fi: number, patch: Partial<GridDataSourceFilter>) {
  if (!props.row.data_source) return
  patchDataSource({ filters: props.row.data_source.filters.map((f, i) => (i === fi ? { ...f, ...patch } : f)) })
}

function insertPath(path: string) {
  emit('update-cell', { path })
}

const staticTextHint = 'Текст (можно использовать {{report_date}} и параметры {{key}})'
</script>

<template>
  <div class="inspector">
    <template v-if="mode === 'row'">
      <h3>Строка</h3>
      <label class="field">
        <span>Высота</span>
        <input type="number" min="10" :value="row.height" @input="$emit('update-row', { height: Math.max(10, Number(($event.target as HTMLInputElement).value) || 20) })" />
      </label>

      <label class="checkbox-field">
        <input type="checkbox" :checked="row.repeat" @change="$emit('update-row', { repeat: ($event.target as HTMLInputElement).checked })" />
        <span>Повторяющаяся строка (клонируется по одной на каждую запись данных)</span>
      </label>

      <template v-if="row.repeat && row.data_source">
        <label class="field">
          <span>Сущность</span>
          <select :value="row.data_source.root_entity" @change="patchDataSource({ root_entity: ($event.target as HTMLSelectElement).value, expand: '' })">
            <option value="">— выберите сущность —</option>
            <option v-for="e in entities" :key="e.key" :value="e.key">{{ e.label }}</option>
          </select>
        </label>

        <label v-if="row.data_source.root_entity" class="field">
          <span>Разворачивать по связи "многие" (опционально)</span>
          <select :value="row.data_source.expand" @change="patchDataSource({ expand: ($event.target as HTMLSelectElement).value })">
            <option value="">— без разворачивания (1 строка на запись) —</option>
            <option v-for="rel in expandOptions" :key="rel.name" :value="rel.name">{{ rel.name }} → {{ entityLabel(entitiesByKey, rel.target) }}</option>
          </select>
        </label>

        <label class="checkbox-field">
          <input
            type="checkbox"
            :checked="row.data_source.include_empty_expand"
            @change="patchDataSource({ include_empty_expand: ($event.target as HTMLInputElement).checked })"
          />
          <span>Выводить запись и без элементов развёрнутой связи</span>
        </label>

        <label class="field">
          <span>Сортировка (путь поля)</span>
          <input type="text" :value="row.data_source.sort_by" @input="patchDataSource({ sort_by: ($event.target as HTMLInputElement).value })" />
        </label>

        <div class="filters-block">
          <div class="filters-head">
            <span>Фильтры</span>
            <button type="button" class="btn-mini" @click="addFilter">+ фильтр</button>
          </div>
          <div v-for="(f, fi) in row.data_source.filters" :key="fi" class="filter-row">
            <input type="text" placeholder="путь поля" :value="f.path" @input="updateFilter(fi, { path: ($event.target as HTMLInputElement).value })" />
            <select :value="f.op" @change="updateFilter(fi, { op: ($event.target as HTMLSelectElement).value as GridFilterOp })">
              <option v-for="[op, label] in FILTER_OPS" :key="op" :value="op">{{ label }}</option>
            </select>
            <input
              v-if="!['not_empty', 'is_true', 'is_false'].includes(f.op)"
              type="text"
              placeholder="значение"
              :value="f.value"
              @input="updateFilter(fi, { value: ($event.target as HTMLInputElement).value })"
            />
            <button type="button" class="icon-btn danger" aria-label="Удалить фильтр" @click="removeFilter(fi)">
              <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
            </button>
          </div>
        </div>
      </template>
    </template>

    <template v-else>
      <h3>Ячейка</h3>
      <label class="field">
        <span>Тип содержимого</span>
        <select :value="cell.kind" @change="$emit('update-cell', { kind: ($event.target as HTMLSelectElement).value as GridCell['kind'] })">
          <option value="static">Статический текст</option>
          <option value="field" :disabled="!row.repeat">Поле из БД (требует повторения строки)</option>
          <option value="index" :disabled="!row.repeat">№ записи (требует повторения строки)</option>
          <option value="formula">Формула Excel</option>
        </select>
      </label>

      <label v-if="cell.kind === 'static'" class="field">
        <span>{{ staticTextHint }}</span>
        <textarea :value="cell.text ?? ''" rows="2" @input="$emit('update-cell', { text: ($event.target as HTMLTextAreaElement).value })"></textarea>
      </label>

      <template v-if="cell.kind === 'field'">
        <label class="field">
          <span>Путь поля</span>
          <input type="text" :value="cell.path ?? ''" placeholder="например, name или building.name" @input="$emit('update-cell', { path: ($event.target as HTMLInputElement).value })" />
        </label>
        <label v-if="fieldPaths.length" class="field">
          <span>Вставить поле</span>
          <select @change="insertPath(($event.target as HTMLSelectElement).value); ($event.target as HTMLSelectElement).selectedIndex = 0">
            <option value="">— выбрать из списка —</option>
            <option v-for="p in fieldPaths" :key="p.path" :value="p.path">{{ p.label }}</option>
          </select>
        </label>
        <label class="field">
          <span>Разделитель (для списков)</span>
          <input type="text" :value="cell.separator ?? '; '" @input="$emit('update-cell', { separator: ($event.target as HTMLInputElement).value })" />
        </label>
      </template>

      <label v-if="cell.kind === 'formula'" class="field">
        <span>Формула (начинается с "=", Excel посчитает сам при открытии)</span>
        <input type="text" :value="cell.text ?? '='" @input="$emit('update-cell', { text: ($event.target as HTMLInputElement).value })" />
      </label>

      <p v-if="cell.kind === 'index'" class="hint-note">Порядковый номер записи внутри повторения строки, начиная с 1.</p>

      <div class="style-block">
        <b>Стиль</b>
        <div class="style-checks">
          <label><input type="checkbox" :checked="!!cell.style?.bold" @change="$emit('update-cell', { style: { ...cell.style, bold: ($event.target as HTMLInputElement).checked || undefined } })" /> Жирный</label>
          <label><input type="checkbox" :checked="!!cell.style?.italic" @change="$emit('update-cell', { style: { ...cell.style, italic: ($event.target as HTMLInputElement).checked || undefined } })" /> Курсив</label>
          <label><input type="checkbox" :checked="!!cell.style?.underline" @change="$emit('update-cell', { style: { ...cell.style, underline: ($event.target as HTMLInputElement).checked || undefined } })" /> Подчёркнутый</label>
          <label><input type="checkbox" :checked="cell.style?.wrap !== false" @change="$emit('update-cell', { style: { ...cell.style, wrap: ($event.target as HTMLInputElement).checked ? undefined : false } })" /> Перенос текста</label>
          <label><input type="checkbox" :checked="!!cell.style?.border" @change="$emit('update-cell', { style: { ...cell.style, border: ($event.target as HTMLInputElement).checked || undefined } })" /> Рамка</label>
        </div>
        <label class="field">
          <span>Выравнивание по горизонтали</span>
          <select :value="cell.style?.align ?? ''" @change="$emit('update-cell', { style: { ...cell.style, align: (($event.target as HTMLSelectElement).value || undefined) as 'left' | 'center' | 'right' | undefined } })">
            <option value="">По умолчанию</option>
            <option value="left">Слева</option>
            <option value="center">По центру</option>
            <option value="right">Справа</option>
          </select>
        </label>
        <label class="field">
          <span>Цвет фона (#RRGGBB)</span>
          <input type="text" :value="cell.style?.bg ?? ''" placeholder="#EEF2FF" @input="$emit('update-cell', { style: { ...cell.style, bg: ($event.target as HTMLInputElement).value || undefined } })" />
        </label>
        <label class="field">
          <span>Формат числа/даты</span>
          <input type="text" :value="cell.style?.number_format ?? ''" placeholder="0.00 или DD.MM.YYYY" @input="$emit('update-cell', { style: { ...cell.style, number_format: ($event.target as HTMLInputElement).value || undefined } })" />
        </label>
      </div>

      <button type="button" class="btn btn-secondary" @click="$emit('delete-cell')">Очистить ячейку</button>
    </template>
  </div>
</template>

<style scoped>
.inspector {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  background: var(--surface-2);
  border-radius: var(--r-m);
  border: 1px solid var(--border);
  min-width: 240px;
}
.inspector h3 {
  margin: 0;
  font-size: 12.5px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
}
.field input,
.field select,
.field textarea {
  background: var(--surface-1, #fff);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 6px 8px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
  resize: vertical;
}
.checkbox-field {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
  color: var(--ink);
}
.filters-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.filters-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: var(--ink-muted);
}
.btn-mini {
  border: 1px dashed var(--border);
  background: none;
  border-radius: var(--r-s);
  padding: 3px 8px;
  font-size: 11px;
  color: var(--brand);
  cursor: pointer;
}
.filter-row {
  display: grid;
  grid-template-columns: 1fr 100px 1fr 24px;
  gap: 5px;
  align-items: center;
}
.filter-row input,
.filter-row select {
  background: var(--surface-1, #fff);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 5px 6px;
  font-size: 11.5px;
}
.hint-note {
  font-size: 11px;
  color: var(--ink-muted);
  margin: 0;
}
.style-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px solid var(--border);
  padding-top: 10px;
}
.style-block b {
  font-size: 11px;
}
.style-checks {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11.5px;
}
.style-checks label {
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
