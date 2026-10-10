import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { useOrganizationStore, DEFAULT_ORGANIZATION_NAME } from '../organization'
import { usePreferencesStore } from '../preferences'
import { stubPreferencesApi } from './preferencesApi'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  vi.unstubAllGlobals()
})

describe('useOrganizationStore', () => {
  it('по умолчанию — значение из хардкода шапки, который заменяет этот стор', () => {
    const org = useOrganizationStore()
    expect(org.name).toBe(DEFAULT_ORGANIZATION_NAME)
    expect(org.name).toBe('ООО «Организация»')
  })

  it('устанавливает новое наименование, обрезает пробелы и отправляет его на сервер как общую настройку', async () => {
    const api = stubPreferencesApi()
    const org = useOrganizationStore()
    org.setName('  ООО «Ромашка»  ')
    expect(org.name).toBe('ООО «Ромашка»')
    await flushPromises()

    expect(api.globalPuts).toEqual([{ organization_name: 'ООО «Ромашка»' }])
    expect(api.userPuts).toEqual([])
    expect(localStorage.getItem('itr.organizationName')).toBeNull()
  })

  it('пустое или пробельное имя, как и значение по умолчанию, сбрасывают настройку (null) и возвращают умолчание', async () => {
    const api = stubPreferencesApi({ global: { organization_name: 'ООО «Ромашка»' } })
    usePreferencesStore().global = { organization_name: 'ООО «Ромашка»' }
    const org = useOrganizationStore()
    org.setName('   ')
    expect(org.name).toBe(DEFAULT_ORGANIZATION_NAME)
    org.setName(DEFAULT_ORGANIZATION_NAME)
    await flushPromises()
    expect(api.globalPuts).toEqual([{ organization_name: null }, { organization_name: null }])
  })

  it('берёт название из загруженных серверных настроек', () => {
    usePreferencesStore().global = { organization_name: 'ООО «Ромашка»' }
    expect(useOrganizationStore().name).toBe('ООО «Ромашка»')
  })

  it('reset() возвращает значение по умолчанию и сбрасывает настройку на сервере', async () => {
    const api = stubPreferencesApi({ global: { organization_name: 'ООО «Ромашка»' } })
    usePreferencesStore().global = { organization_name: 'ООО «Ромашка»' }
    const org = useOrganizationStore()
    org.reset()
    expect(org.name).toBe(DEFAULT_ORGANIZATION_NAME)
    await flushPromises()
    expect(api.server.global).toEqual({})
  })

  it('отказ сервера (не администратор): значение откатывается к серверному и показывается уведомление об ошибке', async () => {
    const api = stubPreferencesApi({ global: { organization_name: 'Старое' } })
    api.failPutsWith = 403
    const prefs = usePreferencesStore()
    prefs.global = { organization_name: 'Старое' }
    const org = useOrganizationStore()
    org.setName('Чужое')
    expect(org.name).toBe('Чужое') // оптимистично
    await flushPromises()
    expect(org.name).toBe('Старое') // откат после отказа
  })
})
