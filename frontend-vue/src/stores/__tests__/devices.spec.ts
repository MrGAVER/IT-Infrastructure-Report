import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useDevicesStore } from '../devices'
import { useCatalogsStore } from '../catalogs'
import { devicesFixture, structuralUnitsFixture, buildingsFixture, deviceTypesFixture } from './fixtures'

function stubApi() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/devices')) return new Response(JSON.stringify(devicesFixture))
      if (url.includes('/resources/structural-units')) return new Response(JSON.stringify(structuralUnitsFixture))
      if (url.includes('/resources/buildings')) return new Response(JSON.stringify(buildingsFixture))
      if (url.includes('/resources/device-types')) return new Response(JSON.stringify(deviceTypesFixture))
      return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
    }),
  )
}

beforeEach(() => {
  setActivePinia(createPinia())
  stubApi()
})

describe('useDevicesStore', () => {
  it('загружает устройства с /api/v1/devices', async () => {
    const store = useDevicesStore()
    await store.ensureLoaded()
    expect(store.total).toBe(3)
    expect(store.all).toHaveLength(3)
  })

  it('фильтрует по подстроке поиска (имя/серийник/IP)', async () => {
    const store = useDevicesStore()
    await store.ensureLoaded()

    store.search = 'srv-db'
    expect(store.filtered.map((d) => d.id)).toEqual(['dev-1'])

    store.search = '10.10.1.'
    expect(store.filtered).toHaveLength(2)

    store.search = ''
    expect(store.filtered).toHaveLength(3)
  })

  it('фильтрует по SIEM', async () => {
    const store = useDevicesStore()
    await store.ensureLoaded()

    store.siemFilter = 'yes'
    expect(store.filtered).toHaveLength(2)
    store.siemFilter = 'no'
    expect(store.filtered.map((d) => d.id)).toEqual(['dev-3'])
  })

  it('фильтрует по зданию и типу устройства', async () => {
    const store = useDevicesStore()
    await store.ensureLoaded()

    store.buildingId = 'b-b'
    expect(store.filtered.map((d) => d.id)).toEqual(['dev-3'])
    store.buildingId = ''

    store.deviceTypeId = 'dt-net'
    expect(store.filtered.map((d) => d.id)).toEqual(['dev-3'])
  })

  it('фильтр по структурной единице включает устройства из зданий дочерних единиц', async () => {
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()
    const store = useDevicesStore()
    await store.ensureLoaded()

    // root-1 "Дирекция ИТ" -> потомок child-1 "Отдел эксплуатации" -> здание b-a -> dev-1, dev-2
    store.structuralUnitIds = ['root-1']
    expect(store.filtered.map((d) => d.id).sort()).toEqual(['dev-1', 'dev-2'])

    // root-2 "Служба безопасности" -> здание b-b -> dev-3
    store.structuralUnitIds = ['root-2']
    expect(store.filtered.map((d) => d.id)).toEqual(['dev-3'])
  })

  it('пагинирует по 6 записей на страницу и сбрасывает страницу', async () => {
    const store = useDevicesStore()
    await store.ensureLoaded()
    expect(store.pageCount).toBe(1) // всего 3 устройства — 1 страница
    store.setPage(5)
    expect(store.page).toBe(1) // не может выйти за pageCount
  })
})
