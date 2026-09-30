import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCatalogsStore } from '../catalogs'
import { structuralUnitsFixture, buildingsFixture, deviceTypesFixture } from './fixtures'

function mockFetchFor() {
  const byResource: Record<string, unknown> = {
    'structural-units': structuralUnitsFixture,
    buildings: buildingsFixture,
    'device-types': deviceTypesFixture,
  }
  return vi.fn(async (url: string) => {
    // /api/v1/resources (без ключа ресурса после) — отдельный эндпоинт, список
    // ВСЕХ ресурсов с человекочитаемым именем (см. stores/catalogs.ts:
    // resourceNames), форма ответа — голый массив, а не {items,total,...}.
    // Не должен попадать под /resources/{key} ниже.
    if (/\/resources$/.test(url)) {
      return new Response(JSON.stringify([{ key: 'devices', name: 'Физические устройства' }]))
    }
    const match = url.match(/\/resources\/([a-z-]+)/)
    const key = match?.[1] ?? ''
    const body = byResource[key] ?? { items: [], total: 0, offset: 0, limit: 1000 }
    return new Response(JSON.stringify(body), { status: 200 })
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('useCatalogsStore', () => {
  it('загружает каталоги и резолвит имя по id', async () => {
    vi.stubGlobal('fetch', mockFetchFor())
    const store = useCatalogsStore()
    await store.ensureLoaded()

    expect(store.loaded).toBe(true)
    expect(store.label('device-types', 'dt-server')).toBe('Сервер')
    expect(store.label('buildings', 'b-a')).toBe('Корпус А')
    expect(store.label('buildings', null)).toBe('—')
    expect(store.label('buildings', 'unknown-id')).toBe('—')
  })

  it('строит дерево структурных единиц по parent_id (та же схема, что Department)', async () => {
    vi.stubGlobal('fetch', mockFetchFor())
    const store = useCatalogsStore()
    await store.ensureLoaded()

    const tree = store.structuralUnitTree
    expect(tree).toHaveLength(2) // два корня: "Дирекция ИТ" и "Служба безопасности"
    const dirIT = tree.find((n) => n.id === 'root-1')
    expect(dirIT?.children).toHaveLength(1)
    expect(dirIT?.children[0].id).toBe('child-1')
  })

  it('разворачивает выбор родительской единицы на всех потомков', async () => {
    vi.stubGlobal('fetch', mockFetchFor())
    const store = useCatalogsStore()
    await store.ensureLoaded()

    const ids = store.unitAndDescendantIds('root-1')
    expect(ids).toEqual(new Set(['root-1', 'child-1']))

    // Единица без детей — возвращает только себя.
    const leafIds = store.unitAndDescendantIds('child-1')
    expect(leafIds).toEqual(new Set(['child-1']))
  })

  it('не шлёт повторный запрос при повторном ensureLoaded()', async () => {
    const fetchMock = mockFetchFor()
    vi.stubGlobal('fetch', fetchMock)
    const store = useCatalogsStore()
    await store.ensureLoaded()
    const callsAfterFirst = fetchMock.mock.calls.length
    await store.ensureLoaded()
    expect(fetchMock.mock.calls.length).toBe(callsAfterFirst)
  })

  it('резолвит человекочитаемое имя ресурса для журнала аудита через /api/v1/resources', async () => {
    vi.stubGlobal('fetch', mockFetchFor())
    const store = useCatalogsStore()
    await store.ensureLoaded()

    expect(store.resourceLabel('devices')).toBe('Физические устройства')
    // Неизвестный ключ — просто возвращаем сам ключ как fallback, не падаем.
    expect(store.resourceLabel('unknown-resource')).toBe('unknown-resource')
  })

  it('replaceDeviceInterfaces точечно заменяет порты одного устройства, не трогая чужие', () => {
    const store = useCatalogsStore()
    store.items['interfaces'] = [
      { id: 'if-1', name: 'eth0', physical_device_id: 'dev-1' },
      { id: 'if-2', name: 'eth1', physical_device_id: 'dev-1' },
      { id: 'if-3', name: 'eth0', physical_device_id: 'dev-2' },
    ]

    store.replaceDeviceInterfaces('dev-1', [{ id: 'if-1', name: 'eth0-renamed', physical_device_id: 'dev-1' }])

    expect(store.items['interfaces']).toEqual([
      { id: 'if-3', name: 'eth0', physical_device_id: 'dev-2' },
      { id: 'if-1', name: 'eth0-renamed', physical_device_id: 'dev-1' },
    ])
  })

  it('replaceInterface заменяет один порт по id, не трогая остальные порты того же устройства', () => {
    const store = useCatalogsStore()
    store.items['interfaces'] = [
      { id: 'if-1', name: 'eth0', physical_device_id: 'dev-1', is_management: false },
      { id: 'if-2', name: 'eth1', physical_device_id: 'dev-1', is_management: false },
    ]

    store.replaceInterface({ id: 'if-2', name: 'eth1', physical_device_id: 'dev-1', is_management: true })

    expect(store.items['interfaces']).toEqual([
      { id: 'if-1', name: 'eth0', physical_device_id: 'dev-1', is_management: false },
      { id: 'if-2', name: 'eth1', physical_device_id: 'dev-1', is_management: true },
    ])
  })

  it('replaceInterface не добавляет порт, которого нет в каталоге, и не падает на незагруженном каталоге', () => {
    const store = useCatalogsStore()
    expect(() => store.replaceInterface({ id: 'if-x', name: 'x', physical_device_id: 'dev-1' })).not.toThrow()
    expect(store.items['interfaces']).toBeUndefined()

    store.items['interfaces'] = [{ id: 'if-1', name: 'eth0', physical_device_id: 'dev-1' }]
    store.replaceInterface({ id: 'if-x', name: 'x', physical_device_id: 'dev-1' })
    expect(store.items['interfaces']).toEqual([{ id: 'if-1', name: 'eth0', physical_device_id: 'dev-1' }])
  })

  it('replaceDeviceInterfaces на ещё не загруженный каталог просто ничего не показывает (без падения)', () => {
    const store = useCatalogsStore()
    expect(() => store.replaceDeviceInterfaces('dev-1', [{ id: 'if-1', name: 'eth0', physical_device_id: 'dev-1' }])).not.toThrow()
    expect(store.items['interfaces']).toEqual([{ id: 'if-1', name: 'eth0', physical_device_id: 'dev-1' }])
  })

  // Регресс на баг: indexOf()/label() кешировали Map по ИМЕНИ каталога, а не по массиву — если
  // компонент успевал спросить лукап раньше, чем catalogs.reload() резолвился (обычная гонка при
  // параллельной загрузке нескольких сторов на одном экране), пустой результат навсегда "запирал"
  // этот ключ, и вновь добавленная через QuickAddModal запись показывалась как "—" до полной
  // перезагрузки страницы (см. п.3.7 фикса).
  it('label() видит запись, добавленную в каталог ПОСЛЕ первого (ещё до загрузки) обращения к indexOf', () => {
    const store = useCatalogsStore()
    // Обращение до заполнения items['embedded-os'] — имитирует раннюю отрисовку select'а.
    expect(store.indexOf('embedded-os').get('os-new')).toBeUndefined()
    expect(store.label('embedded-os', 'os-new')).toBe('—')

    // Каталог "догрузился" — новая запись появилась (или её только что создали через QuickAdd).
    store.items = { ...store.items, 'embedded-os': [{ id: 'os-new', name: 'RouterOS', version: '7.1' }] }

    expect(store.label('embedded-os', 'os-new')).toBe('RouterOS 7.1')
  })

  it('reload(): сбой одного каталога не мешает загрузиться остальным', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (/\/resources$/.test(url)) return new Response(JSON.stringify([]))
        if (url.includes('/resources/buildings')) throw new Error('network error')
        const match = url.match(/\/resources\/([a-z-]+)/)
        const key = match?.[1] ?? ''
        const byResource: Record<string, unknown> = { 'device-types': deviceTypesFixture }
        return new Response(JSON.stringify(byResource[key] ?? { items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )
    const store = useCatalogsStore()
    await store.ensureLoaded()

    expect(store.loaded).toBe(true) // не должно "зависать" в незагруженном состоянии целиком
    expect(store.label('device-types', 'dt-server')).toBe('Сервер') // другие каталоги пришли нормально
    expect(store.error).toContain('buildings') // но о частичном сбое сообщаем
  })

  // Фикс п.4.2: "во всех полях с выпадающим текстом на всех формах должна быть применена
  // сортировка" — сортируется один раз в сторе, при записи в items[key], а не в каждом
  // потребляющем select по отдельности.
  describe('сортировка каталогов (фикс п.4.2)', () => {
    it('reload() сортирует обычный каталог по name (регистронезависимо, кириллица)', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          if (/\/resources$/.test(url)) return new Response(JSON.stringify([]))
          if (url.includes('/resources/manufacturers')) {
            return new Response(
              JSON.stringify({
                items: [
                  { id: 'mf-3', name: 'юником' },
                  { id: 'mf-1', name: 'аквариус' }, // строчная — sensitivity:'base' не должна перевесить алфавитный порядок
                  { id: 'mf-2', name: 'Крафтвэй' },
                ],
                total: 3,
                offset: 0,
                limit: 1000,
              }),
            )
          }
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )
      const store = useCatalogsStore()
      await store.ensureLoaded()

      expect(store.items['manufacturers'].map((m) => m.id)).toEqual(['mf-1', 'mf-2', 'mf-3'])
    })

    it('reload() сортирует operating-systems/embedded-os по (name, version) — версии внутри одного имени по числовому порядку, не лексикографически', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          if (/\/resources$/.test(url)) return new Response(JSON.stringify([]))
          if (url.includes('/resources/operating-systems')) {
            return new Response(
              JSON.stringify({
                items: [
                  // Лексикографически "10" < "9" (сравнение посимвольно: '1' < '9'), а по смыслу
                  // версии 9 должна идти раньше 10 — именно это и проверяем numeric:true.
                  { id: 'os-v10', name: 'Windows Server', version: '10' },
                  { id: 'os-v9', name: 'Windows Server', version: '9' },
                  { id: 'os-ubuntu', name: 'Ubuntu', version: '22.04' },
                ],
                total: 3,
                offset: 0,
                limit: 1000,
              }),
            )
          }
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )
      const store = useCatalogsStore()
      await store.ensureLoaded()

      // "Ubuntu" перед "Windows Server" (по имени), а внутри "Windows Server" — 9 перед 10.
      expect(store.items['operating-systems'].map((o) => o.id)).toEqual(['os-ubuntu', 'os-v9', 'os-v10'])
    })

    it('reload() сортирует interfaces через natural sort — Gi1/0/2 перед Gi1/0/19 (фикс п.3.5)', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          if (/\/resources$/.test(url)) return new Response(JSON.stringify([]))
          if (url.includes('/resources/interfaces')) {
            return new Response(
              JSON.stringify({
                items: [
                  { id: 'if-19', name: 'Gi1/0/19', physical_device_id: 'dev-1' },
                  { id: 'if-2', name: 'Gi1/0/2', physical_device_id: 'dev-1' },
                  { id: 'if-9', name: 'Gi1/0/9', physical_device_id: 'dev-1' },
                ],
                total: 3,
                offset: 0,
                limit: 1000,
              }),
            )
          }
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )
      const store = useCatalogsStore()
      await store.ensureLoaded()

      expect(store.items['interfaces'].map((i) => i.id)).toEqual(['if-2', 'if-9', 'if-19'])
    })

    it('addCatalogItem() вставляет новую запись по алфавиту, а не в конец списка', () => {
      const store = useCatalogsStore()
      store.items['manufacturers'] = [
        { id: 'mf-1', name: 'Cisco' },
        { id: 'mf-2', name: 'Huawei' },
      ]

      store.addCatalogItem('manufacturers', { id: 'mf-new', name: 'Dell' })

      expect(store.items['manufacturers'].map((m) => m.id)).toEqual(['mf-1', 'mf-new', 'mf-2'])
    })

    it('addCatalogItem() на ещё не загруженный каталог всё равно добавляет запись (как раньше делал прямой push в QuickAddModal.vue)', () => {
      const store = useCatalogsStore()
      store.addCatalogItem('manufacturers', { id: 'mf-new', name: 'Dell' })
      expect(store.items['manufacturers']).toEqual([{ id: 'mf-new', name: 'Dell' }])
    })

    it('replaceDeviceInterfaces() сохраняет natural sort после точечной замены (фикс п.3.5 при сохранении портов из DevicePortsModal.vue)', () => {
      const store = useCatalogsStore()
      store.items['interfaces'] = [
        { id: 'if-2', name: 'Gi1/0/2', physical_device_id: 'dev-1' },
        { id: 'if-19', name: 'Gi1/0/19', physical_device_id: 'dev-1' },
      ]

      store.replaceDeviceInterfaces('dev-1', [
        { id: 'if-2', name: 'Gi1/0/2', physical_device_id: 'dev-1' },
        { id: 'if-19', name: 'Gi1/0/19', physical_device_id: 'dev-1' },
        { id: 'if-9', name: 'Gi1/0/9', physical_device_id: 'dev-1' },
      ])

      expect(store.items['interfaces'].map((i) => i.id)).toEqual(['if-2', 'if-9', 'if-19'])
    })
  })
})
