import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useContainersStore } from '../containers'
import type { Container } from '../../api/types'

function container(overrides: Partial<Container>): Container {
  return {
    id: 'ct-x',
    name: 'container',
    virtual_machine_id: null,
    physical_device_id: null,
    runtime: null,
    runtime_version: null,
    purpose: null,
    ...overrides,
  }
}

const fixtureItems: Container[] = [
  container({ id: 'ct-1', name: 'nginx-proxy', runtime: 'Docker', purpose: 'Обратный прокси' }),
  container({ id: 'ct-2', name: 'app-backend', runtime: 'containerd', purpose: 'Бэкенд приложения' }),
]

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('useContainersStore', () => {
  it('загружает контейнеры через generic /resources/containers', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ items: fixtureItems, total: 2, offset: 0, limit: 1000 })))
    vi.stubGlobal('fetch', fetchMock)

    const store = useContainersStore()
    await store.ensureLoaded()

    expect(store.all).toHaveLength(2)
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/resources/containers'), expect.anything())
  })

  it('ensureLoaded не перезапрашивает данные повторно', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ items: fixtureItems, total: 2, offset: 0, limit: 1000 })))
    vi.stubGlobal('fetch', fetchMock)

    const store = useContainersStore()
    await store.ensureLoaded()
    await store.ensureLoaded()

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('фильтрует по названию, runtime и назначению', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ items: fixtureItems, total: 2, offset: 0, limit: 1000 }))),
    )
    const store = useContainersStore()
    await store.ensureLoaded()

    store.search = 'nginx'
    expect(store.filtered.map((c) => c.id)).toEqual(['ct-1'])

    store.search = 'containerd'
    expect(store.filtered.map((c) => c.id)).toEqual(['ct-2'])

    store.search = 'Бэкенд'
    expect(store.filtered.map((c) => c.id)).toEqual(['ct-2'])

    store.search = ''
    expect(store.filtered).toHaveLength(2)
  })

  it('пагинирует по 10 записей на страницу', async () => {
    const many = Array.from({ length: 12 }, (_, i) => container({ id: `ct-${i}`, name: `container-${i}` }))
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ items: many, total: 12, offset: 0, limit: 1000 }))),
    )
    const store = useContainersStore()
    await store.ensureLoaded()

    expect(store.pageCount).toBe(2)
    expect(store.pageItems).toHaveLength(10)

    store.setPage(2)
    expect(store.pageItems).toHaveLength(2)

    store.setPage(99) // зажимается в границах
    expect(store.page).toBe(2)
  })
})
