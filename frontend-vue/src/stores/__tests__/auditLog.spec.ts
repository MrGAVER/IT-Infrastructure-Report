import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuditLogStore } from '../auditLog'
import { DEFAULT_PAGE_SIZE } from '../../utils/pageSize'
import { auditJournal, auditServer } from './fixtures'
import type { AuditLogPage } from '../../api/types'
import { usePreferencesStore } from '../preferences'
import { reloadPinia } from './preferencesApi'

const PAGE_URL = /\/api\/v1\/audit-log\?/

let urls: string[]
const params = (url: string) => new URL(url, 'http://x').searchParams
const lastParams = () => params(urls.at(-1)!)

/** handler получает URL запроса страницы и возвращает её ответ (по умолчанию — эмулятор сервера). */
function stubApi(handler: (url: string) => AuditLogPage | Promise<AuditLogPage> = auditServer(auditJournal(100))) {
  urls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      // Сохранение размера страницы теперь уходит на сервер (stores/preferences.ts) — это не запросы журнала,
      // которые считают и разбирают тесты ниже, поэтому в `urls` они не попадают.
      if (url.includes('/preferences')) return new Response(JSON.stringify({ global: {}, user: {} }))
      urls.push(url)
      return new Response(JSON.stringify(await handler(url)))
    }),
  )
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  stubApi()
})

describe('useAuditLogStore — серверная страница', () => {
  it('load() запрашивает первую страницу без условий и сохраняет items/total/summary/entityTypes', async () => {
    const store = useAuditLogStore()

    await store.load()

    expect(urls).toHaveLength(1)
    expect(urls[0]).toMatch(PAGE_URL)
    const p = lastParams()
    expect(p.get('offset')).toBe('0')
    expect(p.get('limit')).toBe(String(DEFAULT_PAGE_SIZE))
    expect(['q', 'action', 'entity_type'].some((k) => p.has(k))).toBe(false)
    expect(store.items.map((e) => e.id)).toEqual(Array.from({ length: DEFAULT_PAGE_SIZE }, (_, i) => `a-${i}`)) // новые сверху
    expect(store.total).toBe(100)
    expect(store.summary).toEqual({ total: 100, by_action: { CREATE: 34, UPDATE: 33, DELETE: 33 } })
    expect(store.entityTypes).toEqual(['devices', 'vms'])
    expect(store.loaded).toBe(true)
    expect(store.pageCount).toBe(Math.ceil(100 / DEFAULT_PAGE_SIZE))
  })

  it('поиск и фильтры передаются серверу; пробелы по краям поиска отбрасываются, «все» — параметра нет', async () => {
    const store = useAuditLogStore()
    store.search = '  Запись 7 '
    store.actionFilter = 'UPDATE'
    store.entityTypeFilter = 'devices'

    await store.load()

    const p = lastParams()
    expect(p.get('q')).toBe('Запись 7')
    expect(p.get('action')).toBe('UPDATE')
    expect(p.get('entity_type')).toBe('devices')

    store.actionFilter = 'all'
    store.entityTypeFilter = ''
    store.search = '   '
    await store.load()
    expect(['q', 'action', 'entity_type'].some((k) => lastParams().has(k))).toBe(false)
  })

  it('setPage() запрашивает нужное смещение; страница ограничивается диапазоном 1..pageCount', async () => {
    const store = useAuditLogStore()
    await store.load()

    await store.setPage(3)
    expect(lastParams().get('offset')).toBe(String(2 * DEFAULT_PAGE_SIZE))
    expect(store.items[0].id).toBe(`a-${2 * DEFAULT_PAGE_SIZE}`)

    await store.setPage(999)
    expect(store.page).toBe(store.pageCount)
    await store.setPage(-5)
    expect(store.page).toBe(1)
  })

  it('applyFilters() возвращает на первую страницу', async () => {
    const store = useAuditLogStore()
    await store.load()
    await store.setPage(4)

    const before = urls.length
    store.search = 'Запись 9'
    await store.applyFilters()

    expect(store.page).toBe(1)
    // Ровно один запрос, и сразу с нуля: страница не «доезжает» до первой через откат за конец.
    expect(urls).toHaveLength(before + 1)
    expect(lastParams().get('offset')).toBe('0')
  })

  it('summary и список разделов не зависят от поиска и фильтров; total — зависит', async () => {
    const store = useAuditLogStore()
    store.actionFilter = 'DELETE'
    store.entityTypeFilter = 'vms'

    await store.load()

    expect(store.total).toBeLessThan(100)
    expect(store.items.every((e) => e.action === 'DELETE' && e.entity_type === 'vms')).toBe(true)
    expect(store.summary.total).toBe(100)
    expect(store.entityTypes).toEqual(['devices', 'vms'])
    expect(store.countByAction('CREATE')).toBe(34)
    expect(store.countByAction('SYNC')).toBe(0)
  })

  it('записи старше первой тысячи доступны: журнал в 2500 записей листается до самой старой', async () => {
    stubApi(auditServer(auditJournal(2500)))
    const store = useAuditLogStore()
    await store.load()

    await store.setPage(store.pageCount)

    expect(store.total).toBe(2500)
    expect(store.items.at(-1)!.id).toBe('a-2499')
    expect(store.summary.total).toBe(2500)
  })

  it('страница за концом (журнал сузили) → переход на последнюю существующую', async () => {
    let call = 0
    const server = auditServer(auditJournal(35))
    stubApi((url) => {
      call += 1
      // Первый ответ: на странице 6 пусто, но записей всего 35 (4 страницы по 10 → последняя — 4-я).
      return call === 1 ? { ...server(url), items: [], offset: 50 } : server(url)
    })
    const store = useAuditLogStore()
    store.page = 6

    await store.load()

    expect(store.page).toBe(4)
    expect(store.items.map((e) => e.id)).toEqual(['a-30', 'a-31', 'a-32', 'a-33', 'a-34'])
    expect(urls).toHaveLength(2)
    expect(store.loading).toBe(false)
  })

  it('устаревший ответ не затирает более поздний (пользователь печатает быстрее сервера)', async () => {
    const resolvers: Array<(p: AuditLogPage) => void> = []
    stubApi(() => new Promise<AuditLogPage>((resolve) => resolvers.push(resolve)))
    const server = auditServer(auditJournal(100))
    const store = useAuditLogStore()

    store.search = 'Запись 1'
    const first = store.load()
    store.search = 'Запись 12'
    const second = store.load()

    resolvers[1](server('/audit-log?q=Запись 12&offset=0&limit=10'))
    await second
    resolvers[0](server('/audit-log?q=Запись 1&offset=0&limit=10')) // ответ на первый запрос приходит последним
    await first

    expect(store.items.map((e) => e.id)).toEqual(['a-12'])
    expect(store.total).toBe(1)
    expect(store.loading).toBe(false)
  })

  it('ошибка загрузки попадает в error и не стирает уже показанные строки', async () => {
    const store = useAuditLogStore()
    await store.load()

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: 'Сервер недоступен' }), { status: 500 })),
    )
    await store.load()

    expect(store.error).toBe('Сервер недоступен')
    expect(store.items).toHaveLength(DEFAULT_PAGE_SIZE)
    expect(store.loading).toBe(false)

    stubApi()
    await store.reload()
    expect(store.error).toBeNull()
  })

  it('reload() перечитывает текущую страницу с текущими условиями', async () => {
    const store = useAuditLogStore()
    await store.load()
    await store.setPage(2)
    store.actionFilter = 'CREATE'

    await store.reload()

    expect(lastParams().get('offset')).toBe(String(DEFAULT_PAGE_SIZE))
    expect(lastParams().get('action')).toBe('CREATE')
  })
})

describe('useAuditLogStore — размер страницы', () => {
  it('по умолчанию 10; варианты — 10, 25, 50, 100', () => {
    const store = useAuditLogStore()
    expect(store.pageSize).toBe(10)
    expect(store.pageSizeOptions).toEqual([10, 25, 50, 100])
  })

  it('смена размера запрашивает страницу с новым limit и остаётся на странице с тем же первым элементом', async () => {
    const store = useAuditLogStore()
    await store.load()
    await store.setPage(6) // строки 51–60

    await store.setPageSize(50)

    expect(lastParams().get('limit')).toBe('50')
    expect(store.page).toBe(2) // 51-я запись теперь первая на странице 2 (51–100)
    expect(lastParams().get('offset')).toBe('50')
    expect(store.items).toHaveLength(50)
    expect(store.pageCount).toBe(2)
  })

  it('выбор запоминается для этого списка и применяется после «перезагрузки»', async () => {
    const store = useAuditLogStore()
    await store.setPageSize(25)
    expect(usePreferencesStore().user.page_sizes).toEqual({ auditLog: 25 })

    reloadPinia() // «перезагрузка»: настройки подтянуты с сервера

    expect(useAuditLogStore().pageSize).toBe(25)
  })

  it('недопустимое значение и то же значение ничего не меняют и не вызывают запрос', async () => {
    const store = useAuditLogStore()
    await store.load()
    await store.setPage(2)
    const before = urls.length

    await store.setPageSize(7)
    await store.setPageSize(12) // и значение прежней шкалы 12/24/48/96 тоже недопустимо
    await store.setPageSize(10)

    expect(store.pageSize).toBe(10)
    expect(store.page).toBe(2)
    expect(urls).toHaveLength(before)
    expect(usePreferencesStore().user.page_sizes).toBeUndefined()
  })

  it('limit не превышает серверный максимум (200) для всех допустимых размеров', () => {
    expect(useAuditLogStore().pageSizeOptions.every((n) => n <= 200)).toBe(true)
  })
})
