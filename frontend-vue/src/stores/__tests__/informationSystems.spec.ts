import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useInformationSystemsStore } from '../informationSystems'
import { informationSystemsFixture } from './fixtures'

beforeEach(() => {
  setActivePinia(createPinia())
  // /api/v1/information-systems - единственный эндпоинт в этом бэкенде, отдающий
  // ПЛОСКИЙ массив (не {items,total} и не {items,total,offset,limit}) - см. комментарий
  // в stores/informationSystems.ts. Мок это отражает буквально.
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(informationSystemsFixture))))
})

describe('useInformationSystemsStore', () => {
  it('загружает информационные системы плоским массивом', async () => {
    const store = useInformationSystemsStore()
    await store.ensureLoaded()
    expect(store.all).toHaveLength(3)
    expect(store.loaded).toBe(true)
  })

  it('фильтрует по подстроке (имя/описание/назначение/локализация)', async () => {
    const store = useInformationSystemsStore()
    await store.ensureLoaded()

    store.search = 'CRM'
    expect(store.filtered.map((s) => s.id)).toEqual(['is-2'])

    store.search = 'Крипто'
    expect(store.filtered.map((s) => s.id)).toEqual(['is-3'])

    store.search = ''
    expect(store.filtered).toHaveLength(3)
  })

  it('фильтрует по SIEM', async () => {
    const store = useInformationSystemsStore()
    await store.ensureLoaded()

    store.siemFilter = 'yes'
    expect(store.filtered.map((s) => s.id).sort()).toEqual(['is-1', 'is-3'])
    store.siemFilter = 'no'
    expect(store.filtered.map((s) => s.id)).toEqual(['is-2'])
  })

  it('не шлёт повторный запрос при повторном ensureLoaded()', async () => {
    const store = useInformationSystemsStore()
    await store.ensureLoaded()
    const callsAfterFirst = (fetch as ReturnType<typeof vi.fn>).mock.calls.length
    await store.ensureLoaded()
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsAfterFirst)
  })
})
