// Чистые функции общих настроек VLAN стека: подписи состояния, проверка ввода, текст изменений при добавлении
// участника и подмена значений в черновике «VLAN устройства». Вынесены из компонентов, чтобы проверяться без
// монтирования (jsdom). Правила те же, что на бэкенде (services/device_stack_vlans.py): адрес и префикс — только
// вместе (обе пустые — адреса нет), только IPv4.
import type { DeviceVlanDraftRow, StackMemberChange, StackVlanRow, StackVlanValues } from '../api/types'
import { isValidIPv4, isValidPrefixLength } from './ipValidation'

export interface StackVlanStatus {
  /** ok — настроено одинаково у всех участников; warn — нужно «Применить ко всем»; new — настройка ещё не задана. */
  kind: 'ok' | 'warn' | 'new'
  text: string
}

/** Подпись состояния настройки на участниках стека; row === null — строка, добавленная в форме и ещё не применённая. */
export function stackVlanStatus(row: StackVlanRow | null): StackVlanStatus {
  if (!row) return { kind: 'new', text: 'Ещё не применено к устройствам стека' }
  if (row.is_uniform) return { kind: 'ok', text: `Применено ко всем (${row.member_count})` }
  if (row.assigned_count < row.member_count) {
    return { kind: 'warn', text: `VLAN назначен не у всех: ${row.assigned_count} из ${row.member_count}` }
  }
  return { kind: 'warn', text: 'У некоторых устройств значения отличаются от настройки' }
}

/** Сообщение об ошибке ввода или null, если пару «IP-адрес — префикс» можно отправлять (в том числе пустую). */
export function validateSharedIp(ip: string, prefix: string): string | null {
  const hasIp = ip.trim() !== ''
  const hasPrefix = prefix.trim() !== ''
  if (hasIp && !hasPrefix) return 'Укажите префикс (маску) вместе с IP-адресом'
  if (!hasIp && hasPrefix) return 'Укажите IP-адрес вместе с префиксом'
  if (!isValidIPv4(ip)) return 'Некорректный IPv4-адрес'
  if (!isValidPrefixLength(prefix)) return 'Префикс — целое число от 0 до 32'
  return null
}

/** Тело PUT /device-stacks/{id}/vlans/{vlan_id}: пустые поля уходят как null (адреса нет), префикс 0 — не «пусто». */
export function sharedSettingPayload(ip: string, prefix: string, isManagement: boolean): StackVlanValues {
  const trimmedIp = ip.trim()
  const trimmedPrefix = prefix.trim()
  return { ip_address: trimmedIp || null, prefix_length: trimmedPrefix === '' ? null : Number(trimmedPrefix), is_management: isManagement }
}

/** Совпадает ли введённое с тем, что уже применено ко всем участникам (тогда применять нечего). */
export function matchesSharedSetting(row: StackVlanRow | null, ip: string, prefix: string, isManagement: boolean): boolean {
  if (!row || !row.is_uniform) return false
  const payload = sharedSettingPayload(ip, prefix, isManagement)
  return payload.ip_address === row.ip_address && payload.prefix_length === row.prefix_length && payload.is_management === row.is_management
}

/** «10.0.10.1/24, Управление» либо «адрес не задан» — значения настройки одной строкой. */
export function formatStackValues(values: StackVlanValues): string {
  const address = values.ip_address ? (values.prefix_length === null ? values.ip_address : `${values.ip_address}/${values.prefix_length}`) : 'адрес не задан'
  return values.is_management ? `${address}, «Управление»` : address
}

/** Описание изменения для окна подтверждения добавления в стек: что добавится и что заменится. */
export function describeMemberChange(change: StackMemberChange): string {
  if (change.action === 'add' || !change.before) return `Будет назначен VLAN: ${formatStackValues(change.after)}`
  return `Будет заменено: ${formatStackValues(change.before)} → ${formatStackValues(change.after)}`
}

/** VLAN устройства, заданные общими настройками стека, → причина блокировки правки (подсказка в форме устройства). */
export function lockedVlanReasons(items: StackVlanRow[], stackName: string): Record<string, string> {
  const reasons: Record<string, string> = {}
  for (const item of items) reasons[item.vlan_id] = `Задано для стека «${stackName}»: меняется в общих настройках VLAN стека`
  return reasons
}

/** Подставляет в черновик «VLAN устройства» значения общих настроек стека после «Применить ко всем»: у строк с этим VLAN
 * меняются IP, префикс и «Управление» (описание и прочее не трогаются), недостающие строки добавляются (описание — как у
 * назначения на сервере). Остальные строки черновика, в том числе несохранённые правки, остаются как есть. Чистая функция:
 * входной массив не мутируется. deviceId — устройство, чья форма открыта (по нему берётся описание создаваемой строки). */
export function mergeSharedSettingsIntoDraft(rows: DeviceVlanDraftRow[], items: StackVlanRow[], deviceId: string): DeviceVlanDraftRow[] {
  const next = rows.map((row) => ({ ...row }))
  for (const item of items) {
    const prefix = item.prefix_length === null ? '' : String(item.prefix_length)
    const existing = next.find((row) => row.vlan_id === item.vlan_id)
    if (existing) {
      existing.ip_address = item.ip_address ?? ''
      existing.prefix_length = prefix
      existing.is_management = item.is_management
      continue
    }
    const own = item.members.find((m) => m.physical_device_id === deviceId)
    next.push({ vlan_id: item.vlan_id, ip_address: item.ip_address ?? '', prefix_length: prefix, is_management: item.is_management, description: own?.description ?? '' })
  }
  return next
}
