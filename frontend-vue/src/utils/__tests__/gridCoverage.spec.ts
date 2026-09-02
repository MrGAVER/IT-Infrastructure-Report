import { describe, it, expect } from 'vitest'
import { coverageForRows, selectionRect, visibleCellsForRow } from '../gridCoverage'
import type { GridRow } from '../../api/types'

function row(cells: GridRow['cells']): GridRow {
  return { height: 20, repeat: false, data_source: null, cells }
}

describe('coverageForRows', () => {
  it('строка без объединений сверху — пустое покрытие', () => {
    const rows = [row([{ col: 0, kind: 'static', text: 'a' }]), row([])]
    expect(coverageForRows(rows, 1)).toEqual(new Set())
  })

  it('rowspan=2 из строки 0 покрывает те же колонки в строке 1, но не в строке 2', () => {
    const rows = [row([{ col: 1, colspan: 2, rowspan: 2, kind: 'static', text: 'x' }]), row([]), row([])]
    expect(coverageForRows(rows, 1)).toEqual(new Set([1, 2]))
    expect(coverageForRows(rows, 2)).toEqual(new Set())
  })

  it('несколько объединений с разных строк складываются в одно покрытие', () => {
    const rows = [
      row([{ col: 0, rowspan: 3, kind: 'static', text: 'a' }]),
      row([{ col: 2, rowspan: 2, kind: 'static', text: 'b' }]),
      row([]),
    ]
    expect(coverageForRows(rows, 2)).toEqual(new Set([0, 2]))
  })

  it('rowIndex=0 — сверху ничего нет, покрытие всегда пустое', () => {
    const rows = [row([{ col: 0, rowspan: 5, kind: 'static', text: 'a' }])]
    expect(coverageForRows(rows, 0)).toEqual(new Set())
  })
})

describe('selectionRect', () => {
  it('без rangeEnd — диапазона нет (null)', () => {
    expect(selectionRect({ row: 1, col: 2 }, null)).toBeNull()
  })

  it('col===null (выбрана строка целиком) — диапазона нет, даже если rangeEnd задан', () => {
    expect(selectionRect({ row: 1, col: null }, { row: 2, col: 3 })).toBeNull()
  })

  it('normализует прямоугольник независимо от направления выделения', () => {
    expect(selectionRect({ row: 3, col: 4 }, { row: 1, col: 2 })).toEqual({ r1: 1, r2: 3, c1: 2, c2: 4 })
    expect(selectionRect({ row: 1, col: 2 }, { row: 3, col: 4 })).toEqual({ r1: 1, r2: 3, c1: 2, c2: 4 })
  })
})

describe('visibleCellsForRow', () => {
  it('без объединений — по одной позиции на каждую колонку, с ячейкой или без', () => {
    const rows = [row([{ col: 0, kind: 'static', text: 'a' }])]
    const result = visibleCellsForRow(rows, 0, 3)
    expect(result.map((r) => r.col)).toEqual([0, 1, 2])
    expect(result[0].cell?.text).toBe('a')
    expect(result[1].cell).toBeNull()
  })

  it('colspan в той же строке пропускает поглощённые колонки', () => {
    const rows = [row([{ col: 0, colspan: 2, kind: 'static', text: 'wide' }, { col: 2, kind: 'static', text: 'c' }])]
    const result = visibleCellsForRow(rows, 0, 3)
    expect(result.map((r) => r.col)).toEqual([0, 2]) // колонка 1 поглощена colspan=2
  })

  it('колонки, покрытые rowspan сверху, не показываются как отдельная позиция', () => {
    const rows = [row([{ col: 0, rowspan: 2, kind: 'static', text: 'tall' }]), row([{ col: 1, kind: 'static', text: 'b' }])]
    const result = visibleCellsForRow(rows, 1, 2)
    expect(result.map((r) => r.col)).toEqual([1]) // колонка 0 покрыта rowspan сверху, пропущена целиком
  })

  it('работает с обобщёнными ячейками предпросмотра (другой набор полей, но тот же col/colspan/rowspan)', () => {
    const previewRows = [{ cells: [{ col: 0, colspan: 2, rowspan: 1, value: 'x', is_datetime: false, style: {} }] }]
    const result = visibleCellsForRow(previewRows, 0, 3)
    expect(result.map((r) => r.col)).toEqual([0, 2])
    expect(result[0].cell?.value).toBe('x')
  })
})
