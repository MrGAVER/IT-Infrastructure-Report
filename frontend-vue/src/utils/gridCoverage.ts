// Какие колонки в строке rowIndex заняты вертикальным объединением (rowspan), начавшимся в одной
// из строк ВЫШЕ — там для них не нужно рисовать отдельную ячейку в редакторе, её и так покрывает
// rowSpan ячейки сверху (как в обычной HTML-таблице с rowspan). Портировано из
// rbCoverageForRows()/rbRowSpanCoverage() в frontend/static/report_builder.js — используется и
// отрисовкой сетки (какие <td> НЕ рисовать), и валидацией перед включением "повторения" строки
// (rbToggleRepeat: нельзя сделать повторяющейся строку, частично охваченную объединением сверху).
import type { GridRow } from '../api/types'

export function coverageForRows(rows: GridRow[], rowIndex: number): Set<number> {
  const covered = new Set<number>()
  for (let r = 0; r < rowIndex; r++) {
    for (const cell of rows[r].cells) {
      const rowspan = cell.rowspan || 1
      if (r + rowspan > rowIndex) {
        const colspan = cell.colspan || 1
        for (let c = cell.col; c < cell.col + colspan; c++) covered.add(c)
      }
    }
  }
  return covered
}

/** Прямоугольник выделения (для объединения ячеек) из пары "первая выбранная" + "конец диапазона
 * по Shift+клику" — null, если диапазон не задан (выделена только одна ячейка либо строка целиком). */
export function selectionRect(
  selected: { row: number; col: number | null } | null,
  rangeEnd: { row: number; col: number } | null,
): { r1: number; r2: number; c1: number; c2: number } | null {
  if (!selected || selected.col === null || !rangeEnd) return null
  return {
    r1: Math.min(selected.row, rangeEnd.row),
    r2: Math.max(selected.row, rangeEnd.row),
    c1: Math.min(selected.col, rangeEnd.col),
    c2: Math.max(selected.col, rangeEnd.col),
  }
}
