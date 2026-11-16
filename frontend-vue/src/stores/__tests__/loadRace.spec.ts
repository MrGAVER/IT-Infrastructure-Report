// B-02 (дополнительная оценка из пакета B): «последний запрос побеждает» в сторах diagram и portSyncRules.
// Быстрое переключение схем: ответ на ПЕРВУЮ схему, пришедший после ответа на вторую, показал бы на канвасе не ту схему, которую открыл пользователь.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useDiagramStore } from '../diagram'
import { usePortSyncRulesStore } from '../portSyncRules'

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
