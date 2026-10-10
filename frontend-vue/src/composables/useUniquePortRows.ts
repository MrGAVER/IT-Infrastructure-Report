// Общее поведение редакторов открытых портов (OpenPortListEditor.vue — ВМ, порты устройств, группы
// портов; ISProtocolsListEditor.vue — протоколы ИС): «номера портов не повторяются, список
// упорядочен по номеру порта». Вынесено из компонентов, чтобы правило было одно и то же везде и не
// расходилось при правках (см. utils/openPorts.ts — сами чистые функции сортировки и поиска повторов).
//
// Что делает редактор с этим правилом:
//   * подсвечивает строки с повторяющимся номером и показывает одно сообщение под списком;
//   * упорядочивает строки НЕ в момент правки строки, а только когда пользователь добавляет
//     следующую (sortedForAdd) — иначе только что заполняемая строка «уезжала» бы из-под курсора;
//   * само сохранение не блокирует — это делает форма-владелец (duplicatePortNumbers при submit).
import { computed, type ComputedRef } from 'vue'
import type { ProtocolPortCatalogEntry } from '../api/types'
import { duplicatePortNumbers, duplicateRowIndexes, sortOpenPortRows, type PortRow } from '../utils/openPorts'

export interface UniquePortRows<T extends PortRow> {
  /** Индексы строк с повторяющимся номером порта (пусто, если правило выключено). */
  duplicateIndexes: ComputedRef<Set<number>>
  /** Текст ошибки о повторах либо '' (правило выключено или повторов нет). */
  duplicateMessage: ComputedRef<string>
  /** Строки для добавления следующей: отсортированные по номеру порта (если правило включено) либо как есть. */
  sortedForAdd: () => readonly T[]
}

/** Текст ошибки о повторах номеров портов — один для подсказки под списком редактора. */
export function duplicatePortsMessage(numbers: readonly number[]): string {
  return numbers.length ? `Порт ${numbers.join(', ')} указан несколько раз — каждый номер порта можно добавить только один раз.` : ''
}

/**
 * @param rows — текущие строки редактора (геттер, чтобы подхватывать новые значения пропа);
 * @param catalog — справочник «порт + протокол»: номер порта в строке не хранится, а берётся из него;
 * @param enabled — включено ли правило (у OpenPortListEditor — проп sortedUnique, у протоколов ИС всегда).
 *
 * @example
 * const { duplicateIndexes, duplicateMessage, sortedForAdd } = useUniquePortRows(() => props.modelValue, () => props.catalogEntries)
 */
export function useUniquePortRows<T extends PortRow>(
  rows: () => readonly T[],
  catalog: () => readonly ProtocolPortCatalogEntry[],
  enabled: () => boolean = () => true,
): UniquePortRows<T> {
  const duplicateIndexes = computed(() => (enabled() ? duplicateRowIndexes(rows(), catalog()) : new Set<number>()))
  const duplicateMessage = computed(() => (enabled() ? duplicatePortsMessage(duplicatePortNumbers(rows(), catalog())) : ''))
  const sortedForAdd = (): readonly T[] => (enabled() ? sortOpenPortRows(rows(), catalog()) : rows())
  return { duplicateIndexes, duplicateMessage, sortedForAdd }
}
