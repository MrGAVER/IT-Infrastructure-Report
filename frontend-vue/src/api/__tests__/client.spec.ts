import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { api, listAllResource, UNAUTHORIZED_EVENT } from '../client'

function jsonResponse(body: unknown, status = 200) {
  return new Response(body === null ? null : JSON.stringify(body), { status })
}

describe('api/client: ответ 401 и событие UNAUTHORIZED_EVENT', () => {
  const onUnauthorized = vi.fn()

  beforeEach(() => {
    localStorage.clear()
    onUnauthorized.mockClear()
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  })

  afterEach(() => {
    window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  })

  it('401 на PUT /auth/me/password (неверный текущий пароль) НЕ завершает сессию, ошибка пробрасывается', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Текущий пароль указан неверно.' }, 401)))

    await expect(api.put('/auth/me/password', { current_password: 'x', new_password: 'y' })).rejects.toMatchObject({
      status: 401,
      message: 'Текущий пароль указан неверно.',
    })
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('401 на POST /auth/login (неверный пароль при входе) тоже не отправляет событие', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Неверное имя пользователя или пароль.' }, 401)))

    await expect(api.post('/auth/login', { username: 'a', password: 'b' })).rejects.toMatchObject({ status: 401 })
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it.each(['/auth/me', '/resources/devices', '/devices'])(
    '401 на GET %s (протухший токен) отправляет UNAUTHORIZED_EVENT',
    async (path) => {
      vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Требуется вход.' }, 401)))

      await expect(api.get(path)).rejects.toMatchObject({ status: 401 })
      expect(onUnauthorized).toHaveBeenCalledTimes(1)
    },
  )

  it('другие ошибки (403, 500) событие не отправляют', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Недостаточно прав' }, 403)))
    await expect(api.get('/resources/devices')).rejects.toMatchObject({ status: 403 })

    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Ошибка' }, 500)))
    await expect(api.get('/resources/devices')).rejects.toMatchObject({ status: 500 })

    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})

describe('api/client: listAllResource — дочитывание страниц до полного total', () => {
  /** Мок сервера: отдаёт срез из `all` по `offset`/`limit` из URL и считает вызовы. */
  function stubPagedServer(all: Array<{ id: number }>, totalOverride?: number) {
    const fetchMock = vi.fn(async (url: string) => {
      const qs = new URL(url, 'http://localhost').searchParams
      const offset = Number(qs.get('offset') ?? 0)
      const limit = Number(qs.get('limit') ?? 100)
      return jsonResponse({
        items: all.slice(offset, offset + limit),
        total: totalOverride ?? all.length,
        offset,
        limit,
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  const offsetsOf = (fetchMock: ReturnType<typeof stubPagedServer>) =>
    fetchMock.mock.calls.map(([url]) => Number(new URL(url, 'http://localhost').searchParams.get('offset')))

  const makeItems = (n: number) => Array.from({ length: n }, (_, i) => ({ id: i }))

  beforeEach(() => localStorage.clear())

  it('total=2500: ровно 3 запроса с offset 0, 1000, 2000, итог — все 2500 записей без дублей', async () => {
    const fetchMock = stubPagedServer(makeItems(2500))

    const res = await listAllResource<{ id: number }>('connections')

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(offsetsOf(fetchMock)).toEqual([0, 1000, 2000])
    expect(res.items).toHaveLength(2500)
    expect(new Set(res.items.map((i) => i.id)).size).toBe(2500)
    expect(res.total).toBe(2500)
  })

  it('total=1000: один запрос; total=0: один запрос и пустой список', async () => {
    const full = stubPagedServer(makeItems(1000))
    expect((await listAllResource('connections')).items).toHaveLength(1000)
    expect(full).toHaveBeenCalledTimes(1)

    const empty = stubPagedServer([])
    const res = await listAllResource('connections')
    expect(res.items).toEqual([])
    expect(empty).toHaveBeenCalledTimes(1)
  })

  it('пустая страница при неполном total прерывает цикл и не зацикливает загрузку', async () => {
    // сервер утверждает total=5000, но реально отдаёт только 1000 записей
    const fetchMock = stubPagedServer(makeItems(1000), 5000)

    const res = await listAllResource('connections')

    expect(fetchMock).toHaveBeenCalledTimes(2) // вторая страница пуста — выход
    expect(res.items).toHaveLength(1000)
  })

  it('число запросов ограничено предохранителем MAX_PAGES (50), даже если сервер врёт про total', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: makeItems(1000), total: 10_000_000, offset: 0, limit: 1000 }))
    vi.stubGlobal('fetch', fetchMock)

    const res = await listAllResource('connections')

    expect(fetchMock).toHaveBeenCalledTimes(50)
    expect(res.items).toHaveLength(50_000)
  })

  it('передаёт фильтры в каждый запрос, limit/offset из params перекрываются', async () => {
    const fetchMock = stubPagedServer(makeItems(1500))

    await listAllResource('interfaces', { physical_device_id: 'dev-1', limit: 5, offset: 77 })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    for (const [url] of fetchMock.mock.calls) {
      const qs = new URL(url, 'http://localhost').searchParams
      expect(qs.get('physical_device_id')).toBe('dev-1')
      expect(qs.get('limit')).toBe('1000')
    }
    expect(offsetsOf(fetchMock)).toEqual([0, 1000])
  })
})
