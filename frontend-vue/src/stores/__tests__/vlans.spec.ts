import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useVLANsStore } from '../vlans'
import { vlanDashboardFixture } from './fixtures'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(vlanDashboardFixture))),
  )
})

describe('useVLANsStore', () => {
  it('загружает и группирует по vlan_id через /vlan-dashboard', async () => {
    const store = useVLANsStore()
    await store.ensureLoaded()
    expect(store.groups).toHaveLength(2)
    expect(store.definitionCount).toBe(3)
  })

  it('находит vlan_id с разными именами определений в разных доменах', async () => {
    const store = useVLANsStore()
    await store.ensureLoaded()
    // vlan 20 имеет два определения с разными именами (Гости / Гостевой сегмент)
    expect(store.conflictingVlanIds).toEqual([20])
  })

  it('фильтрует по подстроке — включая имя устройства во вложенном списке', async () => {
    const store = useVLANsStore()
    await store.ensureLoaded()

    store.search = 'sw-core'
    expect(store.filtered.map((g) => g.vlan_id)).toEqual([10])

    store.search = 'Гости'
    expect(store.filtered).toHaveLength(1)
    expect(store.filtered[0].definitions).toHaveLength(1)
    expect(store.filtered[0].definitions[0].name).toBe('Гости')

    store.search = ''
    expect(store.filtered).toHaveLength(2)
  })

  it('фильтр по несуществующему запросу возвращает пустой список групп', async () => {
    const store = useVLANsStore()
    await store.ensureLoaded()
    store.search = 'такого точно нет'
    expect(store.filtered).toHaveLength(0)
  })
})
