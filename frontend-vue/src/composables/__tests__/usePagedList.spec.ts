import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { usePreferencesStore } from '../../stores/preferences'
import { stubPreferencesApi, type PreferencesApiStub } from '../../stores/__tests__/preferencesApi'
import { usePagedList } from '../usePagedList'

const range = (n: number) => Array.from({ length: n }, (_, i) => i + 1)
const OPTIONS = { listId: 'testList', defaultPageSize: 10 }

let api: PreferencesApiStub

beforeEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
  setActivePinia(createPinia())
  api = stubPreferencesApi()
})

describe('usePagedList', () => {
  it('по умолчанию — первая страница из defaultPageSize записей; варианты размера — x1, x2, x4, x8', () => {
    const list = usePagedList(range(25), OPTIONS)

    expect(list.page.value).toBe(1)
    expect(list.pageSize.value).toBe(10)
    expect(list.pageSizeOptions.value).toEqual([10, 20, 40, 80])
    expect(list.pageCount.value).toBe(3)
    expect(list.pageItems.value).toEqual(range(10))
    expect([list.rangeFrom.value, list.rangeTo.value, list.total.value]).toEqual([1, 10, 25])
  })

  it('последняя страница неполная, диапазон «Показано» считается по фактическим записям', () => {
    const list = usePagedList(range(25), OPTIONS)

    list.setPage(3)

    expect(list.pageItems.value).toEqual([21, 22, 23, 24, 25])
    expect([list.rangeFrom.value, list.rangeTo.value]).toEqual([21, 25])
  })

  it('пустой список: одна страница, диапазон 0–0, без записей', () => {
    const list = usePagedList([] as number[], OPTIONS)

    expect(list.pageCount.value).toBe(1)
    expect(list.pageItems.value).toEqual([])
    expect([list.rangeFrom.value, list.rangeTo.value, list.total.value]).toEqual([0, 0, 0])
  })

  it('setPage ограничивает номер страницы пределами [1, pageCount]; не число — первая страница', () => {
    const list = usePagedList(range(25), OPTIONS)

    list.setPage(99)
    expect(list.page.value).toBe(3)
    list.setPage(-4)
    expect(list.page.value).toBe(1)
    list.setPage(Number.NaN)
    expect(list.page.value).toBe(1)
  })

  it('если список стал короче, показывается последняя существующая страница, а не пустая таблица', () => {
    const source = ref(range(25))
    const list = usePagedList(source, OPTIONS)
    list.setPage(3)

    source.value = range(12)

    expect(list.pageCount.value).toBe(2)
    expect(list.page.value).toBe(2)
    expect(list.pageItems.value).toEqual([11, 12])
  })

  it('resetPage возвращает на первую страницу (смена поиска/справочника)', () => {
    const list = usePagedList(range(25), OPTIONS)
    list.setPage(2)

    list.resetPage()

    expect(list.page.value).toBe(1)
  })

  it('смена размера оставляет на странице с тем же первым видимым элементом', () => {
    const list = usePagedList(range(100), OPTIONS)
    list.setPage(3) // записи 21–30

    list.setPageSize(20)

    expect(list.page.value).toBe(2) // 21-я — первая на второй странице по 20
    expect(list.pageItems.value[0]).toBe(21)
    expect(list.pageItems.value).toHaveLength(20)
  })

  it('выбранный размер запоминается на сервере для этого списка и восстанавливается новым экземпляром', async () => {
    usePagedList(range(100), OPTIONS).setPageSize(40)
    await flushPromises()
    expect(api.server.user.page_sizes).toEqual({ testList: 40 })

    // «Перезагрузка страницы»: настройки подтягиваются с сервера до создания списка.
    setActivePinia(createPinia())
    await usePreferencesStore().load({ userId: 'user-1', canWriteGlobal: false })
    expect(usePagedList(range(100), OPTIONS).pageSize.value).toBe(40)
  })

  it.each([0, -1, 7, 1000, Number.NaN])('недопустимый размер %s игнорируется: страница и настройки не меняются', (bad) => {
    const list = usePagedList(range(100), OPTIONS)
    list.setPage(2)

    list.setPageSize(bad)

    expect(list.pageSize.value).toBe(10)
    expect(list.page.value).toBe(2)
    expect(api.userPuts).toEqual([])
  })

  it('тот же размер — ничего не меняет и ничего не сохраняет', () => {
    const list = usePagedList(range(100), OPTIONS)
    list.setPage(4)

    list.setPageSize(10)

    expect(list.page.value).toBe(4)
    expect(api.userPuts).toEqual([])
  })

  it.each([0, -5, 2.5, Number.NaN])('недопустимый defaultPageSize %s — понятная ошибка при создании', (bad) => {
    expect(() => usePagedList(range(3), { listId: 'x', defaultPageSize: bad })).toThrow(RangeError)
  })
})
