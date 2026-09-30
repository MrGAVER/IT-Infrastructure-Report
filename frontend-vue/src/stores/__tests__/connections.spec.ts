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

  it('фильтрует по подстроке (устройство/порт/тип линии/роль порта)', async () => {
    const store = useConnectionsStore()
    await store.ensureLoaded()

    store.search = 'Коммутатор'
    expect(store.filtered.map((c) => c.id)).toEqual(['c-2'])

    // c-1: данные/данные; c-2: управление/данные — «управление» есть только у c-2.
    store.search = 'управление'
    expect(store.filtered.map((c) => c.id)).toEqual(['c-2'])

    store.search = 'передача данных'
    expect(store.filtered.map((c) => c.id)).toEqual(['c-1', 'c-2'])

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

  describe('проверка ролей портов-соседей', () => {
    it('счётчики считаются по всем подключениям, а не по отфильтрованным', async () => {
      const store = useConnectionsStore()
      await store.ensureLoaded()
      store.search = 'нет такого'

      expect(store.mismatchCount).toBe(1)
      expect(store.approvedCount).toBe(0)
    })

    it('portConfigFilter оставляет только подключения с выбранным статусом', async () => {
      const store = useConnectionsStore()
      await store.ensureLoaded()

      store.portConfigFilter = 'mismatch'
      expect(store.filtered.map((c) => c.id)).toEqual(['c-2'])
      store.portConfigFilter = 'ok'
      expect(store.filtered.map((c) => c.id)).toEqual(['c-1'])
      store.portConfigFilter = 'approved'
      expect(store.filtered).toEqual([])
      store.portConfigFilter = 'all'
      expect(store.filtered).toHaveLength(2)
    })

    it('фильтр статуса комбинируется с поиском и фильтром активности', async () => {
      const store = useConnectionsStore()
      await store.ensureLoaded()

      store.portConfigFilter = 'mismatch'
      store.activeFilter = 'yes' // c-2 неактивно
      expect(store.filtered).toEqual([])
      store.activeFilter = 'no'
      store.search = 'Файрвол'
      expect(store.filtered.map((c) => c.id)).toEqual(['c-2'])
    })

    it('approve() отправляет id, подставляет обновлённые строки в список и возвращает результат', async () => {
      const store = useConnectionsStore()
      await store.ensureLoaded()
      const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) =>
        new Response(JSON.stringify({ items: [{ ...store.all[1], port_config_status: 'approved' }], skipped_ids: [] })),
      )
      vi.stubGlobal('fetch', fetchMock)

      const result = await store.approve(['c-2'])

      expect(JSON.parse(fetchMock.mock.calls[0][1]!.body as string)).toEqual({ connection_ids: ['c-2'] })
      expect(result.skipped_ids).toEqual([])
      expect(store.all[1].port_config_status).toBe('approved')
      expect(store.all[0].port_config_status).toBe('ok')
      expect(store.mismatchCount).toBe(0)
      expect(store.approvedCount).toBe(1)
    })

    it('revokeApproval() возвращает строку в статус расхождения', async () => {
      const store = useConnectionsStore()
      await store.ensureLoaded()
      store.all[1].port_config_status = 'approved'
      vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...store.all[1], port_config_status: 'mismatch' }))))

      await store.revokeApproval('c-2')

      expect(store.all[1].port_config_status).toBe('mismatch')
    })

    it('ошибка approve() не меняет список и пробрасывается вызывающему', async () => {
      const store = useConnectionsStore()
      await store.ensureLoaded()
      vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Подключение не найдено: c-2' }), { status: 404 })))

      await expect(store.approve(['c-2'])).rejects.toThrow('Подключение не найдено')
      expect(store.all[1].port_config_status).toBe('mismatch')
    })
  })
})
