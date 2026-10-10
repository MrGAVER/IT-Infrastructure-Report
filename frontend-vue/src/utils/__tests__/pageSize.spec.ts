import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { isAllowedPageSize, loadPageSize, pageAfterSizeChange, pageSizeOptionsFor, savePageSize } from '../pageSize'
import { usePreferencesStore } from '../../stores/preferences'
import { stubPreferencesApi, type PreferencesApiStub } from '../../stores/__tests__/preferencesApi'

let api: PreferencesApiStub

beforeEach(() => {
  vi.unstubAllGlobals()
  setActivePinia(createPinia())
  localStorage.clear()
  api = stubPreferencesApi()
})

describe('pageSizeOptionsFor', () => {
  it('варианты строятся от размера по умолчанию (x1, x2, x4, x8) и всегда его содержат', () => {
    expect(pageSizeOptionsFor(6)).toEqual([6, 12, 24, 48])
    expect(pageSizeOptionsFor(8)).toEqual([8, 16, 32, 64])
    expect(pageSizeOptionsFor(12)).toEqual([12, 24, 48, 96])
  })

  it('isAllowedPageSize принимает только варианты списка', () => {
    expect(isAllowedPageSize(16, 8)).toBe(true)
    expect(isAllowedPageSize(10, 8)).toBe(false)
    expect(isAllowedPageSize(0, 8)).toBe(false)
    expect(isAllowedPageSize(-8, 8)).toBe(false)
  })
})

describe('loadPageSize / savePageSize', () => {
  it('без сохранённого значения — размер по умолчанию', () => {
    expect(loadPageSize('vms', 8)).toBe(8)
  })

  it('возвращает сохранённый выбор; у каждого списка он свой', () => {
    savePageSize('vms', 32)
    savePageSize('devices', 12)

    expect(loadPageSize('vms', 8)).toBe(32)
    expect(loadPageSize('devices', 6)).toBe(12)
    expect(loadPageSize('containers', 8)).toBe(8)
  })

  it.each([0, -8, 10, 16.5, 99999])('недопустимое сохранённое значение %s игнорируется', (garbage) => {
    usePreferencesStore().user = { page_sizes: { vms: garbage } }
    expect(loadPageSize('vms', 8)).toBe(8)
  })

  it('значение, ставшее недопустимым для списка (изменился размер по умолчанию), сбрасывается на умолчание', () => {
    savePageSize('vms', 64) // допустимо при умолчании 8
    expect(loadPageSize('vms', 6)).toBe(6) // при умолчании 6 варианты 6/12/24/48
  })

  it('сохраняет выбор на сервере (только изменённый список — остальные сервер не трогает), а не в localStorage', async () => {
    savePageSize('vms', 32)
    await flushPromises()

    expect(api.userPuts).toEqual([{ page_sizes: { vms: 32 } }])
    expect(api.server.user.page_sizes).toEqual({ vms: 32 })
    expect(localStorage.getItem('itr.pageSize.vms')).toBeNull()
  })

  it('сбой сервера не роняет запись: размер откатывается к серверному, ошибка не пробрасывается', async () => {
    api.failPutsWith = 500
    expect(() => savePageSize('vms', 16)).not.toThrow()
    expect(loadPageSize('vms', 8)).toBe(16) // оптимистично
    await flushPromises()
    expect(loadPageSize('vms', 8)).toBe(8) // откат: на сервере выбора нет
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

  it('первая страница всегда остаётся первой', () => {
    expect(pageAfterSizeChange(1, 8, 64)).toBe(1)
    expect(pageAfterSizeChange(1, 64, 8)).toBe(1)
  })

  it('некорректный номер страницы не даёт результата меньше 1', () => {
    expect(pageAfterSizeChange(0, 8, 16)).toBe(1)
    expect(pageAfterSizeChange(-3, 8, 16)).toBe(1)
  })
})
