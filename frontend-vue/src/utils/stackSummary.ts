// Сводка по стекам для дашборда «Стеки устройств»: из списка стеков и реестра устройств (на устройстве есть stack_id,
// stack_position) собирается по строке на стек — состав, модели, IP управления, расположение, покрытие SIEM. Только
// чистые функции, без сторов: подписи каталогов (модель, здание, помещение) передаёт вызывающий, так логику можно
// проверять без монтирования экрана.
import type { Device, DeviceStack } from '../api/types'
import { RU_COLLATOR } from '../stores/catalogs'
import { sortNaturally } from './naturalSort'

/** Как вызывающий превращает устройство в подписи из справочников (пустая строка — значение не задано). */
export interface StackLabelResolvers {
  /** «Производитель · модель». */
  model: (device: Device) => string
  /** «Здание · помещение». */
  place: (device: Device) => string
}

export interface StackMemberRow {
  device: Device
  /** Позиция в стеке; у устройства без позиции — null (такие идут в конце состава). */
  position: number | null
  /** Системное имя, а без него — серийный номер. */
  name: string
  model: string
  place: string
}

/** none — SIEM нет ни у одного участника; partial — не у всех; all — у всех; empty — в стеке нет устройств. */
export type StackSiemState = 'empty' | 'none' | 'partial' | 'all'

export interface StackSummary {
  stack: DeviceStack
  members: StackMemberRow[]
  /** Уникальные значения по участникам, в порядке состава стека. */
  models: string[]
  places: string[]
  ips: string[]
  siemCovered: number
  siemState: StackSiemState
}

export interface StackStats {
  stacks: number
  devices: number
  empty: number
  /** Стеки, где SIEM есть не у всех участников (пустые не считаются: у них нечего покрывать). */
  siemIncomplete: number
}

/** management_ips приходит одной строкой «a; b» (backend: services/serialization.py); делится по «;», запятой и пробелам. */
export function splitIps(value: string | null | undefined): string[] {
  return (value ?? '')
    .split(/[;,\s]+/)
    .map((ip) => ip.trim())
    .filter(Boolean)
}

function uniq(values: readonly string[]): string[] {
  return [...new Set(values.filter(Boolean))]
}

function siemState(covered: number, total: number): StackSiemState {
  if (total === 0) return 'empty'
  if (covered === 0) return 'none'
  return covered === total ? 'all' : 'partial'
}

function compareMembers(a: StackMemberRow, b: StackMemberRow): number {
  // Устройства без позиции — после остальных; при равных позициях порядок задаёт имя тем же collator'ом, что и везде
  // («sw-2» раньше «sw-10»).
  const pa = a.position ?? Number.POSITIVE_INFINITY
  const pb = b.position ?? Number.POSITIVE_INFINITY
  if (pa !== pb) return pa < pb ? -1 : 1
  return RU_COLLATOR.compare(a.name, b.name)
}

/**
 * По одной сводке на стек, стеки — по названию (естественная сортировка: «Стек 2» раньше «Стек 10»). Устройства
 * группируются за один проход по реестру. Устройство со stack_id, которого нет в списке стеков (список ещё не обновился),
 * просто не попадает ни в одну сводку.
 */
export function buildStackSummaries(stacks: readonly DeviceStack[], devices: readonly Device[], labels: StackLabelResolvers): StackSummary[] {
  const byStack = new Map<string, Device[]>()
  for (const device of devices) {
    if (!device.stack_id) continue
    const list = byStack.get(device.stack_id)
    if (list) list.push(device)
    else byStack.set(device.stack_id, [device])
  }

  return sortNaturally(stacks, (s) => s.name).map((stack) => {
    const members: StackMemberRow[] = (byStack.get(stack.id) ?? [])
      .map((device) => ({
        device,
        position: device.stack_position,
        name: device.system_name || device.serial_number,
        model: labels.model(device),
        place: labels.place(device),
      }))
      .sort(compareMembers)
    const siemCovered = members.filter((m) => m.device.siem_enabled).length
    return {
      stack,
      members,
      models: uniq(members.map((m) => m.model)),
      places: uniq(members.map((m) => m.place)),
      ips: uniq(members.flatMap((m) => splitIps(m.device.management_ips))),
      siemCovered,
      siemState: siemState(siemCovered, members.length),
    }
  })
}

/** Тексты, по которым ищется стек: название, описание и всё, что показано о составе (имена, серийные номера, модели, IP, места). */
export function stackSearchTexts(summary: StackSummary): string[] {
  return [
    summary.stack.name,
    summary.stack.description,
    ...summary.members.flatMap((m) => [m.name, m.device.serial_number, m.device.description]),
    ...summary.models,
    ...summary.ips,
    ...summary.places,
  ].filter((t): t is string => typeof t === 'string' && t !== '')
}

export function stackStats(summaries: readonly StackSummary[]): StackStats {
  return {
    stacks: summaries.length,
    devices: summaries.reduce((sum, s) => sum + s.members.length, 0),
    empty: summaries.filter((s) => s.siemState === 'empty').length,
    siemIncomplete: summaries.filter((s) => s.siemState === 'none' || s.siemState === 'partial').length,
  }
}
