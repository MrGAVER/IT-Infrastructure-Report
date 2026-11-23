import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useReportGrid } from '../useReportGrid'
import { cellPreview, newRow, newSheet } from '../../utils/reportGridModel'
import type { GridCell } from '../../api/types'

// Вынесено из ReportGridEditorView.vue: поведение проверяет и спецификация представления (ReportGridEditorView.spec.ts),
// здесь — сама логика без монтирования компонента.
function setup() {
  const grid = useReportGrid()
  grid.sheets.value = [newSheet(1)]
  return grid
}

describe('reportGridModel', () => {
  it('новый лист: заголовок, шесть колонок, строка-шапка и повторяющаяся строка', () => {
    const sheet = newSheet(3)
    expect(sheet.title).toBe('Лист 3')
    expect(sheet.columns).toHaveLength(6)
    expect(sheet.rows).toHaveLength(2)
    expect(sheet.rows[0].cells[0]).toMatchObject({ col: 0, colspan: 6, kind: 'static' })
    expect(sheet.rows[1].repeat).toBe(true)
  })

  it('источник данных есть только у повторяющейся строки', () => {
    expect(newRow(false).data_source).toBeNull()
    expect(newRow(true).data_source).toMatchObject({ root_entity: '', include_empty_expand: true })
  })

  it('подпись ячейки по типу', () => {
    const cell = (c: Partial<GridCell>): GridCell => ({ col: 0, kind: 'static', ...c }) as GridCell
    expect(cellPreview(null)).toBe('')
    expect(cellPreview(cell({ kind: 'static', text: 'Итого' }))).toBe('Итого')
    expect(cellPreview(cell({ kind: 'field', path: 'device.name' }))).toBe('{device.name}')
    expect(cellPreview(cell({ kind: 'field' }))).toBe('{…}')
    expect(cellPreview(cell({ kind: 'index' }))).toBe('№')
    expect(cellPreview(cell({ kind: 'formula' }))).toBe('=')
  })
})

describe('useReportGrid', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    )
  })

  it('вставка строки растягивает вертикальное объединение, «перешагивающее» точку вставки', () => {
    const grid = setup()
    const rows = grid.sheets.value[0].rows
    rows[0].cells[0].rowspan = 2 // шапка объединена с повторяющейся строкой

    grid.addRowAt(0)

    expect(grid.sheets.value[0].rows).toHaveLength(3)
    expect(rows[0].cells[0].rowspan).toBe(3)
  })

  it('последний лист и последнюю колонку удалить нельзя', () => {
    const grid = setup()
    grid.removeSheet(0)
    expect(grid.sheets.value).toHaveLength(1)

    grid.sheets.value[0].columns.splice(1)
    grid.removeColumn(0)
    expect(grid.sheets.value[0].columns).toHaveLength(1)
  })

  it('удаление колонки сдвигает ячейки правее и сужает объединение через неё', () => {
    const grid = setup()
    const rows = grid.sheets.value[0].rows
    rows[1].cells.push({ col: 3, kind: 'static', text: 'D', style: {} })

    grid.removeColumn(1) // шапка объединяет колонки 0–5 и сузится до 5

    expect(grid.sheets.value[0].columns).toHaveLength(5)
    expect(rows[0].cells[0].colspan).toBe(5)
    expect(rows[1].cells[0].col).toBe(2)
  })

  it('Shift+клик задаёт диапазон, объединение собирает одну ячейку на диапазон', () => {
    const grid = setup()
    grid.selectCell(1, 0)
    grid.selectCell(1, 2, { shiftKey: true } as MouseEvent)
    expect(grid.isInRange(1, 1)).toBe(true)
    expect(grid.isInRange(0, 1)).toBe(false)

    grid.mergeSelection()

    const anchor = grid.sheets.value[0].rows[1].cells.find((c) => c.col === 0)
    expect(anchor).toMatchObject({ colspan: 3, rowspan: 1 })
    expect(grid.selected.value).toEqual({ row: 1, col: 0 })
  })

  it('включение повторения создаёт источник данных, отключение превращает привязанные ячейки в пустой текст', () => {
    const grid = setup()
    grid.selectRow(0)
    grid.onUpdateRow({ repeat: true })
    expect(grid.sheets.value[0].rows[0].data_source).not.toBeNull()

    grid.sheets.value[0].rows[0].cells = [{ col: 0, kind: 'field', path: 'device.name', separator: '; ', style: {} }]
    grid.onUpdateRow({ repeat: false })

    const row = grid.sheets.value[0].rows[0]
    expect(row.data_source).toBeNull()
    expect(row.cells[0]).toMatchObject({ kind: 'static', text: '' })
    expect(row.cells[0].path).toBeUndefined()
  })
})
