import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useFormPreferencesStore } from '../formPreferences'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

describe('useFormPreferencesStore', () => {
  it('по умолчанию блок «VLAN устройства» сворачивается при количестве строк больше 10', () => {
    expect(useFormPreferencesStore().deviceVlanCollapseRows).toBe(10)
  })

  it('сохраняет допустимое значение в localStorage и восстанавливает его при новой инициализации стора', () => {
    const store = useFormPreferencesStore()
    expect(store.setDeviceVlanCollapseRows('25')).toBe(true)
    expect(store.deviceVlanCollapseRows).toBe(25)
    expect(localStorage.getItem('itr.deviceVlanCollapseRows')).toBe('25')

    setActivePinia(createPinia())
    expect(useFormPreferencesStore().deviceVlanCollapseRows).toBe(25)
  })

  it('недопустимое значение не принимается и не подменяется молча: стор и localStorage остаются прежними', () => {
    const store = useFormPreferencesStore()
    store.setDeviceVlanCollapseRows(25)
    for (const bad of ['', 'abc', '0', '1001', '2.5']) expect(store.setDeviceVlanCollapseRows(bad)).toBe(false)
    expect(store.deviceVlanCollapseRows).toBe(25)
    expect(localStorage.getItem('itr.deviceVlanCollapseRows')).toBe('25')
  })

  it('испорченное значение в localStorage заменяется значением по умолчанию', () => {
    localStorage.setItem('itr.deviceVlanCollapseRows', 'мусор')
    expect(useFormPreferencesStore().deviceVlanCollapseRows).toBe(10)
  })

  it('reset() возвращает 10', () => {
    const store = useFormPreferencesStore()
    store.setDeviceVlanCollapseRows(3)
    store.reset()
    expect(store.deviceVlanCollapseRows).toBe(10)
  })
})
