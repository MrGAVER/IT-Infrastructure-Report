// Чисто UI-состояние списка портов (DeviceInterfacesEditor.vue) — не часть modelValue. Всё держится по ИНДЕКСУ строки, поэтому
// при любом структурном изменении списка (добавление, удаление, генерация) его сбрасывают: после сдвига индексов старый выбор
// указывал бы на другую строку.
import { ref, type Ref } from 'vue'

export interface RowUiState {
  /** Строки, отмеченные галочкой «Выбрать» (цель массового редактирования). */
  selectedIndices: Ref<Set<number>>
  /** Строки с развёрнутой панелью (VLAN на порту, IP-адреса, описание) — редко нужные поля убраны из компактной таблицы под toggle. */
  expandedIndices: Ref<Set<number>>
  /** Выбранный в «Копировать» порт-получатель открытых портов: индекс строки-ИСТОЧНИКА → индекс получателя строкой ('' — не выбран). Ключ — индекс, а не id: у несохранённой строки id нет. */
  copyTargetIndex: Ref<Record<number, string>>
  toggleSelect: (index: number, checked: boolean) => void
  toggleSelectAll: (checked: boolean) => void
  toggleExpand: (index: number) => void
  setCopyTarget: (index: number, targetIndex: string) => void
  clearSelection: () => void
  /** Структурное изменение списка: сбрасывает выбор, раскрытие и выбор получателя копирования. */
  resetStructure: () => void
}

/** @param rowCount — число строк списка (геттер): «выбрать все» отмечает индексы 0…rowCount-1. */
export function useRowUiState(rowCount: () => number): RowUiState {
  const selectedIndices = ref<Set<number>>(new Set())
  const expandedIndices = ref<Set<number>>(new Set())
  const copyTargetIndex = ref<Record<number, string>>({})

  function toggleSelect(index: number, checked: boolean) {
    if (checked) selectedIndices.value.add(index)
    else selectedIndices.value.delete(index)
  }
  function toggleSelectAll(checked: boolean) {
    selectedIndices.value = checked ? new Set(Array.from({ length: rowCount() }, (_, i) => i)) : new Set()
  }
  function toggleExpand(index: number) {
    if (expandedIndices.value.has(index)) expandedIndices.value.delete(index)
    else expandedIndices.value.add(index)
  }
  function setCopyTarget(index: number, targetIndex: string) {
    copyTargetIndex.value = { ...copyTargetIndex.value, [index]: targetIndex }
  }
  function clearSelection() {
    selectedIndices.value = new Set()
  }
  function resetStructure() {
    selectedIndices.value = new Set()
    expandedIndices.value = new Set()
    copyTargetIndex.value = {}
  }

  return { selectedIndices, expandedIndices, copyTargetIndex, toggleSelect, toggleSelectAll, toggleExpand, setCopyTarget, clearSelection, resetStructure }
}
