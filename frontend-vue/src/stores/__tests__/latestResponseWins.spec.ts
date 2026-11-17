// B-02 (код-ревью main @ b375f58): два перекрывающихся `reload()` — побеждает ПОСЛЕДНИЙ запущенный, а не последний ответивший.
// Образец — «устаревший ответ не затирает более поздний» в auditLog.spec.ts. Один сценарий прогоняется по всем десяти сторам, у которых
// раньше такой защиты не было (у auditLog и connectionsDashboard она уже была и проверяется их собственными тестами).
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuditSettingsStore } from '../auditSettings'
import { useCatalogsStore } from '../catalogs'
import { useConnectionsStore } from '../connections'
import { useContainersStore } from '../containers'
import { useDeviceStacksStore } from '../deviceStacks'
import { useDevicesStore } from '../devices'
import { useInformationSystemsStore } from '../informationSystems'
import { usePortSyncRulesStore } from '../portSyncRules'
import { useReportTemplatesStore } from '../reportTemplates'
import { useVLANDomainsStore } from '../vlanDomains'
import { useVLANsStore } from '../vlans'
import { useVMsStore } from '../vms'
import { BASE_AUDIT_SETTINGS } from './auditSettingsApi'

type Marker = 'старый' | 'новый'

interface Reloadable {
  reload(): Promise<void>
  loading: boolean
  error: string | null
}

interface StoreCase<S extends Reloadable> {
  name: string
  open: () => S
  /** Тело ответа на запрос по адресу `url`; marker — чей это ответ (на первый или на второй reload). */
  body: (marker: Marker, url: string) => unknown
  /** Что стор показывает после загрузки: по этому списку видно, чьи данные в нём остались. */
  read: (store: S) => unknown[]
}

const page = (items: unknown[]) => ({ items, total: items.length, offset: 0, limit: 1000 })

function storeCase<S extends Reloadable>(c: StoreCase<S>): StoreCase<Reloadable> {
  return c as unknown as StoreCase<Reloadable>
}

const CASES: StoreCase<Reloadable>[] = [
  storeCase({
    name: 'catalogs',
    open: () => useCatalogsStore(),
    // 21 справочник + /resources + каталог протоколов: один и тот же reload() делает больше двадцати запросов.
    body: (marker, url) => (/\/resources$/.test(url) ? [] : page([{ id: marker, name: marker }])),
    // До первой загрузки items — пустой объект, а не набор пустых списков.
    read: (store) => ((store as ReturnType<typeof useCatalogsStore>).items.buildings ?? []).map((i) => i.id),
  }),
  storeCase({
    name: 'connections',
    open: () => useConnectionsStore(),
    body: (marker) => page([{ id: marker }]),
    read: (store) => (store as ReturnType<typeof useConnectionsStore>).all.map((i) => i.id),
  }),
  storeCase({
    name: 'containers',
    open: () => useContainersStore(),
    body: (marker) => page([{ id: marker }]),
    read: (store) => (store as ReturnType<typeof useContainersStore>).all.map((i) => i.id),
  }),
  storeCase({
    name: 'deviceStacks',
    open: () => useDeviceStacksStore(),
    body: (marker) => page([{ id: marker }]),
    read: (store) => (store as ReturnType<typeof useDeviceStacksStore>).all.map((i) => i.id),
  }),
  storeCase({
    name: 'devices',
    open: () => useDevicesStore(),
    body: (marker) => page([{ id: marker, system_name: marker }]),
    read: (store) => (store as ReturnType<typeof useDevicesStore>).all.map((i) => i.id),
  }),
  storeCase({
    name: 'informationSystems',
    open: () => useInformationSystemsStore(),
    body: (marker) => [{ id: marker, name: marker }],
    read: (store) => (store as ReturnType<typeof useInformationSystemsStore>).all.map((i) => i.id),
  }),
  storeCase({
    name: 'reportTemplates',
    open: () => useReportTemplatesStore(),
    body: (marker) => [{ id: marker }],
    read: (store) => (store as ReturnType<typeof useReportTemplatesStore>).all.map((i) => i.id),
  }),
  storeCase({
    name: 'vlanDomains',
    open: () => useVLANDomainsStore(),
    body: (marker) => page([{ id: marker }]),
    read: (store) => (store as ReturnType<typeof useVLANDomainsStore>).all.map((i) => i.id),
  }),
  storeCase({
    name: 'vlans',
    open: () => useVLANsStore(),
    body: (marker) => ({ items: [{ vlan_id: marker }] }),
    read: (store) => (store as unknown as { groups: { vlan_id: unknown }[] }).groups.map((g) => g.vlan_id),
  }),
  storeCase({
    name: 'vms',
    open: () => useVMsStore(),
    body: (marker) => page([{ id: marker }]),
    read: (store) => (store as ReturnType<typeof useVMsStore>).all.map((i) => i.id),
  }),
]

/** Управляемый fetch: ответ на каждый запрос отдаётся тестом вручную. Запросы к одному адресу нумеруются по порядку вызовов, поэтому
 * «ответ первого reload()» и «ответ второго» различимы, как бы ни чередовались запросы разных адресов внутри одного reload(). */
function controlledFetch() {
  const pending = new Map<string, Array<(r: Response) => void>>()
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (url: string) =>
        new Promise<Response>((resolve) => {
          pending.set(url, [...(pending.get(url) ?? []), resolve])
        }),
    ),
  )
  const answerAll = (generation: number, make: (url: string) => Response) => {
    for (const [url, resolvers] of pending) resolvers[generation]?.(make(url))
  }
  return {
    ok: (generation: number, marker: Marker, c: StoreCase<Reloadable>) => answerAll(generation, (url) => new Response(JSON.stringify(c.body(marker, url)))),
    fail: (generation: number) => answerAll(generation, () => new Response(JSON.stringify({ detail: 'Сервер недоступен' }), { status: 500 })),
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe.each(CASES)('reload(): побеждает последний запущенный запрос — $name', (c) => {
  it('ответ на более ранний запрос не затирает более поздний (ответы приходят в обратном порядке)', async () => {
    const server = controlledFetch()
    const store = c.open()

    const first = store.reload()
    const second = store.reload()

    server.ok(1, 'новый', c)
    await second
    expect(c.read(store)).toEqual(['новый'])
    expect(store.loading).toBe(false)

    server.ok(0, 'старый', c) // ответ на первый запрос приходит последним
    await first

    expect(c.read(store)).toEqual(['новый'])
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('loading не сбрасывается, пока не ответил последний запрос', async () => {
    const server = controlledFetch()
    const store = c.open()

    const first = store.reload()
    const second = store.reload()

    server.ok(0, 'старый', c) // первый ответил раньше второго
    await first
    expect(store.loading).toBe(true)
    expect(c.read(store)).toEqual([]) // устаревший ответ не применён

    server.ok(1, 'новый', c)
    await second
    expect(store.loading).toBe(false)
    expect(c.read(store)).toEqual(['новый'])
  })

  it('ошибка более раннего запроса не выставляется и не мешает данным последнего', async () => {
    const server = controlledFetch()
    const store = c.open()

    const first = store.reload()
    const second = store.reload()

    server.ok(1, 'новый', c)
    await second
    server.fail(0)
    await first

    expect(store.error).toBeNull()
    expect(c.read(store)).toEqual(['новый'])
    expect(store.loading).toBe(false)
  })

  it('ошибка последнего запроса по-прежнему показывается', async () => {
    const server = controlledFetch()
    const store = c.open()

    const only = store.reload()
    server.fail(0)
    await only

    expect(store.error).toBeTruthy()
    expect(store.loading).toBe(false)
  })
})

// Обратное направление той же гонки: стор сам применяет локально подтверждённое сервером изменение (upsert/remove/move,
// addCatalogItem, save), а load(), начатый ДО изменения, отвечает позже и приносит снимок, где изменения ещё нет.
// Без invalidate() запоздалый ответ молча откатывал бы только что подтверждённое изменение.

interface Loadable {
  loading: boolean
  error: string | null
}

interface LocalChangeCase<S extends Loadable> {
  name: string
  open: () => S
  /** Уже загруженное состояние стора: изменение происходит поверх него. */
  seed: (store: S) => void
  startLoad: (store: S) => Promise<void>
  load: { url: string }
  /** Локальное изменение. Если оно ходит на сервер — вернуть промис, ответ на него задаёт `confirm`. */
  change: (store: S) => Promise<unknown> | void
  confirm?: { method: 'PUT' | 'DELETE'; url: string; body: unknown }
  /** Ответ на запоздалый load: снимок, сделанный до изменения. */
  staleBody: (url: string) => unknown
  /** Ответ на перезапущенный load: то, что на самом деле лежит на сервере после изменения. */
  freshBody: (url: string) => unknown
  read: (store: S) => unknown
  afterChange: unknown
  afterFresh: unknown
}

function localCase<S extends Loadable>(c: LocalChangeCase<S>): LocalChangeCase<Loadable> {
  return c as unknown as LocalChangeCase<Loadable>
}

/** Управляемый fetch с нумерацией запросов отдельно для каждой пары «метод + адрес»: у настроек аудита GET и PUT — один адрес. */
function controlledRequests() {
  const pending = new Map<string, Array<(r: Response) => void>>()
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (url: string, init?: RequestInit) =>
        new Promise<Response>((resolve) => {
          const key = `${init?.method ?? 'GET'} ${url}`
          pending.set(key, [...(pending.get(key) ?? []), resolve])
        }),
    ),
  )
  const matching = (method: string, urlPart: string) => [...pending.keys()].filter((k) => k.startsWith(`${method} `) && k.includes(urlPart))
  return {
    async sent(method: string, urlPart: string, generation = 0) {
      await vi.waitFor(() => expect(matching(method, urlPart).some((k) => pending.get(k)!.length > generation)).toBe(true))
    },
    /** Отвечает на запросы с порядковым номером `generation` по каждому подходящему адресу. */
    answer(method: string, urlPart: string, generation: number, make: (url: string) => unknown) {
      for (const key of matching(method, urlPart)) pending.get(key)![generation]?.(new Response(JSON.stringify(make(key.slice(method.length + 1)))))
    },
  }
}

const ruleBody = (enabled: boolean) => ({ id: 'a', priority: 1, enabled })
const auditBody = (retention: number, lastCleanup: string | null) => ({
  ...BASE_AUDIT_SETTINGS,
  retention_days: retention,
  is_default: retention === BASE_AUDIT_SETTINGS.retention_days,
  last_cleanup_at: lastCleanup,
})

/** Ответ на запрос любого справочника; у каталога протоколов другая форма записи (порт и тип, а не имя). */
function catalogsBody(url: string, ids: string[]) {
  if (/\/resources$/.test(url)) return []
  if (/protocol-port-catalog/.test(url)) return page(ids.map((id, i) => ({ id, port: 80 + i, protocol_type: 'tcp' })))
  return page(ids.map((id) => ({ id, name: id })))
}

const LOCAL_CASES: LocalChangeCase<Loadable>[] = [
  localCase({
    name: 'portSyncRules.update',
    open: () => usePortSyncRulesStore(),
    seed: (store) => {
      store.rules = [ruleBody(true) as never]
      store.loaded = true
    },
    startLoad: (store) => store.load(),
    load: { url: '/port-sync/rules' },
    change: (store) => store.update('a', { enabled: false }),
    confirm: { method: 'PUT', url: '/port-sync/rules/a', body: ruleBody(false) },
    staleBody: () => ({ items: [ruleBody(true)], total: 1 }),
    freshBody: () => ({ items: [ruleBody(false)], total: 1 }),
    read: (store) => store.rules.map((r) => r.enabled),
    afterChange: [false],
    afterFresh: [false],
  }),
  localCase({
    name: 'portSyncRules.remove',
    open: () => usePortSyncRulesStore(),
    seed: (store) => {
      store.rules = [ruleBody(true) as never]
      store.loaded = true
    },
    startLoad: (store) => store.load(),
    load: { url: '/port-sync/rules' },
    change: (store) => store.remove('a'),
    confirm: { method: 'DELETE', url: '/port-sync/rules/a', body: null },
    staleBody: () => ({ items: [ruleBody(true)], total: 1 }),
    freshBody: () => ({ items: [], total: 0 }),
    read: (store) => store.rules.map((r) => r.id),
    afterChange: [],
    afterFresh: [],
  }),
  localCase({
    name: 'catalogs.addCatalogItem',
    open: () => useCatalogsStore(),
    seed: (store) => {
      store.items.buildings = [{ id: 'old', name: 'old' }] as never
      store.loaded = true
    },
    startLoad: (store) => store.reload(),
    load: { url: '' },
    change: (store) => store.addCatalogItem('buildings', { id: 'new', name: 'new' } as never),
    // 21 справочник + /resources + каталог протоколов: один reload() — больше двадцати запросов, ответ задаётся на каждый.
    staleBody: (url) => catalogsBody(url, ['old']),
    freshBody: (url) => catalogsBody(url, ['old', 'new', 'server']),
    read: (store) => ((store as ReturnType<typeof useCatalogsStore>).items.buildings ?? []).map((i) => i.id).sort(),
    afterChange: ['new', 'old'],
    afterFresh: ['new', 'old', 'server'],
  }),
  localCase({
    name: 'auditSettings.save',
    open: () => useAuditSettingsStore(),
    seed: (store) => {
      store.settings = auditBody(0, null)
    },
    startLoad: (store) => store.load(),
    load: { url: '/audit-log/settings' },
    change: (store) => store.save(30),
    confirm: { method: 'PUT', url: '/audit-log/settings', body: { ...auditBody(30, null), removed_now: 5, cleanup_failed: false } },
    staleBody: () => auditBody(0, null),
    freshBody: () => auditBody(30, '2026-11-17T09:00:00'),
    read: (store) => [store.settings?.retention_days, store.settings?.last_cleanup_at],
    afterChange: [30, null],
    afterFresh: [30, '2026-11-17T09:00:00'],
  }),
]

describe.each(LOCAL_CASES)('загрузка в полёте, затем подтверждённое изменение — $name', (c) => {
  /** Доводит сценарий до момента «изменение применено, ответ запоздавшего load ещё не пришёл». */
  async function changeWhileLoading() {
    const server = controlledRequests()
    const store = c.open()
    c.seed(store)

    const load = c.startLoad(store)
    await server.sent('GET', c.load.url)
    const change = c.change(store)
    if (c.confirm) {
      await server.sent(c.confirm.method, c.confirm.url)
      server.answer(c.confirm.method, c.confirm.url, 0, () => c.confirm!.body)
    }
    await change
    return { server, store, load }
  }

  it('запоздалый ответ load не откатывает подтверждённое изменение', async () => {
    const { server, store, load } = await changeWhileLoading()
    expect(c.read(store)).toEqual(c.afterChange)

    server.answer('GET', c.load.url, 0, c.staleBody) // ответ на load, начатый до изменения, приходит после него
    await load

    expect(c.read(store)).toEqual(c.afterChange)
    expect(store.error).toBeNull()
  })

  it('данные не остаются устаревшими: load перезапускается, loading не сбрасывается запоздавшим ответом, итог — ответ перезапуска', async () => {
    const { server, store, load } = await changeWhileLoading()

    server.answer('GET', c.load.url, 0, c.staleBody)
    await load
    expect(store.loading).toBe(true) // идёт перезапущенный load: запоздавший не вправе погасить индикатор

    await server.sent('GET', c.load.url, 1)
    server.answer('GET', c.load.url, 1, c.freshBody)
    await vi.waitFor(() => expect(store.loading).toBe(false))

    expect(c.read(store)).toEqual(c.afterFresh)
    expect(store.error).toBeNull()
  })

  it('без загрузки в полёте изменение не запускает лишних запросов', async () => {
    const server = controlledRequests()
    const store = c.open()
    c.seed(store)

    const change = c.change(store)
    if (c.confirm) {
      await server.sent(c.confirm.method, c.confirm.url)
      server.answer(c.confirm.method, c.confirm.url, 0, () => c.confirm!.body)
    }
    await change

    expect(c.read(store)).toEqual(c.afterChange)
    expect(store.loading).toBe(false)
    expect(vi.mocked(fetch).mock.calls.filter(([, init]) => (init?.method ?? 'GET') === 'GET')).toHaveLength(0)
  })
})
