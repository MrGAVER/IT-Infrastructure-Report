import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  readLocalSettings,
  readLocalUserPreferences,
  removeLocalSettings,
  writeLocalUserPreferences,
} from '../localSettings'

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('readLocalSettings', () => {
  it('читает все известные ключи и перечисляет их в keys', () => {
    localStorage.setItem('itr.colorScheme', 'indigo')
    localStorage.setItem('itr.organizationName', '  ООО «Ромашка»  ')
    localStorage.setItem('itr.deviceVlanCollapseRows', '25')
    localStorage.setItem('itr.pageSize.vms', '16')

    const result = readLocalSettings()

    expect(result).toMatchObject({ colorScheme: 'indigo', organizationName: 'ООО «Ромашка»', collapseRows: 25, pageSizes: { vms: 16 } })
    expect([...result.keys].sort()).toEqual(['itr.colorScheme', 'itr.deviceVlanCollapseRows', 'itr.organizationName', 'itr.pageSize.vms'])
  })

  it('испорченные значения не попадают в результат, но их ключи перечислены (чтобы убрать при переносе)', () => {
    localStorage.setItem('itr.colorScheme', 'Teal Dark!')
    localStorage.setItem('itr.deviceVlanCollapseRows', '0')
    localStorage.setItem('itr.pageSize.vms', 'много')
    localStorage.setItem('itr.pageSize.bad id!', '10')
    localStorage.setItem('itr.organizationName', '   ')

    const result = readLocalSettings()

    expect(result.colorScheme).toBeUndefined()
    expect(result.collapseRows).toBeUndefined()
    expect(result.organizationName).toBeUndefined()
    expect(result.pageSizes).toEqual({})
    expect(result.keys).toHaveLength(5)
  })

  it('токен сессии и чужие ключи игнорируются', () => {
    localStorage.setItem('itr:auth-token', 'секрет')
    localStorage.setItem('other', 'x')
    expect(readLocalSettings().keys).toEqual([])
  })

  it('недоступный localStorage не роняет чтение', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'key').mockImplementation(() => {
      throw new Error('denied')
    })
    expect(readLocalSettings()).toEqual({ pageSizes: {}, keys: [] })
  })
})

describe('readLocalUserPreferences', () => {
  it('возвращает личные настройки в серверной форме и не включает название организации', () => {
    localStorage.setItem('itr.colorScheme', 'copper')
    localStorage.setItem('itr.deviceVlanCollapseRows', '12')
    localStorage.setItem('itr.pageSize.devices', '24')
    localStorage.setItem('itr.organizationName', 'ООО «Ромашка»')

    expect(readLocalUserPreferences()).toEqual({ color_scheme: 'copper', device_vlan_collapse_rows: 12, page_sizes: { devices: 24 } })
  })

  it('пусто — пустой объект', () => {
    expect(readLocalUserPreferences()).toEqual({})
  })
})

describe('writeLocalUserPreferences', () => {
  it('записывает заданное и удаляет то, чего нет, включая устаревшие размеры страниц', () => {
    localStorage.setItem('itr.colorScheme', 'indigo')
    localStorage.setItem('itr.pageSize.old', '8')
    localStorage.setItem('itr.pageSize.keep', '16')

    writeLocalUserPreferences({ device_vlan_collapse_rows: 30, page_sizes: { keep: 32, added: 64 } })

    expect(localStorage.getItem('itr.colorScheme')).toBeNull()
    expect(localStorage.getItem('itr.deviceVlanCollapseRows')).toBe('30')
    expect(localStorage.getItem('itr.pageSize.old')).toBeNull()
    expect(localStorage.getItem('itr.pageSize.keep')).toBe('32')
    expect(localStorage.getItem('itr.pageSize.added')).toBe('64')
  })

  it('не трогает название организации, токен сессии и чужие ключи', () => {
    localStorage.setItem('itr.organizationName', 'ООО «Ромашка»')
    localStorage.setItem('itr:auth-token', 'секрет')
    localStorage.setItem('other', 'x')

    writeLocalUserPreferences({})

    expect(localStorage.getItem('itr.organizationName')).toBe('ООО «Ромашка»')
    expect(localStorage.getItem('itr:auth-token')).toBe('секрет')
    expect(localStorage.getItem('other')).toBe('x')
  })

  it('недоступный localStorage не роняет запись', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })
    expect(() => writeLocalUserPreferences({ color_scheme: 'indigo' })).not.toThrow()
  })
})

describe('removeLocalSettings', () => {
  it('удаляет только указанные ключи', () => {
    localStorage.setItem('a', '1')
    localStorage.setItem('b', '2')
    removeLocalSettings(['a'])
    expect(localStorage.getItem('a')).toBeNull()
    expect(localStorage.getItem('b')).toBe('2')
  })
})
