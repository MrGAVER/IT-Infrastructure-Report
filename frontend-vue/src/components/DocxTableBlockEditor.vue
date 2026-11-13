<script setup lang="ts">
// Свойства блока "Таблица" в docx-редакторе (ReportDocxEditorView.vue) — сущность, циклический
// вывод по связи, сортировка, фильтры, колонки. Props-in/events-out, тот же принцип, что
// GridCellInspector.vue: не мутирует block сам, только эмитит патчи. Портировано из
// rbTableBlockHTML()/rbSetTableEntity()/rbAddTableColumn() и соседних rbXxx-функций
// прежнего vanilla-фронтенда (до 2.60.0).
import { computed } from 'vue'
import type { DocxTableBlock, DocxTableColumn, GridDataSourceFilter, GridFilterOp, ReportEntityMeta } from '../api/types'
import { entityLabel, flattenEntityPaths, indexEntitiesByKey } from '../utils/reportEntityPaths'
import { FILTER_OPS, FILTER_OPS_WITHOUT_VALUE } from '../utils/reportFilterOps'

const props = defineProps<{ block: DocxTableBlock; entities: ReportEntityMeta[] }>()
const emit = defineEmits<{ update: [patch: Partial<DocxTableBlock>] }>()

const entitiesByKey = computed(() => indexEntitiesByKey(props.entities))
const fieldPaths = computed(() => (props.block.root_entity ? flattenEntityPaths(entitiesByKey.value, props.block.root_entity) : []))
const expandOptions = computed(() => (props.block.root_entity ? (entitiesByKey.value[props.block.root_entity]?.to_many ?? []) : []))

// Смена сущности инвалидирует пути колонок/фильтров/сортировки (они относятся к прежней сущности)
// — предупреждаем и сбрасываем, а не оставляем битые пути молча. Портировано из rbSetTableEntity().
function setEntity(newEntity: string) {
  const hasContent = props.block.columns.some((c) => c.source === 'field' && c.path) || props.block.filters.length > 0 || !!props.block.sort_by
  if (hasContent && props.block.root_entity && props.block.root_entity !== newEntity) {
    if (!confirm('Смена сущности сбросит пути колонок, фильтры и сортировку таблицы (они относятся к прежней сущности). Продолжить?')) return
    emit('update', {
      root_entity: newEntity,
      expand: '',
      columns: props.block.columns.map((c) => (c.source === 'field' ? { ...c, path: '' } : c)),
      filters: [],
      sort_by: '',
    })
    return
  }
  emit('update', { root_entity: newEntity, expand: '' })
}

function addFilter() {
  emit('update', { filters: [...props.block.filters, { path: '', op: 'eq', value: '' }] })
}
function removeFilter(fi: number) {
  emit('update', { filters: props.block.filters.filter((_, i) => i !== fi) })
}
function updateFilter(fi: number, patch: Partial<GridDataSourceFilter>) {
  emit('update', { filters: props.block.filters.map((f, i) => (i === fi ? { ...f, ...patch } : f)) })
}

function addColumn() {
  emit('update', { columns: [...props.block.columns, { header: '', source: 'field', path: '', separator: '; ' }] })
}
function removeColumn(ci: number) {
  emit('update', { columns: props.block.columns.filter((_, i) => i !== ci) })
}
function updateColumn(ci: number, patch: Partial<DocxTableColumn>) {
  emit('update', { columns: props.block.columns.map((c, i) => (i === ci ? { ...c, ...patch } : c)) })
}
function moveColumn(ci: number, dir: -1 | 1) {
  const cols = [...props.block.columns]
  const cj = ci + dir
  if (cj < 0 || cj >= cols.length) return
  ;[cols[ci], cols[cj]] = [cols[cj], cols[ci]]
  emit('update', { columns: cols })
}
function setColumnSource(ci: number, source: DocxTableColumn['source']) {
  const col = props.block.columns[ci]
  const patch: Partial<DocxTableColumn> = { source }
  if (source === 'field') {
    patch.path = col.path ?? ''
    patch.separator = col.separator ?? '; '
  }
  if (source === 'static') patch.value = col.value ?? ''
  updateColumn(ci, patch)
}
</script>

<template>
  <div class="table-block">
    <label class="field">
      <span>Заголовок таблицы (только для предпросмотра — в документе добавьте отдельный блок «Заголовок» перед таблицей)</span>
      <input type="text" :value="block.title ?? ''" @input="$emit('update', { title: ($event.target as HTMLInputElement).value })" />
    </label>

    <div class="row">
      <label class="field">
        <span>Сущность</span>
        <select :value="block.root_entity" @change="setEntity(($event.target as HTMLSelectElement).value)">
          <option value="">— выберите сущность —</option>
          <option v-for="e in entities" :key="e.key" :value="e.key">{{ e.label }}</option>
        </select>
      </label>
      <label class="field">
        <span>Циклический вывод по связи (опционально)</span>
        <select :value="block.expand ?? ''" :disabled="!block.root_entity" @change="$emit('update', { expand: ($event.target as HTMLSelectElement).value })">
          <option value="">— одна запись = одна таблица целиком —</option>
          <option v-for="rel in expandOptions" :key="rel.name" :value="rel.name">{{ rel.name }} → {{ entityLabel(entitiesByKey, rel.target) }}</option>
        </select>
      </label>
      <label class="checkbox-field">
        <input
          type="checkbox"
          :checked="block.include_empty_expand !== false"
          :disabled="!block.expand"
          @change="$emit('update', { include_empty_expand: ($event.target as HTMLInputElement).checked })"
        />
        <span>Выводить и без элементов связи</span>
      </label>
    </div>

    <label class="field">
      <span>Сортировка (необязательно)</span>
      <div class="path-row">
        <input type="text" :value="block.sort_by ?? ''" @input="$emit('update', { sort_by: ($event.target as HTMLInputElement).value })" />
        <select
          v-if="fieldPaths.length"
          @change="
            $emit('update', { sort_by: ($event.target as HTMLSelectElement).value })
            ;($event.target as HTMLSelectElement).selectedIndex = 0
          "
        >
          <option value="">Вставить поле…</option>
          <option v-for="p in fieldPaths" :key="p.path" :value="p.path">{{ p.label }}</option>
        </select>
      </div>
    </label>

    <div class="sub-block">
      <div class="sub-head">
        <b>Фильтры</b>
        <button type="button" class="btn-mini" :disabled="!block.root_entity" @click="addFilter">+ фильтр</button>
      </div>
      <p v-if="!block.filters.length" class="empty">Фильтров нет — выводятся все записи.</p>
      <div v-for="(f, fi) in block.filters" :key="fi" class="filter-row">
        <input type="text" placeholder="путь поля" :value="f.path" @input="updateFilter(fi, { path: ($event.target as HTMLInputElement).value })" />
        <select :value="f.op" @change="updateFilter(fi, { op: ($event.target as HTMLSelectElement).value as GridFilterOp })">
          <option v-for="[op, label] in FILTER_OPS" :key="op" :value="op">{{ label }}</option>
        </select>
        <input
          v-if="!FILTER_OPS_WITHOUT_VALUE.includes(f.op)"
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

    <div class="sub-block">
      <div class="sub-head">
        <b>Колонки</b>
        <button type="button" class="btn-mini" :disabled="!block.root_entity" @click="addColumn">+ колонка</button>
      </div>
      <p v-if="!block.columns.length" class="empty">Колонок нет — добавьте кнопкой выше.</p>
      <div v-for="(c, ci) in block.columns" :key="ci" class="column-row">
        <input type="text" placeholder="заголовок колонки" :value="c.header" @input="updateColumn(ci, { header: ($event.target as HTMLInputElement).value })" />
        <select :value="c.source" @change="setColumnSource(ci, ($event.target as HTMLSelectElement).value as DocxTableColumn['source'])">
          <option value="field">Поле из БД</option>
          <option value="static">Статический текст</option>
          <option value="index">№ по порядку</option>
        </select>

        <div v-if="c.source === 'field'" class="column-value">
          <input type="text" placeholder="путь поля" :value="c.path ?? ''" @input="updateColumn(ci, { path: ($event.target as HTMLInputElement).value })" />
          <input
            type="text"
            placeholder="разделитель"
            :value="c.separator ?? '; '"
            @input="updateColumn(ci, { separator: ($event.target as HTMLInputElement).value })"
          />
        </div>
        <div v-else-if="c.source === 'static'" class="column-value">
          <input
            type="text"
            placeholder="текст (можно {{параметр}})"
            :value="c.value ?? ''"
            @input="updateColumn(ci, { value: ($event.target as HTMLInputElement).value })"
          />
        </div>
        <div v-else class="column-value empty">— порядковый номер строки —</div>

        <div class="column-actions">
          <button type="button" aria-label="Сдвинуть колонку влево" :disabled="ci === 0" @click="moveColumn(ci, -1)">←</button>
          <button type="button" aria-label="Сдвинуть колонку вправо" :disabled="ci === block.columns.length - 1" @click="moveColumn(ci, 1)">→</button>
          <button type="button" class="icon-btn danger" aria-label="Удалить колонку" @click="removeColumn(ci)">
            <svg class="icon"><use href="/icons.svg#i-trash" /></svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.table-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
}
.field input,
.field select {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 9px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
}
.row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: flex-end;
}
.row .field {
  flex: 1;
  min-width: 180px;
}
.checkbox-field {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--ink);
  padding-bottom: 8px;
}
.path-row {
  display: flex;
  gap: 6px;
}
.path-row input {
  flex: 1;
  min-width: 0;
}
/* Размер select — по самому длинному пути поля (до 750 px): без потолка он не сжимался и раздвигал страницу вбок. Список при
   открытии показывает варианты целиком, а в самой строке достаточно «Вставить поле…». */
.path-row select {
  min-width: 0;
  max-width: 55%;
}
.sub-block {
  border-top: 1px solid var(--border);
  padding-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sub-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sub-head b {
  font-size: 11.5px;
}
.btn-mini {
  border: 1px dashed var(--border);
  background: none;
  border-radius: var(--r-s);
  padding: 4px 9px;
  font-size: 11px;
  color: var(--brand);
  cursor: pointer;
}
.btn-mini:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.empty {
  font-size: 11px;
  color: var(--ink-muted);
  margin: 0;
}
.filter-row {
  display: grid;
  /* minmax(0, …): у «1fr» минимум — собственная ширина поля ввода, и на телефоне строка раздвигала страницу вбок. */
  grid-template-columns: minmax(0, 1fr) 110px minmax(0, 1fr) 24px;
  gap: 5px;
  align-items: center;
}
.filter-row input,
.filter-row select {
  min-width: 0;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 5px 6px;
  font-size: 11.5px;
}
.column-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 130px minmax(0, 1.6fr) auto;
  gap: 6px;
  align-items: center;
  padding: 6px;
  background: var(--surface-2);
  border-radius: var(--r-s);
}
.column-row input,
.column-row select {
  min-width: 0;
  background: var(--surface-1, #fff);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 5px 6px;
  font-size: 11.5px;
}
.column-value {
  display: flex;
  gap: 5px;
  min-width: 0;
}
.column-value input {
  flex: 1;
}
.column-value.empty {
  color: var(--ink-muted);
  font-size: 11px;
  align-items: center;
}
.column-actions {
  display: flex;
  gap: 3px;
}
.column-actions button {
  border: none;
  background: none;
  color: var(--ink-muted);
  border-radius: var(--r-s);
  width: 22px;
  height: 22px;
  cursor: pointer;
}
.column-actions button:hover:not(:disabled) {
  color: var(--brand);
  background: var(--surface-1, #fff);
}
.column-actions button:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* Телефон: четыре колонки в одну строку не помещаются — заголовок и источник рядом, значение и кнопки ниже на всю ширину. */
@media (max-width: 640px) {
  .column-row {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }
  .column-value,
  .column-actions {
    grid-column: 1 / -1;
  }
  .column-actions {
    justify-content: flex-end;
  }
  .filter-row {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 24px;
  }
  .filter-row input:first-child {
    grid-column: 1 / -1;
  }
  .filter-row button {
    grid-column: 3;
  }
}
</style>
