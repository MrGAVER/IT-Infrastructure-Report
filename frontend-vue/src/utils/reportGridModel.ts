// Чистые функции модели grid-редактора Excel-шаблона (config.sheets, см. backend/app/services/report_grid.py): заготовки новых
// строк и листов и короткая подпись ячейки для сетки. Вынесены из ReportGridEditorView.vue, чтобы не зависеть от Vue и тестироваться отдельно.
import type { GridCell, GridRow, GridSheet } from '../api/types'

export function newRow(repeat = false): GridRow {
  return { height: 20, repeat, data_source: repeat ? { root_entity: '', expand: '', include_empty_expand: true, filters: [], sort_by: '' } : null, cells: [] }
}
export function newSheet(n: number): GridSheet {
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

export function cellPreview(cell: GridCell | null): string {
  if (!cell) return ''
  if (cell.kind === 'static') return cell.text || ''
  if (cell.kind === 'field') return cell.path ? `{${cell.path}}` : '{…}'
  if (cell.kind === 'index') return '№'
  return cell.text || '='
}
