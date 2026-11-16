// B-02 (код-ревью main @ b375f58): два перекрывающихся `reload()` — побеждает ПОСЛЕДНИЙ запущенный, а не последний ответивший.
// Образец — «устаревший ответ не затирает более поздний» в auditLog.spec.ts. Один сценарий прогоняется по всем десяти сторам, у которых
// раньше такой защиты не было (у auditLog и connectionsDashboard она уже была и проверяется их собственными тестами).
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCatalogsStore } from '../catalogs'
import { useConnectionsStore } from '../connections'
import { useContainersStore } from '../containers'
import { useDeviceStacksStore } from '../deviceStacks'
import { useDevicesStore } from '../devices'
import { useInformationSystemsStore } from '../informationSystems'
import { useReportTemplatesStore } from '../reportTemplates'
import { useVLANDomainsStore } from '../vlanDomains'
import { useVLANsStore } from '../vlans'
import { useVMsStore } from '../vms'

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
