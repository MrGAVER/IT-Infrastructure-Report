// Чистые функции блока «Общие IP-адреса VLAN стека» (DeviceStackVlanIpEditor.vue): подписи состояния и проверка ввода.
// Вынесены из компонента, чтобы проверяться без монтирования (jsdom) — правила те же, что на бэкенде
// (services/device_stack_vlans.py): адрес и префикс задаются только вместе, пустая пара — очистка.
import type { StackVlanRow } from '../api/types'
import { isValidIPv4, isValidPrefixLength } from './ipValidation'

export interface StackVlanStatus {
  /** ok — настроено одинаково у всех участников; warn — нужно «Применить ко всем»; new — VLAN ещё не назначен никому. */
  kind: 'ok' | 'warn' | 'new'
  text: string
}

/** Подпись состояния VLAN на участниках стека; row === null — строка, добавленная в форме и ещё не применённая. */
export function stackVlanStatus(row: StackVlanRow | null): StackVlanStatus {
  if (!row) return { kind: 'new', text: 'Не назначен устройствам стека' }
  if (row.is_uniform) return { kind: 'ok', text: `Одинаково у всех (${row.member_count})` }
  if (row.assigned_count < row.member_count) {
    return { kind: 'warn', text: `Назначен не у всех: ${row.assigned_count} из ${row.member_count}` }
  }
  return { kind: 'warn', text: 'Адреса различаются у устройств' }
}

/** Сообщение об ошибке ввода или null, если пару «IP-адрес — префикс» можно отправлять (в том числе пустую: очистка). */
export function validateSharedIp(ip: string, prefix: string): string | null {
  const hasIp = ip.trim() !== ''
  const hasPrefix = prefix.trim() !== ''
  if (hasIp && !hasPrefix) return 'Укажите префикс (маску) вместе с IP-адресом'
  if (!hasIp && hasPrefix) return 'Укажите IP-адрес вместе с префиксом'
  if (!isValidIPv4(ip)) return 'Некорректный IPv4-адрес'
  if (!isValidPrefixLength(prefix)) return 'Префикс — целое число от 0 до 32'
  return null
}

/** Тело PUT /device-stacks/{id}/vlans/{vlan_id}: пустые поля уходят как null (очистка адреса у всех участников). */
export function sharedIpPayload(ip: string, prefix: string): { ip_address: string | null; prefix_length: number | null } {
  const trimmedIp = ip.trim()
  const trimmedPrefix = prefix.trim()
  return { ip_address: trimmedIp || null, prefix_length: trimmedPrefix === '' ? null : Number(trimmedPrefix) }
}

/** Совпадает ли введённая пара с тем, что уже общее у всех участников (тогда применять нечего). */
export function matchesSharedValue(row: StackVlanRow | null, ip: string, prefix: string): boolean {
  if (!row || !row.is_uniform) return false
  const payload = sharedIpPayload(ip, prefix)
  return payload.ip_address === row.ip_address && payload.prefix_length === row.prefix_length
}
