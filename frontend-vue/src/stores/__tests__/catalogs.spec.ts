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
})
