import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useConnectionsStore } from '../connections'
import { connectionsFixture } from './fixtures'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(connectionsFixture))))
})

describe('useConnectionsStore', () => {
  it('загружает подключения через /resources/connections ({items,total,offset,limit})', async () => {
    const store = useConnectionsStore()
    await store.ensureLoaded()
    expect(store.total).toBe(2)
    expect(store.all).toHaveLength(2)
  })

  it('фильтрует по подстроке (устройство/порт/назначение)', async () => {
    const store = useConnectionsStore()
    await store.ensureLoaded()

    store.search = 'Коммутатор'
    expect(store.filtered.map((c) => c.id)).toEqual(['c-2'])

    store.search = 'Передача'
    expect(store.filtered.map((c) => c.id)).toEqual(['c-1'])

    store.search = ''
    expect(store.filtered).toHaveLength(2)
  })

  it('фильтрует по активности', async () => {
    const store = useConnectionsStore()
    await store.ensureLoaded()

    store.activeFilter = 'yes'
    expect(store.filtered.map((c) => c.id)).toEqual(['c-1'])
    store.activeFilter = 'no'
    expect(store.filtered.map((c) => c.id)).toEqual(['c-2'])
  })

  it('occupiedInterfaceIds включает порты только активных подключений', async () => {
    const store = useConnectionsStore()
    await store.ensureLoaded()

    const occupied = store.occupiedInterfaceIds
    // c-1 активно -> if-1/if-2 заняты; c-2 неактивно -> if-3/if-4 свободны
    expect(occupied.has('if-1')).toBe(true)
    expect(occupied.has('if-2')).toBe(true)
    expect(occupied.has('if-3')).toBe(false)
    expect(occupied.has('if-4')).toBe(false)
  })
})
