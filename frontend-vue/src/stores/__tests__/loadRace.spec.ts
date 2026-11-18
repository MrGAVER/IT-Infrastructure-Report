// «Последний запрос побеждает» в сторах diagram и portSyncRules.
// Быстрое переключение схем: ответ на ПЕРВУЮ схему, пришедший после ответа на вторую, показал бы на канвасе
// не ту схему, которую открыл пользователь. То же для действий над схемой (пересборка, переименование, удаление, экспорт):
// ответ сервера на действие над схемой 1 не должен менять схему 2, если её открыли, пока действие было в пути.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useDiagramStore } from '../diagram'
import { usePortSyncRulesStore } from '../portSyncRules'
import { saveBlob } from '../../api/saveBlob'

vi.mock('../../api/saveBlob', () => ({ saveBlob: vi.fn() }))

/** Управляемый fetch: ответ на каждый адрес отдаётся тестом вручную. Запросы к одному адресу нумеруются по порядку вызовов. */
function controlledFetch() {
  const pending = new Map<string, Array<(r: Response) => void>>()
  const fetchMock = vi.fn(
    (url: string) =>
      new Promise<Response>((resolve) => {
        pending.set(url, [...(pending.get(url) ?? []), resolve])
      }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return {
    /** Ждёт, пока сторы отправят n запросов (diagram.load сначала дожидается сохранения раскладки). */
    async sent(n: number) {
      await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(n))
    },
    ok(urlPart: string, body: unknown, generation = 0) {
      const url = [...pending.keys()].find((u) => u.includes(urlPart))
      expect(url, `не было запроса к ${urlPart}`).toBeDefined()
      pending.get(url!)![generation](new Response(JSON.stringify(body)))
    },
    fail(urlPart: string, generation = 0) {
      const url = [...pending.keys()].find((u) => u.includes(urlPart))
      expect(url, `не было запроса к ${urlPart}`).toBeDefined()
      pending.get(url!)![generation](new Response(JSON.stringify({ detail: 'Сервер недоступен' }), { status: 500 }))
    },
  }
}

const diagramBody = (id: string) => ({ id, name: id, nodes: [], edges: [], viewport: { zoom: 1, pan_x: 0, pan_y: 0 } })

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('diagram.load: побеждает последняя запрошенная схема', () => {
  it('ответ на более раннюю схему не подменяет более позднюю', async () => {
    const server = controlledFetch()
    const store = useDiagramStore()

    const first = store.load('схема-1')
    await server.sent(1) // первая схема успела отправить запрос, и только потом пользователь открыл вторую
    const second = store.load('схема-2')
    await server.sent(2)

    server.ok('/diagrams/схема-2', diagramBody('схема-2'))
    await second
    expect(store.diagram?.id).toBe('схема-2')
    expect(store.loading).toBe(false)

    server.ok('/diagrams/схема-1', diagramBody('схема-1')) // ответ на первую схему приходит последним
    await first

    expect(store.diagram?.id).toBe('схема-2')
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('loading не сбрасывается, пока не ответила последняя схема', async () => {
    const server = controlledFetch()
    const store = useDiagramStore()

    const first = store.load('схема-1')
    await server.sent(1) // первая схема успела отправить запрос, и только потом пользователь открыл вторую
    const second = store.load('схема-2')
    await server.sent(2)

    server.ok('/diagrams/схема-1', diagramBody('схема-1'))
    await first
    expect(store.loading).toBe(true)
    expect(store.diagram).toBeNull() // устаревший ответ не применён

    server.ok('/diagrams/схема-2', diagramBody('схема-2'))
    await second
    expect(store.loading).toBe(false)
    expect(store.diagram?.id).toBe('схема-2')
  })

  it('ошибка более ранней схемы не выставляется и не сбрасывает уже загруженную схему', async () => {
    const server = controlledFetch()
    const store = useDiagramStore()

    const first = store.load('схема-1')
    await server.sent(1) // первая схема успела отправить запрос, и только потом пользователь открыл вторую
    const second = store.load('схема-2')
    await server.sent(2)

    server.ok('/diagrams/схема-2', diagramBody('схема-2'))
    await second
    server.fail('/diagrams/схема-1')
    await first

    expect(store.error).toBeNull()
    expect(store.diagram?.id).toBe('схема-2')
    expect(store.loading).toBe(false)
  })

  it('схема, вытесненная до отправки запроса, не делает лишнего запроса и не оставляет loading включённым', async () => {
    const server = controlledFetch()
    const store = useDiagramStore()

    const first = store.load('схема-1')
    const second = store.load('схема-2') // открыта сразу же: первая ещё ждёт сохранения раскладки
    await server.sent(1)
    server.ok('/diagrams/схема-2', diagramBody('схема-2'))
    await Promise.all([first, second])

    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1)
    expect(store.diagram?.id).toBe('схема-2')
    expect(store.loading).toBe(false)
  })

  it('ошибка последней схемы по-прежнему показывается и очищает схему', async () => {
    const server = controlledFetch()
    const store = useDiagramStore()

    const only = store.load('схема-1')
    await server.sent(1)
    server.fail('/diagrams/схема-1')
    await only

    expect(store.error).toBeTruthy()
    expect(store.diagram).toBeNull()
    expect(store.loading).toBe(false)
  })
})

describe('portSyncRules.load: побеждает последний запрос', () => {
  const rulesBody = (id: string) => ({ items: [{ id, priority: 1, enabled: true }], total: 1 })

  it('ответ на более ранний запрос не затирает более поздний', async () => {
    const server = controlledFetch()
    const store = usePortSyncRulesStore()

    const first = store.load()
    const second = store.load()
    await server.sent(2)

    server.ok('/port-sync', rulesBody('новое'), 1)
    await second
    expect(store.rules.map((r) => r.id)).toEqual(['новое'])
    expect(store.loading).toBe(false)

    server.ok('/port-sync', rulesBody('старое'), 0)
    await first

    expect(store.rules.map((r) => r.id)).toEqual(['новое'])
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('loading не сбрасывается, пока не ответил последний запрос, а ошибка раннего не выставляется', async () => {
    const server = controlledFetch()
    const store = usePortSyncRulesStore()

    const first = store.load()
    const second = store.load()
    await server.sent(2)

    server.fail('/port-sync', 0)
    await first
    expect(store.loading).toBe(true)
    expect(store.error).toBeNull()

    server.ok('/port-sync', rulesBody('новое'), 1)
    await second
    expect(store.loading).toBe(false)
    expect(store.rules.map((r) => r.id)).toEqual(['новое'])
  })
})

describe('diagram: ответ на действие над схемой и схема, открытая за время запроса', () => {
  type Store = ReturnType<typeof useDiagramStore>
  type Server = ReturnType<typeof controlledFetch>

  beforeEach(() => vi.mocked(saveBlob).mockClear())

  /** Схема 1 открыта, действие над ней ушло на сервер, пользователь открыл схему 2 — и только потом сервер ответил на действие. */
  async function answeredAfterSwitch(act: (store: Store) => Promise<unknown>, respond: (server: Server) => void) {
    const server = controlledFetch()
    const store = useDiagramStore()
    store.diagram = diagramBody('схема-1') as unknown as Store['diagram']
    const action = act(store)
    await server.sent(1)
    const load = store.load('схема-2')
    await server.sent(2)
    server.ok('/diagrams/схема-2', diagramBody('схема-2'))
    await load
    expect(store.diagram?.id).toBe('схема-2')

    respond(server)
    await action.catch(() => undefined)
    return store
  }

  /** То же действие, но схема не менялась: ответ применяется как обычно. */
  async function answeredOnSameDiagram(act: (store: Store) => Promise<unknown>, respond: (server: Server) => void) {
    const server = controlledFetch()
    const store = useDiagramStore()
    store.diagram = { ...diagramBody('схема-1'), viewport: { zoom: 2, pan_x: 30, pan_y: 40 } } as unknown as Store['diagram']
    const action = act(store)
    await server.sent(1)
    respond(server)
    await action
    return store
  }

  const regenerated = { ...diagramBody('схема-1'), name: 'пересобрана', viewport: { zoom: 1, pan_x: 0, pan_y: 0 } }

  it('regenerate: запоздавший ответ не подменяет открытую схему и не гасит чужой loading', async () => {
    const store = await answeredAfterSwitch(
      (s) => s.regenerate(),
      (server) => server.ok('/diagrams/схема-1/regenerate', regenerated),
    )

    expect(store.diagram?.id).toBe('схема-2')
    expect(store.diagram?.name).toBe('схема-2')
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('regenerate: если схема та же — результат применяется, масштаб и панорама канваса сохраняются', async () => {
    const store = await answeredOnSameDiagram(
      (s) => s.regenerate(),
      (server) => server.ok('/diagrams/схема-1/regenerate', regenerated),
    )

    expect(store.diagram?.name).toBe('пересобрана')
    expect(store.diagram?.viewport).toEqual({ zoom: 2, pan_x: 30, pan_y: 40 })
    expect(store.loading).toBe(false)
  })

  it('rename: имя от схемы 1 не попадает в открытую схему 2', async () => {
    const store = await answeredAfterSwitch(
      (s) => s.rename('новое имя'),
      (server) => server.ok('/diagrams/схема-1/rename', { id: 'схема-1', name: 'новое имя' }),
    )

    expect(store.diagram?.name).toBe('схема-2')
  })

  it('rename: если схема та же — имя меняется', async () => {
    const store = await answeredOnSameDiagram(
      (s) => s.rename('новое имя'),
      (server) => server.ok('/diagrams/схема-1/rename', { id: 'схема-1', name: 'новое имя' }),
    )

    expect(store.diagram?.name).toBe('новое имя')
  })

  it('remove: подтверждённое удаление схемы 1 не закрывает открытую схему 2', async () => {
    const store = await answeredAfterSwitch(
      (s) => s.remove(),
      (server) => server.ok('/diagrams/схема-1', null),
    )

    expect(store.diagram?.id).toBe('схема-2')
  })

  it('remove: если схема та же — она закрывается', async () => {
    const store = await answeredOnSameDiagram(
      (s) => s.remove(),
      (server) => server.ok('/diagrams/схема-1', null),
    )

    expect(store.diagram).toBeNull()
  })

  it('exportAs: файл всё равно скачивается, но «последний формат экспорта» не записывается в открытую схему 2', async () => {
    const store = await answeredAfterSwitch(
      (s) => s.exportAs('svg' as never),
      (server) => server.ok('/diagrams/схема-1/export', {}),
    )

    expect(saveBlob).toHaveBeenCalledTimes(1)
    expect(store.diagram?.id).toBe('схема-2')
    expect(store.diagram?.last_export_format).toBeUndefined()
    expect(store.exporting).toBeNull()
  })

  it('exportAs: если схема та же — формат запоминается', async () => {
    const store = await answeredOnSameDiagram(
      (s) => s.exportAs('svg' as never),
      (server) => server.ok('/diagrams/схема-1/export', {}),
    )

    expect(saveBlob).toHaveBeenCalledTimes(1)
    expect(store.diagram?.last_export_format).toBe('svg')
  })
})
