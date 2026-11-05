import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS, isAllowedPageSize, loadPageSize, pageAfterSizeChange, savePageSize } from '../pageSize'
import { usePreferencesStore } from '../../stores/preferences'
import { stubPreferencesApi, type PreferencesApiStub } from '../../stores/__tests__/preferencesApi'

let api: PreferencesApiStub

beforeEach(() => {
  vi.unstubAllGlobals()
  setActivePinia(createPinia())
  localStorage.clear()
  api = stubPreferencesApi()
})

describe('шкала размеров страницы', () => {
  it('одна шкала для всех списков — 10 / 25 / 50 / 100, по умолчанию 10 (F-09)', () => {
    expect(PAGE_SIZE_OPTIONS).toEqual([10, 25, 50, 100])
    expect(DEFAULT_PAGE_SIZE).toBe(10)
    expect(PAGE_SIZE_OPTIONS).toContain(DEFAULT_PAGE_SIZE)
  })

  it('все значения шкалы укладываются в предел серверных списков (журнал аудита — не больше 200)', () => {
    expect(Math.max(...PAGE_SIZE_OPTIONS)).toBeLessThanOrEqual(200)
  })

  it('isAllowedPageSize принимает только значения шкалы', () => {
    for (const size of PAGE_SIZE_OPTIONS) expect(isAllowedPageSize(size)).toBe(true)
    for (const size of [0, -10, 6, 8, 12, 24, 48, 20, 1000, 25.5, Number.NaN]) expect(isAllowedPageSize(size)).toBe(false)
  })
})

describe('loadPageSize / savePageSize', () => {
  it('без сохранённого значения — размер по умолчанию', () => {
    expect(loadPageSize('vms')).toBe(DEFAULT_PAGE_SIZE)
  })

  it('возвращает сохранённый выбор; у каждого списка он свой', () => {
    savePageSize('vms', 50)
    savePageSize('devices', 25)

    expect(loadPageSize('vms')).toBe(50)
    expect(loadPageSize('devices')).toBe(25)
    expect(loadPageSize('containers')).toBe(DEFAULT_PAGE_SIZE)
  })

  it.each([0, -10, 12, 16.5, 99999])('недопустимое сохранённое значение %s игнорируется', (garbage) => {
    usePreferencesStore().user = { page_sizes: { vms: garbage } }
    expect(loadPageSize('vms')).toBe(DEFAULT_PAGE_SIZE)
  })

  it.each([6, 8, 12, 16, 24, 32, 48, 64, 96])(
    'выбор из прежних вариантов (%s) читается как «не выбрано»: список откроется с размером по умолчанию',
    (legacy) => {
      usePreferencesStore().user = { page_sizes: { devices: legacy } }
      expect(loadPageSize('devices')).toBe(DEFAULT_PAGE_SIZE)
    },
  )

  it('сохраняет выбор на сервере (только изменённый список — остальные сервер не трогает), а не в localStorage', async () => {
    savePageSize('vms', 50)
    await flushPromises()

    expect(api.userPuts).toEqual([{ page_sizes: { vms: 50 } }])
    expect(api.server.user.page_sizes).toEqual({ vms: 50 })
    expect(localStorage.getItem('itr.pageSize.vms')).toBeNull()
  })

  it('сбой сервера не роняет запись: размер откатывается к серверному, ошибка не пробрасывается', async () => {
    api.failPutsWith = 500
    expect(() => savePageSize('vms', 25)).not.toThrow()
    expect(loadPageSize('vms')).toBe(25) // оптимистично
    await flushPromises()
    expect(loadPageSize('vms')).toBe(DEFAULT_PAGE_SIZE) // откат: на сервере выбора нет
  })
})

describe('pageAfterSizeChange', () => {
  it('остаётся на странице, где окажется первая из видимых записей', () => {
    // страница 3 по 8 → первая запись № 17; по 16 на странице она — первая на странице 2
    expect(pageAfterSizeChange(3, 8, 16)).toBe(2)
    // страница 2 по 8 → № 9; по 16 она на странице 1
    expect(pageAfterSizeChange(2, 8, 16)).toBe(1)
    // страница 2 по 16 → № 17; по 8 — страница 3
    expect(pageAfterSizeChange(2, 16, 8)).toBe(3)
  })

  it('на значениях шкалы 10 / 25 / 50 / 100 первая видимая запись не теряется', () => {
    // страница 3 по 10 → № 21; по 25 она на странице 1, по 50 — тоже
    expect(pageAfterSizeChange(3, 10, 25)).toBe(1)
    // страница 2 по 25 → № 26; по 10 — страница 3, по 100 — страница 1
    expect(pageAfterSizeChange(2, 25, 10)).toBe(3)
    expect(pageAfterSizeChange(2, 25, 100)).toBe(1)
    // страница 3 по 50 → № 101; по 25 — страница 5
    expect(pageAfterSizeChange(3, 50, 25)).toBe(5)
  })

  it('первая страница всегда остаётся первой', () => {
    expect(pageAfterSizeChange(1, 8, 64)).toBe(1)
    expect(pageAfterSizeChange(1, 64, 8)).toBe(1)
  })

  it('некорректный номер страницы не даёт результата меньше 1', () => {
    expect(pageAfterSizeChange(0, 8, 16)).toBe(1)
    expect(pageAfterSizeChange(-3, 8, 16)).toBe(1)
  })
})
