import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useConnectionsStore } from '../connections'
import { useToast } from '../../composables/useToast'
import { connectionsFixture } from './fixtures'

beforeEach(() => {
  setActivePinia(createPinia())
  useToast().toasts.splice(0)
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(connectionsFixture))),
  )
})

// Общий кэш подключений (карта занятых портов, схема, формы). Постраничная таблица дашборда —
// отдельный стор, см. connectionsDashboard.spec.ts.
describe('useConnectionsStore (общий кэш)', () => {
  it('загружает подключения через /resources/connections ({items,total,offset,limit})', async () => {
    const store = useConnectionsStore()
    await store.ensureLoaded()
    expect(store.total).toBe(2)
    expect(store.all).toHaveLength(2)
    expect(store.loaded).toBe(true)
  })

  it('ensureLoaded() не перезагружает уже загруженный кэш', async () => {
    const store = useConnectionsStore()
    await store.ensureLoaded()
    await store.ensureLoaded()
    expect(fetch).toHaveBeenCalledTimes(1)
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

  it('ошибка загрузки попадает в error, а не в исключение', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: 'Сервер недоступен' }), { status: 500 })),
    )
    const store = useConnectionsStore()
    await store.reload()
    expect(store.error).toBe('Сервер недоступен')
    expect(store.loading).toBe(false)
  })

  it('R2-01: полная загрузка — без предупреждений', async () => {
    const store = useConnectionsStore()
    await store.ensureLoaded()
    expect(useToast().toasts).toHaveLength(0)
  })

  it('R2-01: усечённая загрузка (total больше, чем отдал сервер) — предупреждение, а данные при этом всё равно показываются', async () => {
    // сервер обещает 2 000 записей, а на дальнейшие страницы отвечает пустыми — загрузка прерывается с truncated=true
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const offset = Number(new URL(url, 'http://localhost').searchParams.get('offset'))
        const items = offset === 0 ? connectionsFixture.items : []
        return new Response(JSON.stringify({ ...connectionsFixture, items, total: 2000, offset }))
      }),
    )
    const store = useConnectionsStore()
    await store.ensureLoaded()

    expect(store.loaded).toBe(true)
    expect(store.all).toHaveLength(2)
    expect(useToast().toasts.filter((t) => t.type === 'warning' && t.message.includes('подключений'))).toHaveLength(1)
  })
})
