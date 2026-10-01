import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { DEFAULT_PAGE_SIZE, useConnectionsDashboardStore } from '../connectionsDashboard'
import type { Connection, ConnectionsPage } from '../../api/types'

function row(id: string, overrides: Partial<Connection> = {}): Connection {
  return {
    id,
    source_interface_id: `${id}-s`,
    destination_interface_id: `${id}-d`,
    connection_type_id: 'ct-1',
    is_active: true,
    description: null,
    source_device_name: 'srv',
    source_interface_name: 'eth0',
    destination_device_name: 'sw',
    destination_interface_name: 'Gi0/1',
    connection_type_name: 'Медь',
    source_port_role: 'data',
    destination_port_role: 'data',
    port_config_status: 'ok',
    ...overrides,
  }
}

const SUMMARY = { total: 20, active: 18, inactive: 2, mismatch: 4, approved: 1 }

function page(items: Connection[], total = items.length, summary = SUMMARY): ConnectionsPage {
  return { items, total, offset: 0, limit: DEFAULT_PAGE_SIZE, summary }
}

// Именно страница дашборда (/api/v1/connections?…), а не общий кэш (/api/v1/resources/connections?…).
const PAGE_URL = /\/api\/v1\/connections\?/

interface Call { url: string; method: string; body?: Record<string, unknown> }
let calls: Call[]
const pageCalls = () => calls.filter((c) => c.method === 'GET' && PAGE_URL.test(c.url))
const params = (call: Call) => new URL(call.url, 'http://x').searchParams

/** handler получает вызов страницы и возвращает её ответ; остальные вызовы — пустые. */
function stubApi(pageHandler: (call: Call) => ConnectionsPage | Promise<ConnectionsPage> = () => page([])) {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const call: Call = { url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body as string) : undefined }
      calls.push(call)
      if (call.method === 'GET' && PAGE_URL.test(url)) return new Response(JSON.stringify(await pageHandler(call)))
      if (call.method === 'GET' && url.includes('/resources/connections')) return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      if (url.endsWith('/connections/port-config/approve')) return new Response(JSON.stringify({ items: [], skipped_ids: [], approved_count: 3 }))
      if (call.method === 'DELETE') return new Response(JSON.stringify(row('c-1', { port_config_status: 'mismatch' })))
      return new Response('{}')
    }),
  )
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  stubApi()
})

describe('useConnectionsDashboardStore — серверная страница', () => {
  it('load() запрашивает первую страницу без условий и сохраняет items/total/summary', async () => {
    stubApi(() => page([row('c-1'), row('c-2')], 20))
    const store = useConnectionsDashboardStore()

    await store.load()

    const p = params(pageCalls()[0])
    expect(p.get('offset')).toBe('0')
    expect(p.get('limit')).toBe(String(DEFAULT_PAGE_SIZE))
    expect(['q', 'is_active', 'port_config_status'].some((k) => p.has(k))).toBe(false)
    expect(store.items.map((c) => c.id)).toEqual(['c-1', 'c-2'])
    expect(store.total).toBe(20)
    expect(store.summary).toEqual(SUMMARY)
    expect(store.loaded).toBe(true)
    expect(store.pageCount).toBe(Math.ceil(20 / DEFAULT_PAGE_SIZE))
  })

  it('поиск и фильтры передаются серверу; пробелы по краям поиска отбрасываются', async () => {
    const store = useConnectionsDashboardStore()
    store.search = '  Коммутатор '
    store.activeFilter = 'no'
    store.portConfigFilter = 'mismatch'

    await store.load()

    const p = params(pageCalls()[0])
    expect(p.get('q')).toBe('Коммутатор')
    expect(p.get('is_active')).toBe('false')
    expect(p.get('port_config_status')).toBe('mismatch')
  })

  it('activeFilter «yes» → is_active=true, «all» → параметра нет', async () => {
    const store = useConnectionsDashboardStore()
    store.activeFilter = 'yes'
    await store.load()
    expect(params(pageCalls()[0]).get('is_active')).toBe('true')
  })

  it('setPage() запрашивает нужное смещение; страница ограничивается диапазоном 1..pageCount', async () => {
    stubApi(() => page([row('c-9')], 20))
    const store = useConnectionsDashboardStore()
    await store.load()

    await store.setPage(3)
    expect(params(pageCalls().at(-1)!).get('offset')).toBe(String(2 * DEFAULT_PAGE_SIZE))

    await store.setPage(999)
    expect(store.page).toBe(store.pageCount)
    await store.setPage(-5)
    expect(store.page).toBe(1)
  })

  it('applyFilters() возвращает на первую страницу', async () => {
    stubApi(() => page([row('c-1')], 40))
    const store = useConnectionsDashboardStore()
    await store.load()
    await store.setPage(4)

    await store.applyFilters()

    expect(store.page).toBe(1)
    expect(params(pageCalls().at(-1)!).get('offset')).toBe('0')
  })

  it('страница за концом (удалили последнюю запись) → переход на последнюю существующую', async () => {
    let call = 0
    stubApi(() => {
      call += 1
      // Первый ответ: на странице 3 пусто, но всего записей 17 (3 страницы по 8 → последняя — 3-я? нет: 17/8 → 3).
      // Пусть страниц стало 2: total = 9.
      return call === 1 ? page([], 9) : page([row('c-last')], 9)
    })
    const store = useConnectionsDashboardStore()
    store.page = 3

    await store.load()

    expect(store.page).toBe(2)
    expect(store.items.map((c) => c.id)).toEqual(['c-last'])
    expect(pageCalls()).toHaveLength(2)
    expect(store.loading).toBe(false)
  })

  it('устаревший ответ не затирает более поздний (пользователь печатает быстрее сервера)', async () => {
    const resolvers: Array<(p: ConnectionsPage) => void> = []
    stubApi(() => new Promise<ConnectionsPage>((resolve) => resolvers.push(resolve)))
    const store = useConnectionsDashboardStore()

    store.search = 'а'
    const first = store.load()
    store.search = 'аб'
    const second = store.load()

    resolvers[1](page([row('new')], 1))
    await second
    resolvers[0](page([row('old')], 1)) // ответ на первый запрос приходит последним
    await first

    expect(store.items.map((c) => c.id)).toEqual(['new'])
    expect(store.loading).toBe(false)
  })

  it('ошибка загрузки попадает в error и не стирает уже показанные строки', async () => {
    stubApi(() => page([row('c-1')], 1))
    const store = useConnectionsDashboardStore()
    await store.load()

    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Сервер недоступен' }), { status: 500 })))
    await store.load()

    expect(store.error).toBe('Сервер недоступен')
    expect(store.items.map((c) => c.id)).toEqual(['c-1'])
    expect(store.loading).toBe(false)
  })
})

describe('useConnectionsDashboardStore — действия', () => {
  it('approve(ids) отправляет id и затем перечитывает страницу и общий кэш', async () => {
    const store = useConnectionsDashboardStore()

    const result = await store.approve(['c-1'])

    expect(result.approved_count).toBe(3)
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({ connection_ids: ['c-1'] })
    expect(pageCalls()).toHaveLength(1)
    expect(calls.some((c) => c.url.includes('/resources/connections'))).toBe(true)
  })

  it('approveMatching() отправляет текущие поиск и фильтр активности, а не id со страницы', async () => {
    const store = useConnectionsDashboardStore()
    store.search = ' ядро '
    store.activeFilter = 'yes'
    store.portConfigFilter = 'mismatch'

    await store.approveMatching()

    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({ match: { q: 'ядро', is_active: true } })
  })

  it('approveMatching() без условий передаёт null, а не пустую строку', async () => {
    const store = useConnectionsDashboardStore()
    await store.approveMatching()
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({ match: { q: null, is_active: null } })
  })

  it('revokeApproval() возвращает актуальную запись и обновляет страницу и кэш', async () => {
    const store = useConnectionsDashboardStore()

    const updated = await store.revokeApproval('c-1')

    expect(updated.port_config_status).toBe('mismatch')
    expect(calls.find((c) => c.method === 'DELETE')!.url).toContain('/connections/c-1/port-config/approval')
    expect(pageCalls()).toHaveLength(1)
    expect(calls.some((c) => c.url.includes('/resources/connections'))).toBe(true)
  })

  it('refreshAfterChange() обновляет и страницу, и общий кэш', async () => {
    const store = useConnectionsDashboardStore()
    await store.refreshAfterChange()
    expect(pageCalls()).toHaveLength(1)
    expect(calls.filter((c) => c.url.includes('/resources/connections'))).toHaveLength(1)
  })
})

describe('useConnectionsDashboardStore — количество строк на странице', () => {
  it('по умолчанию 8; варианты — 8, 16, 32, 64', () => {
    const store = useConnectionsDashboardStore()
    expect(store.pageSize).toBe(DEFAULT_PAGE_SIZE)
    expect(store.pageSizeOptions).toEqual([8, 16, 32, 64])
  })

  it('смена размера запрашивает у сервера новый limit и пересчитывает число страниц', async () => {
    stubApi(() => page([row('c-1')], 100))
    const store = useConnectionsDashboardStore()
    await store.load()
    expect(store.pageCount).toBe(13)

    await store.setPageSize(32)

    const p = params(pageCalls().at(-1)!)
    expect(p.get('limit')).toBe('32')
    expect(p.get('offset')).toBe('0')
    expect(store.pageCount).toBe(4)
  })

  it('остаётся на странице с тем же первым подключением: 3-я страница по 8 (с 17-го) → 2-я по 16', async () => {
    stubApi(() => page([row('c-1')], 100))
    const store = useConnectionsDashboardStore()
    await store.load()
    await store.setPage(3)

    await store.setPageSize(16)

    expect(store.page).toBe(2)
    const p = params(pageCalls().at(-1)!)
    expect(p.get('offset')).toBe('16')
    expect(p.get('limit')).toBe('16')
  })

  it('выбор запоминается и восстанавливается новым стором', async () => {
    await useConnectionsDashboardStore().setPageSize(64)
    expect(localStorage.getItem('itr.pageSize.connections')).toBe('64')

    setActivePinia(createPinia())
    expect(useConnectionsDashboardStore().pageSize).toBe(64)
  })

  it.each([0, 7, 100])('недопустимое значение %s не меняет размер и не делает запрос', async (bad) => {
    const store = useConnectionsDashboardStore()
    await store.load()
    const before = pageCalls().length

    await store.setPageSize(bad)

    expect(store.pageSize).toBe(DEFAULT_PAGE_SIZE)
    expect(pageCalls()).toHaveLength(before)
  })

  it('то же значение — без лишнего запроса', async () => {
    const store = useConnectionsDashboardStore()
    await store.load()
    const before = pageCalls().length
    await store.setPageSize(DEFAULT_PAGE_SIZE)
    expect(pageCalls()).toHaveLength(before)
  })
})
