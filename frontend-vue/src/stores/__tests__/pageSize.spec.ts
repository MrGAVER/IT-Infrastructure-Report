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

const LISTS: Array<{ name: string; listId: string; defaultSize: number; make: () => PagedStore }> = [
  {
    name: 'устройства', listId: 'devices', defaultSize: 6,
    make: () => {
      const s = useDevicesStore()
      s.all = range(200).map((i) => ({ id: `d${i}`, system_name: `dev-${i}`, serial_number: `SN-${i}`, stack_id: null })) as never
      return s as unknown as PagedStore
    },
  },
  {
    name: 'виртуальные машины', listId: 'vms', defaultSize: 8,
    make: () => {
      const s = useVMsStore()
      s.all = range(200).map((i) => ({ id: `v${i}`, name: `vm-${i}` })) as never
      return s as unknown as PagedStore
    },
  },
  {
    name: 'контейнеры', listId: 'containers', defaultSize: 8,
    make: () => {
      const s = useContainersStore()
      s.all = range(200).map((i) => ({ id: `c${i}`, name: `ct-${i}` })) as never
      return s as unknown as PagedStore
    },
  },
  {
    name: 'информационные системы', listId: 'informationSystems', defaultSize: 8,
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

describe.each(LISTS)('количество строк на странице — $name', ({ listId, defaultSize, make }) => {
  it('по умолчанию сохраняется прежний размер страницы; варианты — x1, x2, x4, x8', () => {
    const store = make()
    expect(store.pageSize).toBe(defaultSize)
    expect(store.pageSizeOptions).toEqual([1, 2, 4, 8].map((m) => defaultSize * m))
    expect(store.pageItems).toHaveLength(defaultSize)
    expect(store.pageCount).toBe(Math.ceil(200 / defaultSize))
  })

  it('смена размера меняет число строк на странице и число страниц', () => {
    const store = make()

    store.setPageSize(defaultSize * 4)

    expect(store.pageSize).toBe(defaultSize * 4)
    expect(store.pageItems).toHaveLength(defaultSize * 4)
    expect(store.pageCount).toBe(Math.ceil(200 / (defaultSize * 4)))
  })

  it('остаётся на странице с тем же первым видимым элементом', () => {
    const store = make()
    store.setPage(3)
    const firstBefore = store.pageItems[0]

    store.setPageSize(defaultSize * 2)

    expect(store.page).toBe(2)
    expect(store.pageItems).toContain(firstBefore)
    expect(store.pageItems[0]).toBe(firstBefore) // 3-я страница по N = 2-я по 2N со сдвигом 0
  })

  it('страница никогда не выходит за пределы после уменьшения списка вариантов', () => {
    const store = make()
    store.setPage(store.pageCount)

    store.setPageSize(defaultSize * 8)

    expect(store.page).toBeGreaterThanOrEqual(1)
    expect(store.page).toBeLessThanOrEqual(store.pageCount)
    expect(store.pageItems.length).toBeGreaterThan(0)
  })

  it('выбор запоминается на сервере для этого списка и восстанавливается новым стором после загрузки настроек', async () => {
    make().setPageSize(defaultSize * 2)
    await flushPromises()
    expect(api.server.user.page_sizes).toEqual({ [listId]: defaultSize * 2 })
    expect(localStorage.getItem(`itr.pageSize.${listId}`)).toBeNull()

    // «Перезагрузка страницы»: новое приложение, настройки подтягиваются с сервера до создания стора списка.
    setActivePinia(createPinia())
    await usePreferencesStore().load({ identity: 'anonymous', canWriteGlobal: false })
    expect(make().pageSize).toBe(defaultSize * 2)
  })

  it.each([0, -1, 7, 1000, Number.NaN])('недопустимое значение %s игнорируется', (bad) => {
    const store = make()
    store.setPage(2)

    store.setPageSize(bad)

    expect(store.pageSize).toBe(defaultSize)
    expect(store.page).toBe(2)
    expect(api.userPuts).toEqual([])
  })

  it('то же значение — ничего не меняет (страница остаётся)', () => {
    const store = make()
    store.setPage(4)
    store.setPageSize(defaultSize)
    expect(store.page).toBe(4)
  })
})

it('размер страницы одного списка не влияет на остальные', () => {
  useVMsStore().setPageSize(32)
  expect(useVMsStore().pageSize).toBe(32)
  expect(useContainersStore().pageSize).toBe(8)
  expect(useAuditLogStore().pageSize).toBe(12)
})
