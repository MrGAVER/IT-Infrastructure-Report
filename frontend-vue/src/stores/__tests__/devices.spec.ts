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
      if (/\/resources$/.test(url)) return new Response(JSON.stringify([]))
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

  // Регресс на баг: DevicesView.vue грузит devices/catalogs/vlans параллельно
  // (Promise.all), и filtered — реактивный getter, к которому Vue может обратиться в рендере
  // раньше, чем ОБА промиса резолвнутся. Раньше это навсегда "запирало" пустой индекс зданий
  // внутри catalogs.indexOf('buildings') (см. catalogs.spec.ts) — и фильтр по структурной
  // единице после этого не находил вообще ничего, даже когда здания благополучно догружались.
  it('фильтр по структурной единице переживает раннее (до catalogs.ensureLoaded()) обращение к filtered', async () => {
    const catalogs = useCatalogsStore()
    const store = useDevicesStore()
    await store.ensureLoaded()

    // Здания ещё не загружены (catalogs.items['buildings'] пуст) — но фильтр уже применён, как
    // если бы Vue успел отрисовать таблицу до резолва catalogs.ensureLoaded() из другого Promise.all.
    store.structuralUnitIds = ['root-1']
    expect(store.filtered).toEqual([]) // ожидаемо пусто — buildings ещё не пришли

    // Справочники догрузились уже ПОСЛЕ первого обращения к filtered выше.
    await catalogs.ensureLoaded()
    expect(store.filtered.map((d) => d.id).sort()).toEqual(['dev-1', 'dev-2'])
  })

  it('страница не выходит за pageCount: на трёх устройствах она одна', async () => {
    const store = useDevicesStore()
    await store.ensureLoaded()
    expect(store.pageCount).toBe(1) // всего 3 устройства — 1 страница
    store.setPage(5)
    expect(store.page).toBe(1) // не может выйти за pageCount
  })

  it('группирует участников одного стека в одну строку, отсортированную по позиции', async () => {
    const store = useDevicesStore()
    await store.ensureLoaded()
    // dev-1 и dev-2 — участники одного стека; позиции намеренно в обратном алфавиту порядке
    // (dev-2 первый, dev-1 второй), чтобы отличить сортировку по stack_position от случайного
    // совпадения с порядком в fixture. dev-3 остаётся одиночным устройством.
    store.all = store.all.map((d) => {
      if (d.id === 'dev-1') return { ...d, stack_id: 'stack-1', stack_name: 'Стек ядра', stack_position: 2 }
      if (d.id === 'dev-2') return { ...d, stack_id: 'stack-1', stack_name: 'Стек ядра', stack_position: 1 }
      return d
    })

    const rows = store.groupedFiltered
    expect(rows).toHaveLength(2) // одна строка на стек (2 участника схлопнуты) + одна на dev-3
    const stackRow = rows.find((r) => r.kind === 'stack')
    expect(stackRow?.kind === 'stack' && stackRow.stackName).toBe('Стек ядра')
    expect(stackRow?.kind === 'stack' && stackRow.members.map((m) => m.id)).toEqual(['dev-2', 'dev-1'])
    const deviceRow = rows.find((r) => r.kind === 'device')
    expect(deviceRow?.kind === 'device' && deviceRow.device.id).toBe('dev-3')
  })

  it('стек занимает один слот пагинации независимо от числа участников', async () => {
    const store = useDevicesStore()
    await store.ensureLoaded()
    store.all = store.all.map((d) => (d.id === 'dev-1' || d.id === 'dev-2' ? { ...d, stack_id: 'stack-1', stack_name: 'Стек ядра', stack_position: 1 } : d))
    // 3 "сырых" устройства, но 2 строки (1 стек + 1 одиночное устройство) — по-прежнему 1 страница.
    expect(store.groupedFiltered).toHaveLength(2)
    expect(store.pageCount).toBe(1)
  })

  it('сортирует устройства естественным порядком: dev-6 раньше dev-12, без имени — первыми (UI-13)', async () => {
    const base = devicesFixture.items[0]
    const named = (id: string, system_name: string | null) => ({ ...base, id, system_name, stack_id: null, stack_name: null, stack_position: null })
    const payload = { items: [named('d12', 'dev-12'), named('d6', 'dev-6'), named('d0', null), named('d1', 'dev-1')], total: 4, offset: 0, limit: 1000 }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(payload))),
    )
    const store = useDevicesStore()

    await store.reload()

    expect(store.all.map((d) => d.id)).toEqual(['d0', 'd1', 'd6', 'd12'])
    expect(store.filtered.map((d) => d.id)).toEqual(['d0', 'd1', 'd6', 'd12'])
  })
})
