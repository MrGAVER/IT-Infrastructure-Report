import { describe, it, expect } from 'vitest'
import { facetsLabel, flagsFromRole, formatVlans, hasRoleMismatch, modeAndVlansLabel, modeLabel, portRoleOf, roleFromFlags, roleLabel } from '../portConfig'
import type { PortRole } from '../../api/types'

describe('portConfig utils', () => {
  it.each([
    [false, false, 'none'],
    [true, false, 'management'],
    [false, true, 'data'],
    [true, true, 'management_data'],
  ] as const)('roleFromFlags(%s, %s) = %s', (management, data, expected) => {
    expect(roleFromFlags(management, data)).toBe(expected)
    expect(portRoleOf({ is_management: management, is_data_transfer: data })).toBe(expected)
  })

  it('flagsFromRole — обратное преобразование для всех четырёх ролей', () => {
    for (const role of ['none', 'management', 'data', 'management_data'] as PortRole[]) {
      const { is_management, is_data_transfer } = flagsFromRole(role)
      expect(roleFromFlags(is_management, is_data_transfer)).toBe(role)
    }
  })

  it('portRoleOf: отсутствующие флаги считаются выключенными', () => {
    expect(portRoleOf({})).toBe('none')
  })

  it('hasRoleMismatch: порт управления сервера против порта передачи данных коммутатора — расхождение', () => {
    expect(hasRoleMismatch({ is_management: true, is_data_transfer: false }, { is_management: false, is_data_transfer: true })).toBe(true)
    expect(hasRoleMismatch({ is_data_transfer: true }, { is_data_transfer: true })).toBe(false)
  })

  it('roleLabel: подпись роли и прочерк для неизвестной', () => {
    expect(roleLabel('management')).toBe('Управление активами')
    expect(roleLabel(null)).toBe('—')
  })
})

describe('portConfig utils — режим и VLAN', () => {
  it('formatVlans: пустой набор — «нет»', () => {
    expect(formatVlans([])).toBe('нет')
    expect(formatVlans(null)).toBe('нет')
    expect(formatVlans(undefined)).toBe('нет')
  })

  it('formatVlans: сворачивает подряд идущие номера в диапазоны, пару соседних оставляет списком', () => {
    expect(formatVlans([10])).toBe('10')
    expect(formatVlans([10, 11])).toBe('10, 11')
    expect(formatVlans([10, 11, 12])).toBe('10–12')
    expect(formatVlans([10, 11, 12, 20, 30, 31])).toBe('10–12, 20, 30, 31')
  })

  it('formatVlans: сортирует и убирает дубликаты', () => {
    expect(formatVlans([30, 10, 20, 10, 11])).toBe('10, 11, 20, 30')
  })

  it('formatVlans: транк на все VLAN умещается в короткую строку', () => {
    const all = Array.from({ length: 4094 }, (_, i) => i + 1)
    expect(formatVlans(all)).toBe('1–4094')
  })

  it('modeLabel / modeAndVlansLabel: режим и VLAN одной строкой, прочерк для отсутствующего порта', () => {
    expect(modeLabel('access')).toBe('access')
    expect(modeLabel(null)).toBe('—')
    expect(modeAndVlansLabel('trunk', [10, 20])).toBe('trunk · VLAN 10, 20')
    expect(modeAndVlansLabel('access', [])).toBe('access · VLAN нет')
  })

  it('facetsLabel: названия граней расхождения через запятую', () => {
    expect(facetsLabel(['role', 'mode', 'vlans'])).toBe('роль, режим, VLAN')
    expect(facetsLabel(['vlans'])).toBe('VLAN')
    expect(facetsLabel([])).toBe('')
  })
})
