<script setup lang="ts">
// Визуальный grid-редактор листа Excel для шаблона конструктора отчётов (xlsx). Портирован с
// самого большого оставшегося блока vanilla-фронтенда (до 2.60.0:
// rbRenderGridEditor() и соседние rbXxx-функции) — тот же формат config.sheets (см.
// backend/app/services/report_grid.py), та же модель выделения/объединения, тот же набор типов
// ячеек. Главное отличие от vanilla — вставка полей БД по клику (select "Вставить поле" в
// GridCellInspector.vue), а не drag-and-drop: тот же результат, но надёжнее тестируется и
// доступнее с клавиатуры/скринридера. Word-шаблоны (.docx) редактируются отдельным экраном
// (ReportDocxEditorView.vue) — этот открывается только для format === 'xlsx', для docx
// показывает пояснение вместо сетки.
import { useRoute, useRouter } from 'vue-router'
import { useGridPreview } from '../composables/useGridPreview'
import { useGridTemplate } from '../composables/useGridTemplate'
import { useReportGrid } from '../composables/useReportGrid'
import { cellPreview } from '../utils/reportGridModel'
import GridCellInspector from '../components/GridCellInspector.vue'
import GridPreviewTable from '../components/GridPreviewTable.vue'

const route = useRoute()
const router = useRouter()
const templateId = route.params.id as string

// Редактирование сетки (листы, колонки, строки, выделение, объединение, инспектор) — composables/useReportGrid.ts.
const {
  sheets,
  activeSheet,
  selected,
  curSheet,
  inspectorMode,
  inspectorRow,
  inspectorCell,
  switchSheet,
  addSheet,
  removeSheet,
  addColumn,
  removeColumn,
  setColWidth,
  addRowAt,
  removeRow,
  selectCell,
  selectRow,
  isSelectedCell,
  isInRange,
  visibleCellsForRow,
  mergeSelection,
  unmergeSelected,
  onUpdateRow,
  onUpdateCell,
  onDeleteCell,
} = useReportGrid()

// Загрузка и сохранение шаблона — composables/useGridTemplate.ts.
const { loading, saving, errorMessage, template, entities, name, description, save } = useGridTemplate(templateId, sheets)

function backToList() {
  router.push('/report-templates')
}

// ---------- Предпросмотр ----------

const { previewOpen, previewLoading, previewError, previewResult, runPreview, closePreview } = useGridPreview(sheets)
</script>

<template>
  <div class="editor-view">
    <p v-if="loading" class="loading-hint">Загрузка шаблона…</p>

    <template v-else-if="errorMessage && !template">
      <div class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>
      <button type="button" class="btn btn-secondary" @click="backToList">← К списку шаблонов</button>
    </template>

    <template v-else-if="template && template.format !== 'xlsx'">
      <p class="scope-note">
        Шаблон «{{ template.name }}» — в формате Word (.docx). У него другой редактор — вернитесь к списку и откройте «Конструктор» ещё раз.
      </p>
      <button type="button" class="btn btn-secondary" @click="backToList">← К списку шаблонов</button>
    </template>

    <template v-else-if="template">
      <div class="top-bar">
        <button type="button" class="btn btn-secondary" @click="backToList">← К списку шаблонов</button>
        <label class="field">
          <span>Название</span>
          <input v-model.trim="name" type="text" />
        </label>
        <label class="field field-wide">
          <span>Описание</span>
          <input v-model.trim="description" type="text" />
        </label>
        <button type="button" class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? 'Сохранение…' : 'Сохранить' }}
        </button>
      </div>

      <div v-if="errorMessage" class="form-error">
        <svg class="icon"><use href="/icons.svg#i-alert" /></svg>
        {{ errorMessage }}
      </div>

      <div class="sheet-tabs">
        <button v-for="(sheet, si) in sheets" :key="si" type="button" class="sheet-tab" :class="{ active: si === activeSheet }" @click="switchSheet(si)">
          {{ sheet.title || `Лист ${si + 1}` }}
        </button>
        <button type="button" class="sheet-tab add" @click="addSheet">+ лист</button>
      </div>

      <div class="sheet-toolbar">
        <label class="field">
          <span>Название листа</span>
          <input :value="curSheet.title" type="text" @input="curSheet.title = ($event.target as HTMLInputElement).value" />
        </label>
        <button type="button" class="btn-mini" @click="removeSheet(activeSheet)">Удалить лист</button>
        <button type="button" class="btn-mini" @click="addColumn">+ колонка</button>
        <button type="button" class="btn-mini" @click="mergeSelection">Объединить</button>
        <button type="button" class="btn-mini" @click="unmergeSelected">Разъединить</button>
        <button type="button" class="btn-mini" @click="runPreview">Предпросмотр</button>
      </div>

      <div class="editor-body">
        <div class="grid-wrap">
          <table class="grid-table">
            <thead>
              <tr>
                <th class="row-head"></th>
                <th v-for="(col, ci) in curSheet.columns" :key="ci" class="col-head">
                  <input type="number" min="4" :value="col.width" @input="setColWidth(ci, ($event.target as HTMLInputElement).value)" />
                  <button type="button" aria-label="Удалить колонку" @click="removeColumn(ci)">×</button>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, ri) in curSheet.rows" :key="ri">
                <td class="row-head" :class="{ selected: selected?.row === ri && selected?.col === null }" @click="selectRow(ri)">
                  <span v-if="row.repeat" class="repeat-badge" title="Повторяющаяся строка">↻</span>
                  {{ ri + 1 }}
                  <button type="button" aria-label="Добавить строку ниже" @click.stop="addRowAt(ri)">+</button>
                  <button type="button" aria-label="Удалить строку" @click.stop="removeRow(ri)">×</button>
                </td>
                <template v-for="{ col, cell } in visibleCellsForRow(ri)" :key="col">
                  <td
                    class="grid-cell"
                    :class="{ selected: isSelectedCell(ri, col), 'in-range': isInRange(ri, col) }"
                    :colspan="cell?.colspan || 1"
                    :rowspan="cell?.rowspan || 1"
                    @click="selectCell(ri, col, $event)"
                  >
                    {{ cellPreview(cell) }}
                  </td>
                </template>
              </tr>
            </tbody>
          </table>
        </div>

        <GridCellInspector
          v-if="inspectorMode && inspectorRow"
          :mode="inspectorMode"
          :row="inspectorRow"
          :cell="inspectorCell ?? { col: 0, kind: 'static', text: '', style: {} }"
          :entities="entities"
          @update-row="onUpdateRow"
          @update-cell="onUpdateCell"
          @delete-cell="onDeleteCell"
        />
        <div v-else class="inspector-placeholder">Выберите ячейку или строку, чтобы увидеть свойства.</div>
      </div>

      <div v-if="previewOpen" class="preview-panel">
        <div class="preview-panel-head">
          <b>Предпросмотр (первые записи каждой повторяющейся строки)</b>
          <button type="button" class="icon-btn" aria-label="Закрыть предпросмотр" @click="closePreview">
            <svg class="icon"><use href="/icons.svg#i-x" /></svg>
          </button>
        </div>
        <p v-if="previewLoading" class="loading-hint">Строим предпросмотр…</p>
        <p v-else-if="previewError" class="form-error">{{ previewError }}</p>
        <div v-else-if="previewResult" class="preview-sections">
          <GridPreviewTable v-for="(section, si) in previewResult.sections" :key="si" :section="section" />
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.editor-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.loading-hint,
.scope-note {
  font-size: 12.5px;
  color: var(--ink-muted);
}
.scope-note {
  background: var(--surface-2);
  border-radius: var(--r-s);
  padding: 10px 12px;
}
.scope-note code {
  font-family: var(--font-mono);
}
.top-bar {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ink-muted);
}
.field input {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  padding: 7px 9px;
  font-size: 12.5px;
  color: var(--ink);
  font-family: inherit;
}
.field-wide {
  flex: 1;
  min-width: 200px;
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
}
.sheet-tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.sheet-tab {
  border: 1px solid var(--border);
  background: var(--surface-2);
  border-radius: var(--r-s) var(--r-s) 0 0;
  padding: 7px 12px;
  font-size: 12px;
  color: var(--ink-muted);
  cursor: pointer;
}
.sheet-tab.active {
  background: var(--surface-1, #fff);
  color: var(--ink);
  font-weight: 600;
  border-bottom-color: transparent;
}
.sheet-tab.add {
  color: var(--brand);
}
.sheet-toolbar {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px;
  background: var(--surface-2);
  border-radius: var(--r-s);
}
.btn-mini {
  border: 1px dashed var(--border);
  background: none;
  border-radius: var(--r-s);
  padding: 6px 10px;
  font-size: 11.5px;
  color: var(--brand);
  cursor: pointer;
  align-self: flex-end;
}
.editor-body {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}
.grid-wrap {
  overflow: auto;
  flex: 1;
  border: 1px solid var(--border);
  border-radius: var(--r-s);
}
.grid-table {
  border-collapse: collapse;
}
.grid-table th,
.grid-table td {
  border: 1px solid var(--border);
  padding: 4px 6px;
  font-size: 11.5px;
  white-space: nowrap;
}
.col-head {
  background: var(--surface-2);
}
.col-head input {
  width: 44px;
  border: 1px solid var(--border);
  border-radius: 3px;
  font-size: 11px;
}
.row-head {
  background: var(--surface-2);
  cursor: pointer;
  text-align: center;
  min-width: 60px;
}
.row-head.selected {
  background: var(--brand-soft, rgba(99, 102, 241, 0.15));
}
.repeat-badge {
  color: var(--brand);
  margin-right: 2px;
}
.grid-cell {
  cursor: pointer;
  min-width: 60px;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.grid-cell.selected {
  outline: 2px solid var(--brand);
  outline-offset: -2px;
}
.grid-cell.in-range {
  background: var(--brand-soft, rgba(99, 102, 241, 0.12));
}
.inspector-placeholder {
  min-width: 240px;
  padding: 20px 12px;
  text-align: center;
  font-size: 11.5px;
  color: var(--ink-muted);
  background: var(--surface-2);
  border-radius: var(--r-m);
  border: 1px dashed var(--border);
}
.preview-panel {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.preview-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.preview-panel-head b {
  font-size: 12.5px;
}
.preview-sections {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
