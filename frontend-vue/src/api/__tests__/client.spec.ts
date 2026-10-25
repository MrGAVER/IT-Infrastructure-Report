import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { api, ApiError, ClientErrorCode, DEFAULT_REQUEST_TIMEOUT_MS, listAllResource, request, setStoredToken, UNAUTHORIZED_EVENT } from '../client'

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

type FetchInit = RequestInit & { signal?: AbortSignal }

/** fetch-заглушка, которая не отвечает никогда, но честно реагирует на отмену через signal — как настоящий fetch. */
function stubHangingFetch() {
  const fetchMock = vi.fn((_url: string, init?: FetchInit) => {
    return new Promise<Response>((_resolve, reject) => {
      const signal = init?.signal
      const abort = () => reject(signal?.reason ?? new DOMException('The operation was aborted.', 'AbortError'))
      if (signal?.aborted) abort()
      else signal?.addEventListener('abort', abort, { once: true })
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('api/client: заголовки запроса (B-11)', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  function stubOk() {
    const fetchMock = vi.fn(async (_url: string, _init?: FetchInit) => jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }
  const sent = (fetchMock: ReturnType<typeof stubOk>) => new Headers(fetchMock.mock.calls[0][1]?.headers)

  it('по умолчанию отправляет Content-Type: application/json и Bearer-токен', async () => {
    setStoredToken('tok-1')
    const fetchMock = stubOk()

    await api.get('/resources/devices')

    expect(sent(fetchMock).get('Content-Type')).toBe('application/json')
    expect(sent(fetchMock).get('Authorization')).toBe('Bearer tok-1')
  })

  it('без сохранённого токена заголовка Authorization нет', async () => {
    const fetchMock = stubOk()
    await api.get('/resources/devices')
    expect(sent(fetchMock).has('Authorization')).toBe(false)
  })

  it('заголовки вызывающего кода (init.headers) не затирают Authorization и Content-Type, а добавляются к ним', async () => {
    setStoredToken('tok-1')
    const fetchMock = stubOk()

    await request('/resources/devices', { method: 'POST', body: '{}', headers: { 'X-Trace-Id': 'abc' } })

    expect(sent(fetchMock).get('X-Trace-Id')).toBe('abc')
    expect(sent(fetchMock).get('Authorization')).toBe('Bearer tok-1')
    expect(sent(fetchMock).get('Content-Type')).toBe('application/json')
  })

  it('заголовок, заданный вызывающим кодом явно (Content-Type), имеет приоритет над умолчанием', async () => {
    const fetchMock = stubOk()

    await request('/resources/devices', { method: 'POST', body: 'a,b', headers: new Headers({ 'content-type': 'text/csv' }) })

    expect(sent(fetchMock).get('Content-Type')).toBe('text/csv')
  })

  it('метод, тело и адрес передаются как раньше', async () => {
    const fetchMock = stubOk()

    await api.put('/resources/devices/d1', { name: 'x' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/resources/devices/d1')
    expect(init?.method).toBe('PUT')
    expect(init?.body).toBe(JSON.stringify({ name: 'x' }))
  })
})

describe('api/client: разбор ответа (B-11)', () => {
  beforeEach(() => localStorage.clear())

  it('204 возвращает null', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })))
    await expect(api.delete('/resources/devices/d1')).resolves.toBeNull()
  })

  it('ошибка с detail-объектом: message и code берутся из detail', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: { message: 'Позиция занята', code: 'RACK_POSITION_OCCUPIED' } }, 409)))

    const error = await api.post('/resources/devices', {}).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 409, message: 'Позиция занята', code: 'RACK_POSITION_OCCUPIED' })
  })

  it('ошибка с телом не в JSON: текст ответа становится сообщением, code = null', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('Bad Gateway', { status: 502 })))

    await expect(api.get('/devices')).rejects.toMatchObject({ status: 502, message: 'Bad Gateway', code: null })
  })
})

describe('api/client: таймаут и отмена запросов (B-11)', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('по умолчанию ждёт 30 секунд', () => {
    expect(DEFAULT_REQUEST_TIMEOUT_MS).toBe(30_000)
  })

  it('зависший запрос отклоняется ApiError «Сервер не отвечает» с кодом REQUEST_TIMEOUT ровно через таймаут', async () => {
    stubHangingFetch()
    const result = api.get('/resources/devices').catch((e: unknown) => e)

    await vi.advanceTimersByTimeAsync(DEFAULT_REQUEST_TIMEOUT_MS - 1)
    let settled = false
    void result.then(() => (settled = true))
    await vi.advanceTimersByTimeAsync(0)
    expect(settled).toBe(false) // за миллисекунду до таймаута запрос ещё ждёт

    await vi.advanceTimersByTimeAsync(1)
    const error = await result
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 0, code: ClientErrorCode.REQUEST_TIMEOUT })
    expect((error as ApiError).message).toContain('Сервер не отвечает')
  })

  it('timeoutMs из параметров перекрывает значение по умолчанию', async () => {
    stubHangingFetch()
    const result = api.get('/resources/devices', { timeoutMs: 1_000 }).catch((e: unknown) => e)

    await vi.advanceTimersByTimeAsync(1_000)

    expect(await result).toMatchObject({ code: ClientErrorCode.REQUEST_TIMEOUT })
  })

  it('своевременный ответ таймером не прерывается, а таймер снимается (после ответа отмены нет)', async () => {
    let seenSignal: AbortSignal | undefined
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: FetchInit) => {
      seenSignal = init?.signal
      return jsonResponse({ ok: true })
    }))

    await expect(api.get('/resources/devices')).resolves.toEqual({ ok: true })
    await vi.advanceTimersByTimeAsync(DEFAULT_REQUEST_TIMEOUT_MS * 2)

    expect(seenSignal?.aborted).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('переданный signal отменяет запрос: исходный AbortError, а не «Сервер не отвечает»', async () => {
    stubHangingFetch()
    const controller = new AbortController()
    const result = api.get('/resources/devices', { signal: controller.signal }).catch((e: unknown) => e)

    controller.abort()
    const error = await result

    expect(error).not.toBeInstanceOf(ApiError)
    expect((error as DOMException).name).toBe('AbortError')
    expect(vi.getTimerCount()).toBe(0) // таймер таймаута снят
  })

  it('уже отменённый signal отклоняет запрос сразу', async () => {
    stubHangingFetch()
    const controller = new AbortController()
    controller.abort()

    const error = await api.get('/resources/devices', { signal: controller.signal }).catch((e: unknown) => e)

    expect((error as DOMException).name).toBe('AbortError')
  })

  it('отмена после таймаута ничего не меняет: ошибка остаётся «Сервер не отвечает»', async () => {
    stubHangingFetch()
    const controller = new AbortController()
    const result = api.get('/resources/devices', { signal: controller.signal, timeoutMs: 500 }).catch((e: unknown) => e)

    await vi.advanceTimersByTimeAsync(500)
    controller.abort()

    expect(await result).toMatchObject({ code: ClientErrorCode.REQUEST_TIMEOUT })
  })

  it('signal и timeoutMs доступны во всех методах api.*', async () => {
    for (const call of [
      (o: object) => api.get('/x', o),
      (o: object) => api.post('/x', {}, o),
      (o: object) => api.put('/x', {}, o),
      (o: object) => api.delete('/x', o),
    ]) {
      stubHangingFetch()
      const result = call({ timeoutMs: 100 }).catch((e: unknown) => e)
      await vi.advanceTimersByTimeAsync(100)
      expect(await result).toMatchObject({ code: ClientErrorCode.REQUEST_TIMEOUT })
    }
  })

  it('listAllResource передаёт signal во все запросы страниц и прерывается при отмене', async () => {
    const controller = new AbortController()
    const seen: Array<AbortSignal | undefined> = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: FetchInit) => {
      seen.push(init?.signal)
      if (seen.length === 1) {
        controller.abort() // отмена между страницами
        return jsonResponse({ items: [{ id: 'a' }], total: 2500, offset: 0, limit: 1000 })
      }
      throw init?.signal?.reason
    }))

    const error = await listAllResource('connections', {}, { signal: controller.signal }).catch((e: unknown) => e)

    expect((error as DOMException).name).toBe('AbortError')
    expect(seen.every((signal) => signal !== undefined)).toBe(true)
  })
})

