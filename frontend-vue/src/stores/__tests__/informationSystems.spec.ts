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

  describe('поиск по IP-адресам', () => {
    async function loadWithIps() {
      const store = useInformationSystemsStore()
      await store.ensureLoaded()
      // is-1 — два адреса (один ВМ, с префиксом), is-2 — один, у is-3 поля в ответе нет (старый ответ/созданная запись)
      store.all = store.all.map((s) => {
        if (s.id === 'is-1') return { ...s, ip_addresses: ['10.1.1.5', '192.168.5.10/24'] }
        if (s.id === 'is-2') return { ...s, ip_addresses: ['172.16.0.7'] }
        return s
      })
      return store
    }

    it('находит систему по адресу целиком', async () => {
      const store = await loadWithIps()
      store.search = '172.16.0.7'
      expect(store.filtered.map((s) => s.id)).toEqual(['is-2'])
    })

    it('находит по началу адреса и по адресу с префиксом', async () => {
      const store = await loadWithIps()
      store.search = '10.1.'
      expect(store.filtered.map((s) => s.id)).toEqual(['is-1'])

      store.search = '192.168.5.10/24'
      expect(store.filtered.map((s) => s.id)).toEqual(['is-1'])

      store.search = '192.168.5.10' // без префикса — тоже находит
      expect(store.filtered.map((s) => s.id)).toEqual(['is-1'])
    })

    it('несуществующий адрес не находит ничего; ИС без поля ip_addresses не ломает поиск по тексту', async () => {
      const store = await loadWithIps()
      store.search = '8.8.8.8'
      expect(store.filtered).toEqual([])

      store.search = 'Крипто' // is-3 без ip_addresses по-прежнему находится по тексту
      expect(store.filtered.map((s) => s.id)).toEqual(['is-3'])
    })

    it('работает вместе с фильтром SIEM', async () => {
      const store = await loadWithIps()
      store.search = '10.1.1.5'
      store.siemFilter = 'no'
      expect(store.filtered).toEqual([])
      store.siemFilter = 'yes'
      expect(store.filtered.map((s) => s.id)).toEqual(['is-1'])
    })
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
