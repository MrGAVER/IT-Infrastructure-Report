// Выбор количества строк на странице — общее поведение четырёх клиентских списков (устройства,
// ВМ, контейнеры, информационные системы). Подключения и журнал аудита — постраничная выборка с
// сервера, их проверяют connectionsDashboard.spec.ts и auditLog.spec.ts.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { usePreferencesStore } from '../preferences'
import { stubPreferencesApi, type PreferencesApiStub } from './preferencesApi'
import { useDevicesStore } from '../devices'
import { useAuditLogStore } from '../auditLog'
import { useVMsStore } from '../vms'
import { useContainersStore } from '../containers'
import { useInformationSystemsStore } from '../informationSystems'
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '../../utils/pageSize'

interface PagedStore {
  page: number
  pageSize: number
  pageSizeOptions: number[]
  pageCount: number
  pageItems: unknown[]
  setPage: (p: number) => void
  setPageSize: (size: number) => void
}

const range = (n: number) => Array.from({ length: n }, (_, i) => i)

const LISTS: Array<{ name: string; listId: string; make: () => PagedStore }> = [
  {
    name: 'устройства',
    listId: 'devices',
    make: () => {
      const s = useDevicesStore()
      s.all = range(200).map((i) => ({ id: `d${i}`, system_name: `dev-${i}`, serial_number: `SN-${i}`, stack_id: null })) as never
      return s as unknown as PagedStore
    },
  },
  {
    name: 'виртуальные машины',
    listId: 'vms',
    make: () => {
      const s = useVMsStore()
      s.all = range(200).map((i) => ({ id: `v${i}`, name: `vm-${i}` })) as never
      return s as unknown as PagedStore
    },
  },
  {
    name: 'контейнеры',
    listId: 'containers',
    make: () => {
      const s = useContainersStore()
      s.all = range(200).map((i) => ({ id: `c${i}`, name: `ct-${i}` })) as never
      return s as unknown as PagedStore
    },
  },
  {
    name: 'информационные системы',
    listId: 'informationSystems',
    make: () => {
      const s = useInformationSystemsStore()
      s.all = range(200).map((i) => ({ id: `s${i}`, name: `is-${i}` })) as never
      return s as unknown as PagedStore
    },
  },
]

let api: PreferencesApiStub

beforeEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
  setActivePinia(createPinia())
  api = stubPreferencesApi()
})

describe.each(LISTS)('количество строк на странице — $name', ({ listId, make }) => {
  it('по умолчанию 10 строк; варианты — 10 / 25 / 50 / 100, как у всех списков', () => {
    const store = make()
    expect(store.pageSize).toBe(DEFAULT_PAGE_SIZE)
    expect(store.pageSize).toBe(10)
    expect(store.pageSizeOptions).toEqual([10, 25, 50, 100])
    expect(store.pageItems).toHaveLength(10)
    expect(store.pageCount).toBe(20)
  })

  it('смена размера меняет число строк на странице и число страниц', () => {
    const store = make()

    store.setPageSize(50)

    expect(store.pageSize).toBe(50)
    expect(store.pageItems).toHaveLength(50)
    expect(store.pageCount).toBe(4)
  })

  it('остаётся на странице с тем же первым видимым элементом', () => {
    const store = make()
    store.setPage(6) // записи 51–60; индекс первой — 50
    const firstBefore = store.pageItems[0]

    store.setPageSize(25)

    expect(store.page).toBe(3) // по 25 запись с индексом 50 — первая на странице 3
    expect(store.pageItems[0]).toBe(firstBefore)
  })

  it('страница никогда не выходит за пределы после увеличения размера', () => {
    const store = make()
    store.setPage(store.pageCount)

    store.setPageSize(100)

    expect(store.page).toBeGreaterThanOrEqual(1)
    expect(store.page).toBeLessThanOrEqual(store.pageCount)
    expect(store.pageItems.length).toBeGreaterThan(0)
  })

  it('выбор запоминается на сервере для этого списка и восстанавливается новым стором после загрузки настроек', async () => {
    make().setPageSize(25)
    await flushPromises()
    expect(api.server.user.page_sizes).toEqual({ [listId]: 25 })
    expect(localStorage.getItem(`itr.pageSize.${listId}`)).toBeNull()

    // «Перезагрузка страницы»: новое приложение, настройки подтягиваются с сервера до создания стора списка.
    setActivePinia(createPinia())
    await usePreferencesStore().load({ userId: 'user-1', canWriteGlobal: false })
    expect(make().pageSize).toBe(25)
  })

  it.each([0, -1, 7, 12, 20, 1000, Number.NaN])('недопустимое значение %s игнорируется', (bad) => {
    const store = make()
    store.setPage(2)

    store.setPageSize(bad)

    expect(store.pageSize).toBe(DEFAULT_PAGE_SIZE)
    expect(store.page).toBe(2)
    expect(api.userPuts).toEqual([])
  })

  it('то же значение — ничего не меняет (страница остаётся)', () => {
    const store = make()
    store.setPage(4)
    store.setPageSize(DEFAULT_PAGE_SIZE)
    expect(store.page).toBe(4)
  })

  it('прежний сохранённый размер (6/12/24/48 и т. п.) не применяется: список открывается с 10 строками', async () => {
    await usePreferencesStore().load({ userId: 'user-1', canWriteGlobal: false })
    usePreferencesStore().user = { page_sizes: { [listId]: 24 } }
    expect(make().pageSize).toBe(DEFAULT_PAGE_SIZE)
  })
})

it('размер страницы одного списка не влияет на остальные', () => {
  useVMsStore().setPageSize(50)
  expect(useVMsStore().pageSize).toBe(50)
  expect(useContainersStore().pageSize).toBe(DEFAULT_PAGE_SIZE)
  expect(useAuditLogStore().pageSize).toBe(DEFAULT_PAGE_SIZE)
})

it('клиентские списки и журнал аудита берут шкалу из одного места', () => {
  for (const store of [useDevicesStore(), useVMsStore(), useContainersStore(), useInformationSystemsStore(), useAuditLogStore()]) {
    expect(store.pageSizeOptions).toEqual([...PAGE_SIZE_OPTIONS])
  }
})
