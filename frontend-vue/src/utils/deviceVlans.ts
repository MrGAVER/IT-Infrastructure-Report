// Чистые функции над черновыми строками блока «VLAN устройства» (DeviceVlanDraftRow) — те же правила,
// что у открытых портов (utils/openPorts.ts): список упорядочен, повторов нет, уже добавленное не
// предлагается ещё раз. Вынесено из компонента ради тестов без монтирования и чтобы редактор (подсветка,
// опции) и форма (проверка при сохранении) пользовались одним правилом.
//
// Осторожно с именами: у строки черновика vlan_id — это ИДЕНТИФИКАТОР записи VLANDefinition (uuid), а
// номер VLAN (10, 20, …) лежит в VLANDefinition.vlan_id. Сортировка идёт по номеру, повторы ищутся по uuid.
import type { VLANDefinition } from '../api/types'

/** Минимум, который нужен функциям ниже от строки черновика: выбранный VLAN (uuid определения). */
export interface VlanRow {
  vlan_id: string
}

/** Сравнение определений VLAN: номер по возрастанию, затем домен и имя (одинаковый номер в разных доменах). */
export function compareVlanDefinitions(a: VLANDefinition, b: VLANDefinition): number {
  if (a.vlan_id !== b.vlan_id) return a.vlan_id < b.vlan_id ? -1 : 1
  return (a.domain_name ?? '').localeCompare(b.domain_name ?? '', 'ru') || (a.name ?? '').localeCompare(b.name ?? '', 'ru')
}

/** Копия списка определений, упорядоченная для выпадающего списка. Входной массив не меняется. */
export function sortVlanDefinitions(definitions: readonly VLANDefinition[]): VLANDefinition[] {
  return [...definitions].sort(compareVlanDefinitions)
}

/**
 * Копия строк, упорядоченная по номеру VLAN по возрастанию. Строки без выбранного (или не найденного
 * среди definitions) VLAN — в конце, чтобы только что добавленная пустая строка оставалась внизу.
 * Сортировка стабильна, исходный массив не меняется.
 *
 * @example
 * sortDeviceVlanRows([{ vlan_id: 'b' }, { vlan_id: '' }, { vlan_id: 'a' }], definitions) // a (10), b (20), пустая
 */
export function sortDeviceVlanRows<T extends VlanRow>(rows: readonly T[], definitions: readonly VLANDefinition[]): T[] {
  const byId = new Map(definitions.map((d) => [d.id, d]))
  return [...rows].sort((a, b) => {
    const da = byId.get(a.vlan_id)
    const db = byId.get(b.vlan_id)
    if (!da || !db) return da === db ? 0 : da ? -1 : 1
    return compareVlanDefinitions(da, db)
  })
}

/** Множество уже выбранных в строках VLAN (пустые строки не считаются). */
export function usedVlanIds(rows: readonly VlanRow[]): Set<string> {
  return new Set(rows.map((r) => r.vlan_id).filter(Boolean))
}

/**
 * Опции для строки: VLAN, уже выбранные в ДРУГИХ строках, скрываются; собственный выбор строки остаётся
 * (если он есть среди options). Порядок options сохраняется. Если повтор всё же попал в черновик
 * (старые данные), обе строки сохраняют свой VLAN в списке — выбор не пропадает из поля.
 */
export function vlanOptionsForRow<T extends VLANDefinition>(options: readonly T[], used: ReadonlySet<string>, own: string): T[] {
  return options.filter((o) => o.id === own || !used.has(o.id))
}

/** Индексы строк, чей VLAN встречается в черновике более одного раза. */
export function duplicateVlanRowIndexes(rows: readonly VlanRow[]): Set<number> {
  const byVlan = new Map<string, number[]>()
  rows.forEach((row, index) => {
    if (!row.vlan_id) return
    const indexes = byVlan.get(row.vlan_id)
    if (indexes) indexes.push(index)
    else byVlan.set(row.vlan_id, [index])
  })
  const result = new Set<number>()
  for (const indexes of byVlan.values()) {
    if (indexes.length > 1) indexes.forEach((i) => result.add(i))
  }
  return result
}

/** Текст ошибки о повторах (пусто, если повторов нет): «VLAN 10, 20 указан несколько раз — …». */
export function duplicateVlansMessage(rows: readonly VlanRow[], definitions: readonly VLANDefinition[]): string {
  const duplicated = duplicateVlanRowIndexes(rows)
  if (!duplicated.size) return ''
  const byId = new Map(definitions.map((d) => [d.id, d]))
  const labels = new Map<string, { label: string; number: number }>()
  for (const index of duplicated) {
    const id = rows[index].vlan_id
    if (labels.has(id)) continue
    const def = byId.get(id)
    labels.set(id, { label: def ? String(def.vlan_id) : id, number: def ? def.vlan_id : Number.POSITIVE_INFINITY })
  }
  const text = [...labels.values()].sort((a, b) => a.number - b.number).map((l) => l.label).join(', ')
  return `VLAN ${text} указан несколько раз — каждый VLAN можно добавить устройству только один раз.`
}
