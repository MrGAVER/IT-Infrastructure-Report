import { describe, expect, it } from 'vitest'
import type { StackVlanRow } from '../../api/types'
import { matchesSharedValue, sharedIpPayload, stackVlanStatus, validateSharedIp } from '../stackVlans'

function row(overrides: Partial<StackVlanRow> = {}): StackVlanRow {
  return {
    vlan_id: 'v-10',
    vlan_number: 10,
    vlan_name: 'mgmt',
    domain_id: null,
    ip_address: '10.0.10.1',
    prefix_length: 24,
    is_uniform: true,
    assigned_count: 3,
    member_count: 3,
    members: [],
    ...overrides,
  }
}

describe('stackVlanStatus', () => {
  it('строка без серверного состояния — VLAN ещё не назначен устройствам', () => {
    expect(stackVlanStatus(null)).toEqual({ kind: 'new', text: 'Не назначен устройствам стека' })
  })

  it('единый адрес у всех участников — ok со счётчиком', () => {
    expect(stackVlanStatus(row())).toEqual({ kind: 'ok', text: 'Одинаково у всех (3)' })
  })

  it('назначен не всем — warn с количеством', () => {
    expect(stackVlanStatus(row({ is_uniform: false, assigned_count: 2 }))).toEqual({ kind: 'warn', text: 'Назначен не у всех: 2 из 3' })
  })

  it('назначен всем, но адреса разные — warn про различия', () => {
    expect(stackVlanStatus(row({ is_uniform: false, ip_address: null, prefix_length: null })).text).toBe('Адреса различаются у устройств')
  })
})

describe('validateSharedIp', () => {
  it('корректная пара и пустая пара (очистка) допустимы', () => {
    expect(validateSharedIp('10.0.10.5', '24')).toBeNull()
    expect(validateSharedIp('', '')).toBeNull()
    expect(validateSharedIp('  ', ' ')).toBeNull()
  })

  it('IP без префикса и префикс без IP отклоняются — как на бэкенде', () => {
    expect(validateSharedIp('10.0.10.5', '')).toContain('префикс')
    expect(validateSharedIp('', '24')).toContain('IP-адрес')
  })

  it('некорректный IPv4 и префикс вне 0–32', () => {
    expect(validateSharedIp('999.1.1.1', '24')).toBe('Некорректный IPv4-адрес')
    expect(validateSharedIp('10.0.10.5', '33')).toBe('Префикс — целое число от 0 до 32')
    expect(validateSharedIp('10.0.10.5', '-1')).toBe('Префикс — целое число от 0 до 32')
    expect(validateSharedIp('10.0.10.5', '2.5')).toBe('Префикс — целое число от 0 до 32')
  })
})

describe('sharedIpPayload', () => {
  it('приводит префикс к числу и обрезает пробелы', () => {
    expect(sharedIpPayload(' 10.0.10.5 ', '24')).toEqual({ ip_address: '10.0.10.5', prefix_length: 24 })
  })

  it('пустые поля уходят как null (очистка адреса), а префикс 0 — не «пусто»', () => {
    expect(sharedIpPayload('', '')).toEqual({ ip_address: null, prefix_length: null })
    expect(sharedIpPayload('0.0.0.0', '0')).toEqual({ ip_address: '0.0.0.0', prefix_length: 0 })
  })
})

describe('matchesSharedValue', () => {
  it('совпадает только когда адрес уже единый у всех и ввод его не меняет', () => {
    expect(matchesSharedValue(row(), '10.0.10.1', '24')).toBe(true)
    expect(matchesSharedValue(row(), '10.0.10.2', '24')).toBe(false)
    expect(matchesSharedValue(row({ is_uniform: false }), '10.0.10.1', '24')).toBe(false)
    expect(matchesSharedValue(null, '', '')).toBe(false)
  })

  it('единая очистка (адреса нет у всех) совпадает с пустым вводом', () => {
    expect(matchesSharedValue(row({ ip_address: null, prefix_length: null }), '', '')).toBe(true)
  })
})
