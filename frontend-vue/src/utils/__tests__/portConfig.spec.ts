import { describe, it, expect } from 'vitest'
import { flagsFromRole, hasRoleMismatch, portRoleOf, roleFromFlags, roleLabel } from '../portConfig'
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
