import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { applyGlobalPatch, applyUserPatch, usePreferencesStore } from '../preferences'
import { useToast } from '../../composables/useToast'
import { stubPreferencesApi, type PreferencesApiStub } from './preferencesApi'

let api: PreferencesApiStub
// Серверный режим: есть учётная запись. Режим без аутентификации (личные настройки в браузере) — LOCAL.
const SERVER = { userId: 'user-1', canWriteGlobal: true }
const LOCAL = { userId: null, canWriteGlobal: true }

beforeEach(() => {
  vi.unstubAllGlobals()
  setActivePinia(createPinia())
  localStorage.clear()
  useToast().toasts.splice(0)
  api = stubPreferencesApi()
})

describe('applyUserPatch / applyGlobalPatch (те же правила, что на сервере)', () => {
  it('null сбрасывает ключ, остальные ключи не трогаются, входной объект не меняется', () => {
    const current = { color_scheme: 'indigo', device_vlan_collapse_rows: 5 }
    expect(applyUserPatch(current, { color_scheme: null })).toEqual({ device_vlan_collapse_rows: 5 })
    expect(current).toEqual({ color_scheme: 'indigo', device_vlan_collapse_rows: 5 })
  })

  it('page_sizes сливается по спискам; null убирает список; последний убранный список убирает ключ', () => {
    let state = applyUserPatch({}, { page_sizes: { devices: 50 } })
    state = applyUserPatch(state, { page_sizes: { vms: 100 } })
    expect(state.page_sizes).toEqual({ devices: 50, vms: 100 })
    state = applyUserPatch(state, { page_sizes: { devices: null, vms: null } })
    expect(state.page_sizes).toBeUndefined()
  })

  it('общая настройка: значение задаётся, null сбрасывает', () => {
    expect(applyGlobalPatch({}, { organization_name: 'ООО «Х»' })).toEqual({ organization_name: 'ООО «Х»' })
    expect(applyGlobalPatch({ organization_name: 'ООО «Х»' }, { organization_name: null })).toEqual({})
  })
})

describe('load()', () => {
  it('загружает настройки один раз для пользователя; повторный вызов запроса не делает', async () => {
    api.server = { user: { color_scheme: 'indigo' }, global: { organization_name: 'ООО «Ромашка»' } }
    const store = usePreferencesStore()
    expect(store.loaded).toBe(false)

    await store.load(SERVER)
    await store.load(SERVER)

    expect(api.gets).toBe(1)
    expect(store.loaded).toBe(true)
    expect(store.user).toEqual({ color_scheme: 'indigo' })
    expect(store.global).toEqual({ organization_name: 'ООО «Ромашка»' })
  })

  it('одновременные вызовы делят один запрос', async () => {
    const store = usePreferencesStore()
    await Promise.all([store.load(SERVER), store.load(SERVER), store.load(SERVER)])
    expect(api.gets).toBe(1)
  })

  it('для другого пользователя настройки загружаются заново', async () => {
    const store = usePreferencesStore()
    await store.load({ userId: 'user-1', canWriteGlobal: false })
    await store.load({ userId: 'user-2', canWriteGlobal: false })
    expect(api.gets).toBe(2)
  })

  it('reset() забывает загруженное: следующий пользователь не видит чужих настроек', async () => {
    api.server.user = { color_scheme: 'copper' }
    const store = usePreferencesStore()
    await store.load({ userId: 'user-1', canWriteGlobal: false })

    store.reset()

    expect(store.loaded).toBe(false)
    expect(store.user).toEqual({})
  })

  it('сбой загрузки не бросает: умолчания, одно предупреждение и никаких повторных запросов на каждой навигации', async () => {
    api.failGetWith = 500
    const store = usePreferencesStore()

    await expect(store.load(SERVER)).resolves.toBeUndefined()
    await store.load(SERVER)

    expect(store.loadFailed).toBe(true)
    expect(store.user).toEqual({})
    expect(api.gets).toBe(1)
    expect(useToast().toasts.filter((t) => t.type === 'warning')).toHaveLength(1)
  })
})

describe('сохранение', () => {
  it('применяется сразу, до ответа сервера', () => {
    const store = usePreferencesStore()
    void store.saveUser({ color_scheme: 'indigo' })
    expect(store.user.color_scheme).toBe('indigo')
  })

  it('запросы уходят на сервер строго по очереди, в порядке вызовов', async () => {
    const store = usePreferencesStore()
    void store.saveUser({ color_scheme: 'indigo' })
    void store.saveUser({ color_scheme: 'copper' })
    void store.saveUser({ color_scheme: 'teal' })
    await flushPromises()

    expect(api.userPuts.map((p) => p.color_scheme)).toEqual(['indigo', 'copper', 'teal'])
    expect(api.server.user.color_scheme).toBe('teal')
  })

  it('сбой записи: уведомление об ошибке и откат к тому, что на сервере', async () => {
    api.server.user = { color_scheme: 'teal' }
    const store = usePreferencesStore()
    await store.load(SERVER)
    api.failPutsWith = 500

    void store.saveUser({ color_scheme: 'copper' })
    expect(store.user.color_scheme).toBe('copper')
    await flushPromises()

    expect(store.user.color_scheme).toBe('teal')
    expect(useToast().toasts.some((t) => t.type === 'error' && t.message.includes('Не удалось сохранить'))).toBe(true)
  })

  it('после сбоя очередь продолжает работать: следующее сохранение доходит до сервера', async () => {
    const store = usePreferencesStore()
    api.failPutsWith = 500
    void store.saveUser({ color_scheme: 'copper' })
    await flushPromises()

    api.failPutsWith = 0
    void store.saveUser({ color_scheme: 'indigo' })
    await flushPromises()

    expect(api.server.user.color_scheme).toBe('indigo')
  })
})

describe('разовый перенос значений из localStorage', () => {
  const seedLegacy = () => {
    localStorage.setItem('itr.colorScheme', 'indigo')
    localStorage.setItem('itr.deviceVlanCollapseRows', '25')
    localStorage.setItem('itr.pageSize.vms', '16')
    localStorage.setItem('itr.pageSize.devices', '12')
    localStorage.setItem('itr.organizationName', 'ООО «Ромашка»')
  }

  it('значения уходят на сервер (личные и общее), старые ключи удаляются', async () => {
    seedLegacy()
    const store = usePreferencesStore()

    await store.load(SERVER)

    expect(api.server.user).toEqual({ color_scheme: 'indigo', device_vlan_collapse_rows: 25, page_sizes: { vms: 16, devices: 12 } })
    expect(api.server.global).toEqual({ organization_name: 'ООО «Ромашка»' })
    expect(store.user.color_scheme).toBe('indigo')
    expect(localStorage.getItem('itr.colorScheme')).toBeNull()
    expect(localStorage.getItem('itr.pageSize.vms')).toBeNull()
    expect(localStorage.getItem('itr.organizationName')).toBeNull()
  })

  it('значение на сервере главнее локального: оно не затирается, а локальный ключ всё равно убирается', async () => {
    api.server = { user: { color_scheme: 'teal', page_sizes: { vms: 32 } }, global: { organization_name: 'Серверное' } }
    seedLegacy()

    await usePreferencesStore().load(SERVER)

    expect(api.server.user.color_scheme).toBe('teal')
    expect(api.server.user.page_sizes).toEqual({ vms: 32, devices: 12 }) // vms не тронут, devices добавлен
    expect(api.server.global).toEqual({ organization_name: 'Серверное' })
    expect(localStorage.getItem('itr.organizationName')).toBeNull()
    expect(localStorage.getItem('itr.colorScheme')).toBeNull()
  })

  it('без права менять общие настройки (не администратор) название организации не отправляется и ключ остаётся до входа администратора', async () => {
    seedLegacy()

    await usePreferencesStore().load({ userId: 'viewer-1', canWriteGlobal: false })

    expect(api.globalPuts).toEqual([])
    expect(api.server.user.color_scheme).toBe('indigo') // личное переносится у любой роли
    expect(localStorage.getItem('itr.organizationName')).toBe('ООО «Ромашка»')
    expect(localStorage.getItem('itr.colorScheme')).toBeNull()
  })

  it('название организации, равное значению по умолчанию, на сервер не отправляется', async () => {
    localStorage.setItem('itr.organizationName', 'ООО «Организация»')

    await usePreferencesStore().load(SERVER)

    expect(api.globalPuts).toEqual([])
    expect(localStorage.getItem('itr.organizationName')).toBeNull()
  })

  it('сбой отправки: старые ключи остаются, значения не теряются, перенос повторится при следующем открытии', async () => {
    api.failPutsWith = 500
    seedLegacy()

    await usePreferencesStore().load(SERVER)

    expect(localStorage.getItem('itr.colorScheme')).toBe('indigo')
    expect(localStorage.getItem('itr.pageSize.vms')).toBe('16')
    expect(localStorage.getItem('itr.organizationName')).toBe('ООО «Ромашка»')
  })

  it('испорченные локальные значения не отправляются, но ключи убираются; токен сессии и чужие ключи не трогаются', async () => {
    localStorage.setItem('itr.colorScheme', 'Teal Dark!')
    localStorage.setItem('itr.deviceVlanCollapseRows', '0')
    localStorage.setItem('itr.pageSize.vms', 'много')
    localStorage.setItem('itr:auth-token', 'секретный-токен')
    localStorage.setItem('itr.somethingElse', 'x')

    await usePreferencesStore().load(SERVER)

    expect(api.userPuts).toEqual([])
    expect(localStorage.getItem('itr.colorScheme')).toBeNull()
    expect(localStorage.getItem('itr.deviceVlanCollapseRows')).toBeNull()
    expect(localStorage.getItem('itr.pageSize.vms')).toBeNull()
    expect(localStorage.getItem('itr:auth-token')).toBe('секретный-токен')
    expect(localStorage.getItem('itr.somethingElse')).toBe('x')
  })

  it('без старых ключей лишних запросов нет', async () => {
    await usePreferencesStore().load(SERVER)
    expect(api.userPuts).toEqual([])
    expect(api.globalPuts).toEqual([])
  })

  it('если загрузить настройки не удалось, перенос не выполняется и ключи остаются', async () => {
    api.failGetWith = 500
    seedLegacy()

    await usePreferencesStore().load(SERVER)

    expect(api.userPuts).toEqual([])
    expect(localStorage.getItem('itr.colorScheme')).toBe('indigo')
  })
})

describe('режим без аутентификации: личные настройки хранит браузер, название организации — сервер', () => {
  it('личные настройки читаются из localStorage, а не с сервера; общие — с сервера', async () => {
    localStorage.setItem('itr.colorScheme', 'copper')
    localStorage.setItem('itr.pageSize.vms', '16')
    api.server = { user: { color_scheme: 'indigo' }, global: { organization_name: 'ООО «Ромашка»' } }
    const store = usePreferencesStore()

    await store.load(LOCAL)

    expect(store.userStorage).toBe('local')
    expect(store.loadedFor).toBe('local')
    expect(store.user).toEqual({ color_scheme: 'copper', page_sizes: { vms: 16 } })
    expect(store.global).toEqual({ organization_name: 'ООО «Ромашка»' })
  })

  it('сохранение личной настройки пишет в localStorage сразу и не отправляет ничего на сервер', async () => {
    const store = usePreferencesStore()
    await store.load(LOCAL)

    void store.saveUser({ color_scheme: 'indigo', device_vlan_collapse_rows: 25, page_sizes: { devices: 24 } })
    await flushPromises()

    expect(localStorage.getItem('itr.colorScheme')).toBe('indigo')
    expect(localStorage.getItem('itr.deviceVlanCollapseRows')).toBe('25')
    expect(localStorage.getItem('itr.pageSize.devices')).toBe('24')
    expect(api.userPuts).toEqual([])
  })

  it('сброс (null) и удаление размера страницы убирают ключи из localStorage', async () => {
    localStorage.setItem('itr.colorScheme', 'indigo')
    localStorage.setItem('itr.pageSize.vms', '16')
    localStorage.setItem('itr.pageSize.devices', '24')
    const store = usePreferencesStore()
    await store.load(LOCAL)

    void store.saveUser({ color_scheme: null, page_sizes: { vms: null } })

    expect(localStorage.getItem('itr.colorScheme')).toBeNull()
    expect(localStorage.getItem('itr.pageSize.vms')).toBeNull()
    expect(localStorage.getItem('itr.pageSize.devices')).toBe('24')
  })

  it('название организации по-прежнему уходит на сервер и откатывается при отказе, не затрагивая браузерные личные настройки', async () => {
    localStorage.setItem('itr.colorScheme', 'copper')
    api.server.global = { organization_name: 'Старое' }
    const store = usePreferencesStore()
    await store.load(LOCAL)
    api.failPutsWith = 500

    void store.saveGlobal({ organization_name: 'Новое' })
    expect(store.global.organization_name).toBe('Новое') // оптимистично
    await flushPromises()

    expect(store.global.organization_name).toBe('Старое') // откат с сервера
    expect(store.user.color_scheme).toBe('copper') // личное из браузера не затёрто пустым серверным ответом
  })

  it('перенос: название организации из браузера уходит на сервер, а личные ключи остаются — это их постоянное место', async () => {
    localStorage.setItem('itr.organizationName', 'ООО «Ромашка»')
    localStorage.setItem('itr.colorScheme', 'indigo')
    localStorage.setItem('itr.deviceVlanCollapseRows', '25')
    localStorage.setItem('itr.pageSize.vms', '16')

    await usePreferencesStore().load(LOCAL)

    expect(api.server.global).toEqual({ organization_name: 'ООО «Ромашка»' })
    expect(api.userPuts).toEqual([])
    expect(localStorage.getItem('itr.organizationName')).toBeNull()
    expect(localStorage.getItem('itr.colorScheme')).toBe('indigo')
    expect(localStorage.getItem('itr.deviceVlanCollapseRows')).toBe('25')
    expect(localStorage.getItem('itr.pageSize.vms')).toBe('16')
  })

  it('сбой загрузки: личные настройки всё равно берутся из браузера, предупреждение одно', async () => {
    localStorage.setItem('itr.colorScheme', 'copper')
    api.failGetWith = 500
    const store = usePreferencesStore()

    await store.load(LOCAL)

    expect(store.loadFailed).toBe(true)
    expect(store.user.color_scheme).toBe('copper')
    expect(useToast().toasts.filter((t) => t.type === 'warning')).toHaveLength(1)
  })

  it('reset() возвращает серверный режим по умолчанию (следующим войдёт пользователь с учётной записью)', async () => {
    const store = usePreferencesStore()
    await store.load(LOCAL)
    expect(store.userStorage).toBe('local')

    store.reset()

    expect(store.userStorage).toBe('server')
  })

  it('локальные ключи, оставшиеся от работы без аутентификации, при входе пользователя переезжают на сервер и убираются из браузера', async () => {
    localStorage.setItem('itr.colorScheme', 'indigo')
    localStorage.setItem('itr.pageSize.vms', '16')

    await usePreferencesStore().load({ userId: 'user-9', canWriteGlobal: false })

    expect(api.server.user).toEqual({ color_scheme: 'indigo', page_sizes: { vms: 16 } })
    expect(localStorage.getItem('itr.colorScheme')).toBeNull()
    expect(localStorage.getItem('itr.pageSize.vms')).toBeNull()
  })
})
