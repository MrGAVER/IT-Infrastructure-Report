// Какие колонки в строке rowIndex заняты вертикальным объединением (rowspan), начавшимся в одной
// из строк ВЫШЕ — там для них не нужно рисовать отдельную ячейку в редакторе, её и так покрывает
// rowSpan ячейки сверху (как в обычной HTML-таблице с rowspan). Портировано из
// rbCoverageForRows()/rbRowSpanCoverage() в frontend/static/report_builder.js — используется и
// отрисовкой сетки (какие <td> НЕ рисовать), и валидацией перед включением "повторения" строки
// (rbToggleRepeat: нельзя сделать повторяющейся строку, частично охваченную объединением сверху).

/** Минимальная форма строки/ячейки, которой достаточно для coverageForRows/visibleCellsForRow —
 * общая как для "живых" GridRow/GridCell редактора, так и для уже материализованных
 * GridPreviewRow/GridPreviewCell предпросмотра (api/types.ts): у обеих есть col/colspan/rowspan,
 * но разный набор остальных полей (kind/text/path у одной, value/is_datetime у другой). */
export interface CoverageRow<TCell extends { col: number; colspan?: number; rowspan?: number }> {
  cells: TCell[]
}

export function coverageForRows<TCell extends { col: number; colspan?: number; rowspan?: number }>(
  rows: CoverageRow<TCell>[],
  rowIndex: number,
): Set<number> {
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

/** Для каждой видимой (не покрытой вертикальным объединением сверху) позиции в строке ri — либо
 * реальная ячейка (если начинается здесь), либо null (пустая позиция). Пропускает и колонки,
 * "проглоченные" colspan идущей раньше в той же строке ячейки — иначе один и тот же физический
 * столбец отрисовался бы дважды. Общая для ReportGridEditorView.vue (редактирование) и
 * GridPreviewTable.vue (предпросмотр) — тот же алгоритм обхода, разные типы ячеек. */
export function visibleCellsForRow<TCell extends { col: number; colspan?: number; rowspan?: number }>(
  rows: CoverageRow<TCell>[],
  ri: number,
  columnCount: number,
): Array<{ col: number; cell: TCell | null }> {
  const row = rows[ri]
  const coveredAbove = coverageForRows(rows, ri)
  const result: Array<{ col: number; cell: TCell | null }> = []
  let ci = 0
  while (ci < columnCount) {
    if (coveredAbove.has(ci)) {
      ci += 1
      continue
    }
    const cell = row.cells.find((c) => c.col === ci) ?? null
    result.push({ col: ci, cell })
    ci += cell ? cell.colspan || 1 : 1
  }
  return result
}
