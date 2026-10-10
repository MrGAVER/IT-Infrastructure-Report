import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { useFormPreferencesStore } from '../formPreferences'
import { usePreferencesStore } from '../preferences'
import { stubPreferencesApi, reloadPinia, type PreferencesApiStub } from './preferencesApi'

let api: PreferencesApiStub

beforeEach(() => {
  vi.unstubAllGlobals()
  setActivePinia(createPinia())
  localStorage.clear()
  api = stubPreferencesApi()
})

describe('useFormPreferencesStore', () => {
  it('по умолчанию блок «VLAN устройства» сворачивается при количестве строк больше 10', () => {
    expect(useFormPreferencesStore().collapseRows).toBe(10)
  })

  it('сохраняет допустимое значение на сервере (не в localStorage) и применяет его сразу', async () => {
    const store = useFormPreferencesStore()
    expect(store.setCollapseRows('25')).toBe(true)
    expect(store.collapseRows).toBe(25) // без ожидания ответа сервера
    await flushPromises()

    expect(api.userPuts).toEqual([{ device_vlan_collapse_rows: 25 }])
    expect(api.server.user.device_vlan_collapse_rows).toBe(25)
    expect(localStorage.getItem('itr.deviceVlanCollapseRows')).toBeNull()
  })

  it('значение переживает «перезагрузку»: после загрузки настроек с сервера порог тот же', async () => {
    useFormPreferencesStore().setCollapseRows(25)
    await flushPromises()

    reloadPinia()
    expect(useFormPreferencesStore().collapseRows).toBe(25)
  })

  it('недопустимое значение не принимается и не подменяется молча: порог прежний, на сервер ничего не уходит', async () => {
    const store = useFormPreferencesStore()
    store.setCollapseRows(25)
    await flushPromises()
    api.userPuts.length = 0

    for (const bad of ['', 'abc', '0', '1001', '2.5']) expect(store.setCollapseRows(bad)).toBe(false)
    await flushPromises()

    expect(store.collapseRows).toBe(25)
    expect(api.userPuts).toEqual([])
  })

  it('испорченное значение в серверных настройках заменяется значением по умолчанию', () => {
    usePreferencesStore().user = { device_vlan_collapse_rows: 5000 }
    expect(useFormPreferencesStore().collapseRows).toBe(10)
  })

  it('reset() сбрасывает настройку на сервере (null) и возвращает 10', async () => {
    const store = useFormPreferencesStore()
    store.setCollapseRows(3)
    await flushPromises()

    store.reset()
    await flushPromises()

    expect(store.collapseRows).toBe(10)
    expect(api.server.user).toEqual({})
  })
})
