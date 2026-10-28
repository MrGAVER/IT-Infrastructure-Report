import { describe, expect, it } from 'vitest'
import { useRowUiState } from '../useRowUiState'

describe('useRowUiState', () => {
  it('«выбрать все» отмечает индексы 0…n-1 по текущему числу строк, снятие очищает выбор', () => {
    let count = 3
    const ui = useRowUiState(() => count)
    ui.toggleSelectAll(true)
    expect([...ui.selectedIndices.value]).toEqual([0, 1, 2])
    count = 4
    ui.toggleSelectAll(true)
    expect(ui.selectedIndices.value.size).toBe(4)
    ui.toggleSelectAll(false)
    expect(ui.selectedIndices.value.size).toBe(0)
  })

  it('toggleSelect и toggleExpand добавляют и убирают индекс', () => {
    const ui = useRowUiState(() => 5)
    ui.toggleSelect(2, true)
    ui.toggleSelect(4, true)
    ui.toggleSelect(2, false)
    expect([...ui.selectedIndices.value]).toEqual([4])
    ui.toggleExpand(1)
    expect(ui.expandedIndices.value.has(1)).toBe(true)
    ui.toggleExpand(1)
    expect(ui.expandedIndices.value.has(1)).toBe(false)
  })

  it('setCopyTarget хранит выбор по индексу строки-источника и не трогает чужие', () => {
    const ui = useRowUiState(() => 3)
    ui.setCopyTarget(0, '2')
    ui.setCopyTarget(1, '0')
    ui.setCopyTarget(0, '')
    expect(ui.copyTargetIndex.value).toEqual({ 0: '', 1: '0' })
  })

  it('структурное изменение сбрасывает выбор, раскрытие и получателей копирования, clearSelection — только выбор', () => {
    const ui = useRowUiState(() => 3)
    ui.toggleSelect(0, true)
    ui.toggleExpand(1)
    ui.setCopyTarget(0, '1')
    ui.clearSelection()
    expect(ui.selectedIndices.value.size).toBe(0)
    expect(ui.expandedIndices.value.size).toBe(1)
    ui.toggleSelect(2, true)
    ui.resetStructure()
    expect(ui.selectedIndices.value.size + ui.expandedIndices.value.size).toBe(0)
    expect(ui.copyTargetIndex.value).toEqual({})
  })
})
