import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useVMsStore } from '../vms'
import { vmsFixture } from './fixtures'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(vmsFixture))),
  )
})

describe('useVMsStore', () => {
  it('загружает ВМ из {items,total}', async () => {
    const store = useVMsStore()
    await store.ensureLoaded()
    expect(store.total).toBe(2)
    expect(store.all).toHaveLength(2)
  })

  it('фильтрует по подстроке (название/назначение/описание)', async () => {
    const store = useVMsStore()
    await store.ensureLoaded()

    store.search = 'DB'
    expect(store.filtered.map((v) => v.id)).toEqual(['vm-1'])

    store.search = 'Приложение'
    expect(store.filtered.map((v) => v.id)).toEqual(['vm-2'])

    store.search = ''
    expect(store.filtered).toHaveLength(2)
  })
})
