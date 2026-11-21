// Состояние и операции grid-редактора листа Excel (конструктор отчётов): листы, колонки, строки, выделение и объединение ячеек,
// правка выбранной ячейки/строки через инспектор. Вынесено из ReportGridEditorView.vue без изменения поведения — представление осталось
// отвечать за загрузку шаблона, сохранение и разметку. Формат config.sheets — backend/app/services/report_grid.py.
import { computed, ref } from 'vue'
import type { GridCell, GridRow, GridSheet } from '../api/types'
import { coverageForRows, selectionRect, visibleCellsForRow as visibleCellsForRowShared } from '../utils/gridCoverage'
import { newRow, newSheet } from '../utils/reportGridModel'
import { useToast } from './useToast'

export function useReportGrid() {
  const { notify } = useToast()

  const sheets = ref<GridSheet[]>([])
  const activeSheet = ref(0)
  const selected = ref<{ row: number; col: number | null } | null>(null)
  const rangeEnd = ref<{ row: number; col: number } | null>(null)
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
        if (hadBound && !confirm('В строке есть ячейки, привязанные к данным (поле/№) — при отключении повторения они станут пустым текстом. Продолжить?'))
          return
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

  return {
    sheets,
    activeSheet,
    selected,
    rangeEnd,
    curSheet,
    rect,
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
    cellAt,
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
  }
}
