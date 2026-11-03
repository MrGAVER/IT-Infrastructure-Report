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
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getReportEntities } from '../api/reportEntities'
import { previewGridConfig } from '../api/reportPreview'
import { getReportTemplate, saveReportTemplate } from '../api/reportTemplates'
import type { GridCell, GridConfig, GridPreviewResponse, GridRow, GridSheet, ReportEntityMeta, ReportTemplate } from '../api/types'
import { useToast } from '../composables/useToast'
import { coverageForRows, selectionRect, visibleCellsForRow as visibleCellsForRowShared } from '../utils/gridCoverage'
import GridCellInspector from '../components/GridCellInspector.vue'
import GridPreviewTable from '../components/GridPreviewTable.vue'

const route = useRoute()
const router = useRouter()
const { notify } = useToast()
const templateId = route.params.id as string

const loading = ref(true)
const saving = ref(false)
const errorMessage = ref<string | null>(null)
const template = ref<ReportTemplate | null>(null)
const entities = ref<ReportEntityMeta[]>([])

const name = ref('')
const description = ref('')
const sheets = ref<GridSheet[]>([])
const activeSheet = ref(0)
const selected = ref<{ row: number; col: number | null } | null>(null)
const rangeEnd = ref<{ row: number; col: number } | null>(null)

function newRow(repeat = false): GridRow {
  return { height: 20, repeat, data_source: repeat ? { root_entity: '', expand: '', include_empty_expand: true, filters: [], sort_by: '' } : null, cells: [] }
}
function newSheet(n: number): GridSheet {
  const cols = 6
  return {
    title: `Лист ${n}`,
    columns: Array.from({ length: cols }, () => ({ width: 20 })),
    rows: [
      {
        height: 24,
        repeat: false,
        data_source: null,
        cells: [{ col: 0, colspan: cols, kind: 'static', text: 'Новый лист', style: { bold: true, align: 'center', bg: '#EEF2FF' } }],
      },
      newRow(true),
    ],
  }
}

onMounted(async () => {
  try {
    const [t, e] = await Promise.all([getReportTemplate(templateId), getReportEntities()])
    template.value = t
    entities.value = e
    name.value = t.name
    description.value = t.description ?? ''
    const cfg = t.config as unknown as GridConfig
    sheets.value = cfg.sheets && cfg.sheets.length ? cfg.sheets : [newSheet(1)]
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось загрузить шаблон'
  } finally {
    loading.value = false
  }
})

const curSheet = computed(() => sheets.value[activeSheet.value])

// ---------- Листы ----------

function switchSheet(si: number) {
  activeSheet.value = si
  selected.value = null
  rangeEnd.value = null
}
function addSheet() {
  sheets.value.push(newSheet(sheets.value.length + 1))
  activeSheet.value = sheets.value.length - 1
  selected.value = null
  rangeEnd.value = null
}
function removeSheet(si: number) {
  if (sheets.value.length <= 1) {
    notify('В шаблоне должен остаться хотя бы один лист.', 'error')
    return
  }
  if (!confirm('Удалить лист целиком со всеми ячейками?')) return
  sheets.value.splice(si, 1)
  if (activeSheet.value >= sheets.value.length) activeSheet.value = sheets.value.length - 1
  selected.value = null
  rangeEnd.value = null
}

// ---------- Колонки ----------

function addColumn() {
  curSheet.value.columns.push({ width: 20 })
}
function removeColumn(ci: number) {
  const sheet = curSheet.value
  if (sheet.columns.length <= 1) {
    notify('На листе должна остаться хотя бы одна колонка.', 'error')
    return
  }
  const hasContent = sheet.rows.some((r) => r.cells.some((c) => c.col === ci || (c.col < ci && c.col + (c.colspan || 1) > ci)))
  if (hasContent && !confirm('В этой колонке (или в объединении через неё) есть содержимое — удалить вместе с колонкой?')) return
  for (const row of sheet.rows) {
    row.cells = row.cells.filter((c) => c.col !== ci).map((c) => (c.col > ci ? { ...c, col: c.col - 1 } : c))
    for (const c of row.cells) {
      const span = c.colspan || 1
      if (c.col < ci && c.col + span > ci) c.colspan = Math.max(1, span - 1)
    }
  }
  sheet.columns.splice(ci, 1)
  selected.value = null
  rangeEnd.value = null
}
function setColWidth(ci: number, v: string) {
  curSheet.value.columns[ci].width = Math.max(4, Number(v) || 20)
}

// ---------- Строки ----------

function addRowAt(ri: number) {
  const sheet = curSheet.value
  const insertAt = ri + 1
  // Объединения по вертикали, "перешагивающие" точку вставки, растягиваем на 1 — иначе новая
  // строка окажется внутри визуально разорванного объединения (см. report_grid.py: rowspan не
  // может "перепрыгивать" границу вставки без соответствующей растяжки).
  for (let r = 0; r < insertAt; r++) {
    for (const c of sheet.rows[r].cells) {
      const span = c.rowspan || 1
      if (r + span > insertAt) c.rowspan = span + 1
    }
  }
  sheet.rows.splice(insertAt, 0, newRow(false))
}
function removeRow(ri: number) {
  const sheet = curSheet.value
  if (sheet.rows.length <= 1) {
    notify('На листе должна остаться хотя бы одна строка.', 'error')
    return
  }
  if (sheet.rows[ri].cells.length && !confirm('В строке есть содержимое — удалить вместе со строкой?')) return
  for (let r = 0; r < ri; r++) {
    for (const c of sheet.rows[r].cells) {
      const span = c.rowspan || 1
      if (r + span > ri) c.rowspan = Math.max(1, span - 1)
    }
  }
  sheet.rows.splice(ri, 1)
  selected.value = null
  rangeEnd.value = null
}

// ---------- Выделение ----------

function cellAt(row: GridRow, col: number): GridCell | undefined {
  return row.cells.find((c) => c.col === col)
}
function selectCell(ri: number, ci: number, ev?: MouseEvent) {
  if (ev?.shiftKey && selected.value && selected.value.col !== null) {
    rangeEnd.value = { row: ri, col: ci }
  } else {
    selected.value = { row: ri, col: ci }
    rangeEnd.value = null
  }
}
function selectRow(ri: number) {
  selected.value = { row: ri, col: null }
  rangeEnd.value = null
}
const rect = computed(() => selectionRect(selected.value, rangeEnd.value))
function isSelectedCell(ri: number, ci: number): boolean {
  return selected.value?.row === ri && selected.value?.col === ci
}
function isInRange(ri: number, ci: number): boolean {
  const r = rect.value
  return !!r && ri >= r.r1 && ri <= r.r2 && ci >= r.c1 && ci <= r.c2
}

/** Обёртка над общей utils/gridCoverage.ts:visibleCellsForRow — здесь просто фиксирует
 * "текущий лист" как источник строк/числа колонок, чтобы вызывать из шаблона без лишних
 * аргументов. Общая функция также используется GridPreviewTable.vue (предпросмотр) — тот же
 * алгоритм обхода поверх другого типа ячеек (GridPreviewCell вместо GridCell). */
function visibleCellsForRow(ri: number): Array<{ col: number; cell: GridCell | null }> {
  return visibleCellsForRowShared(curSheet.value.rows, ri, curSheet.value.columns.length)
}

function cellPreview(cell: GridCell | null): string {
  if (!cell) return ''
  if (cell.kind === 'static') return cell.text || ''
  if (cell.kind === 'field') return cell.path ? `{${cell.path}}` : '{…}'
  if (cell.kind === 'index') return '№'
  return cell.text || '='
}

// ---------- Объединение ----------

function mergeSelection() {
  const sheet = curSheet.value
  const r = rect.value
  if (!r) {
    notify('Выделите диапазон: кликните первую ячейку, затем Shift+клик по последней.', 'error')
    return
  }
  const { r1, r2, c1, c2 } = r
  if (r1 === r2 && c1 === c2) {
    notify('Выделите больше одной ячейки для объединения.', 'error')
    return
  }
  if (r2 > r1) {
    for (let ri = r1; ri <= r2; ri++) {
      if (sheet.rows[ri].repeat) {
        notify('Нельзя объединять по вертикали через повторяющуюся строку.', 'error')
        return
      }
    }
  }
  const anchorExisting = cellAt(sheet.rows[r1], c1)
  const toRemove: Array<[number, GridCell]> = []
  for (let ri = r1; ri <= r2; ri++) {
    for (const c of sheet.rows[ri].cells) {
      const within = c.col >= c1 && c.col + (c.colspan || 1) - 1 <= c2
      if (within && !(ri === r1 && c.col === c1)) toRemove.push([ri, c])
    }
  }
  if (toRemove.length && !confirm('Внутри диапазона есть другие ячейки с содержимым — они будут удалены при объединении. Продолжить?')) return
  for (const [ri, c] of toRemove) {
    const row = sheet.rows[ri]
    row.cells.splice(row.cells.indexOf(c), 1)
  }
  const anchor: GridCell = anchorExisting ?? { col: c1, kind: 'static', text: '', style: {} }
  anchor.colspan = c2 - c1 + 1
  anchor.rowspan = r2 - r1 + 1
  if (!anchorExisting) sheet.rows[r1].cells.push(anchor)
  selected.value = { row: r1, col: c1 }
  rangeEnd.value = null
}
function unmergeSelected() {
  if (!selected.value || selected.value.col === null) {
    notify('Выберите объединённую ячейку.', 'error')
    return
  }
  const cell = cellAt(curSheet.value.rows[selected.value.row], selected.value.col)
  if (!cell || ((cell.colspan || 1) === 1 && (cell.rowspan || 1) === 1)) {
    notify('Выбранная ячейка не объединена.', 'error')
    return
  }
  cell.colspan = 1
  cell.rowspan = 1
}

// ---------- Содержимое ячейки / строки (из GridCellInspector.vue) ----------

function ensureCell(ri: number, ci: number): GridCell {
  const row = curSheet.value.rows[ri]
  let cell = cellAt(row, ci)
  if (!cell) {
    cell = { col: ci, kind: 'static', text: '', style: {} }
    row.cells.push(cell)
  }
  return cell
}

const inspectorMode = computed<'row' | 'cell' | null>(() => {
  if (!selected.value) return null
  return selected.value.col === null ? 'row' : 'cell'
})
const inspectorRow = computed<GridRow | null>(() => (selected.value ? curSheet.value.rows[selected.value.row] : null))
const inspectorCell = computed<GridCell | null>(() => {
  if (!selected.value || selected.value.col === null) return null
  return cellAt(curSheet.value.rows[selected.value.row], selected.value.col) ?? { col: selected.value.col, kind: 'static', text: '', style: {} }
})

function onUpdateRow(patch: Partial<GridRow>) {
  if (!selected.value) return
  const row = curSheet.value.rows[selected.value.row]
  if (patch.repeat !== undefined && patch.repeat !== row.repeat) {
    if (patch.repeat) {
      if (coverageForRows(curSheet.value.rows, selected.value.row).size) {
        notify('Эта строка частично охвачена вертикальным объединением сверху — сначала разъедините ячейки.', 'error')
        return
      }
      if (row.cells.some((c) => (c.rowspan || 1) > 1)) {
        notify('В строке есть вертикальное объединение — сначала разъедините ячейки, затем включите повторение.', 'error')
        return
      }
      row.repeat = true
      row.data_source = { root_entity: '', expand: '', include_empty_expand: true, filters: [], sort_by: '' }
    } else {
      const hadBound = row.cells.some((c) => c.kind === 'field' || c.kind === 'index')
      if (hadBound && !confirm('В строке есть ячейки, привязанные к данным (поле/№) — при отключении повторения они станут пустым текстом. Продолжить?')) return
      for (const c of row.cells) {
        if (c.kind === 'field' || c.kind === 'index') {
          c.kind = 'static'
          c.text = ''
          delete c.path
        }
      }
      row.repeat = false
      row.data_source = null
    }
    return
  }
  Object.assign(row, patch)
}

function onUpdateCell(patch: Partial<GridCell>) {
  if (!selected.value || selected.value.col === null) return
  const row = curSheet.value.rows[selected.value.row]
  if (patch.kind && (patch.kind === 'field' || patch.kind === 'index') && !row.repeat) {
    notify('Поле из БД и «№» обычно нужны в повторяющейся строке — отметьте строку как повторяющуюся в панели справа.', 'info')
  }
  const cell = ensureCell(selected.value.row, selected.value.col)
  Object.assign(cell, patch)
  if (patch.kind === 'field') {
    if (cell.path === undefined) cell.path = ''
    if (cell.separator === undefined) cell.separator = '; '
    delete cell.text
  }
  if (patch.kind === 'formula' && !cell.text) cell.text = '='
  if (patch.kind === 'static' && cell.text === undefined) cell.text = ''
  if (patch.kind === 'index') {
    delete cell.path
    delete cell.text
  }
}
function onDeleteCell() {
  if (!selected.value || selected.value.col === null) return
  const row = curSheet.value.rows[selected.value.row]
  const cell = cellAt(row, selected.value.col)
  if (!cell) return
  row.cells.splice(row.cells.indexOf(cell), 1)
}

// ---------- Сохранение ----------

async function save() {
  errorMessage.value = null
  if (!name.value.trim()) {
    errorMessage.value = 'Укажите название шаблона.'
    return
  }
  saving.value = true
  try {
    const config: GridConfig = { sheets: sheets.value }
    await saveReportTemplate(templateId, {
      name: name.value.trim(),
      description: description.value.trim() || null,
      format: 'xlsx',
      config: config as unknown as Record<string, unknown>,
    })
    notify('Шаблон сохранён', 'success')
  } catch (err) {
    errorMessage.value = err instanceof Error ? err.message : 'Не удалось сохранить шаблон'
  } finally {
    saving.value = false
  }
}

function backToList() {
  router.push('/report-templates')
}

// ---------- Предпросмотр ----------

const previewOpen = ref(false)
const previewLoading = ref(false)
const previewError = ref<string | null>(null)
const previewResult = ref<GridPreviewResponse | null>(null)

async function runPreview() {
  previewOpen.value = true
  previewError.value = null
  previewLoading.value = true
  try {
    previewResult.value = await previewGridConfig({ sheets: sheets.value } as unknown as Record<string, unknown>)
  } catch (err) {
    previewError.value = err instanceof Error ? err.message : 'Не удалось построить предпросмотр'
  } finally {
    previewLoading.value = false
  }
}
function closePreview() {
  previewOpen.value = false
}
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
