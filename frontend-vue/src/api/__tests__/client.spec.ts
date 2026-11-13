import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  api,
  ApiError,
  ClientErrorCode,
  DEFAULT_REQUEST_TIMEOUT_MS,
  ErrorCode,
  listAllResource,
  notifyUnauthorizedIfNeeded,
  parseRetryAfter,
  request,
  setStoredToken,
  UNAUTHORIZED_EVENT,
} from '../client'

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
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'Текущий пароль указан неверно.' }, 401)),
    )

    await expect(api.put('/auth/me/password', { current_password: 'x', new_password: 'y' })).rejects.toMatchObject({
      status: 401,
      message: 'Текущий пароль указан неверно.',
    })
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('401 на POST /auth/login (неверный пароль при входе) тоже не отправляет событие', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'Неверное имя пользователя или пароль.' }, 401)),
    )

    await expect(api.post('/auth/login', { username: 'a', password: 'b' })).rejects.toMatchObject({ status: 401 })
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it.each(['/auth/me', '/resources/devices', '/devices'])('401 на GET %s (протухший токен) отправляет UNAUTHORIZED_EVENT', async (path) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'Требуется вход.' }, 401)),
    )

    await expect(api.get(path)).rejects.toMatchObject({ status: 401 })
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('другие ошибки (403, 500) событие не отправляют', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'Недостаточно прав' }, 403)),
    )
    await expect(api.get('/resources/devices')).rejects.toMatchObject({ status: 403 })

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'Ошибка' }, 500)),
    )
    await expect(api.get('/resources/devices')).rejects.toMatchObject({ status: 500 })

    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  // ИБ-02: общий помощник для тех, кто делает fetch напрямую (скачивание файлов) и не проходит через request().
  describe('notifyUnauthorizedIfNeeded (ИБ-02)', () => {
    it('401 на обычном пути — отправляет UNAUTHORIZED_EVENT', () => {
      notifyUnauthorizedIfNeeded(401, '/api/v1/reports/download/a.xlsx')

      expect(onUnauthorized).toHaveBeenCalledTimes(1)
    })

    it.each(['/auth/login', '/auth/me/password'])('401 на %s (ошибка в форме, а не конец сессии) — событие не отправляется', (path) => {
      notifyUnauthorizedIfNeeded(401, path)

      expect(onUnauthorized).not.toHaveBeenCalled()
    })

    it.each([200, 403, 404, 500, 503])('статус %i — событие не отправляется', (status) => {
      notifyUnauthorizedIfNeeded(status, '/resources/devices')

      expect(onUnauthorized).not.toHaveBeenCalled()
    })
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
    expect(res.truncated).toBe(false)
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

  it('пустая страница при неполном total прерывает загрузку, не зацикливает её и даёт truncated=true', async () => {
    // сервер утверждает total=5000, но реально отдаёт только 1000 записей
    const fetchMock = stubPagedServer(makeItems(1000), 5000)

    const res = await listAllResource('connections')

    // первая страница + один пакет из 4 страниц (все пусты) — и больше ничего: пакеты не продолжаются после пустой страницы
    expect(fetchMock).toHaveBeenCalledTimes(5)
    expect(res.items).toHaveLength(1000)
    expect(res.truncated).toBe(true)
  })

  it('пустая страница в середине пакета: записи до неё сохраняются, следующие пакеты не запрашиваются', async () => {
    // total=20 000 (20 страниц), но реально есть 2500 записей: страницы 0–2 с данными, 3 и дальше пусты
    const fetchMock = stubPagedServer(makeItems(2500), 20_000)

    const res = await listAllResource<{ id: number }>('connections')

    expect(fetchMock).toHaveBeenCalledTimes(5) // страница 0 + пакет 1–4
    expect(res.items.map((i) => i.id)).toEqual(makeItems(2500).map((i) => i.id))
    expect(res.truncated).toBe(true)
  })

  it('число запросов ограничено предохранителем MAX_PAGES (50), даже если сервер врёт про total', async () => {
    // страницы с разными записями (по offset): одинаковые id на каждой странице были бы повторами, которые B-03 убирает
    const fetchMock = vi.fn(async (url: string) => {
      const offset = Number(new URL(url, 'http://localhost').searchParams.get('offset') ?? 0)
      return jsonResponse({ items: Array.from({ length: 1000 }, (_, i) => ({ id: offset + i })), total: 10_000_000, offset, limit: 1000 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const res = await listAllResource('connections')

    expect(fetchMock).toHaveBeenCalledTimes(50)
    expect(res.items).toHaveLength(50_000)
    expect(res.truncated).toBe(true)
  })

  it('R2-01: total=51 000 — не больше 50 запросов, 50 000 записей и честный признак усечения (total настоящий)', async () => {
    const fetchMock = stubPagedServer(makeItems(51_000))

    const res = await listAllResource<{ id: number }>('interfaces')

    expect(fetchMock).toHaveBeenCalledTimes(50)
    expect(res.items).toHaveLength(50_000)
    expect(res.total).toBe(51_000)
    expect(res.limit).toBe(50_000)
    expect(res.truncated).toBe(true)
  })

  it('R2-01: ровно 50 000 записей — предел достигнут, но ничего не потеряно: truncated=false', async () => {
    const fetchMock = stubPagedServer(makeItems(50_000))

    const res = await listAllResource('interfaces')

    expect(fetchMock).toHaveBeenCalledTimes(50)
    expect(res.items).toHaveLength(50_000)
    expect(res.truncated).toBe(false)
  })

  it('R2-01: страницы читаются пакетами — одновременно не больше 4 запросов, а первая страница идёт одна', async () => {
    let inFlight = 0
    let maxInFlight = 0
    const inFlightAtStart: number[] = []
    const all = makeItems(10_000)
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        inFlight++
        maxInFlight = Math.max(maxInFlight, inFlight)
        inFlightAtStart.push(inFlight)
        await new Promise((resolve) => setTimeout(resolve, 1)) // даём запросам пакета накопиться
        inFlight--
        const qs = new URL(url, 'http://localhost').searchParams
        const offset = Number(qs.get('offset'))
        return jsonResponse({ items: all.slice(offset, offset + 1000), total: all.length, offset, limit: 1000 })
      }),
    )

    const res = await listAllResource('connections')

    expect(res.items).toHaveLength(10_000)
    expect(inFlightAtStart[0]).toBe(1) // первая страница одна: из неё известен total
    expect(maxInFlight).toBe(4)
  })

  it('R2-01: порядок записей — по offset, даже если страницы пакета приходят в обратном порядке', async () => {
    const all = makeItems(4500)
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const qs = new URL(url, 'http://localhost').searchParams
        const offset = Number(qs.get('offset'))
        // чем дальше страница, тем быстрее ответ: страница 4 приходит раньше страницы 1
        await new Promise((resolve) => setTimeout(resolve, Math.max(1, 12 - (offset / 1000) * 3)))
        return jsonResponse({ items: all.slice(offset, offset + 1000), total: all.length, offset, limit: 1000 })
      }),
    )

    const res = await listAllResource<{ id: number }>('connections')

    expect(res.items.map((i) => i.id)).toEqual(all.map((i) => i.id))
    expect(res.truncated).toBe(false)
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

  /** Сервер, у которого набор данных меняется между запросами страниц: `pages[n]` — что отдаётся на n-й странице. */
  function stubShiftingServer(pages: Array<Array<{ id: string }>>, total: number) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const offset = Number(new URL(url, 'http://localhost').searchParams.get('offset') ?? 0)
        return jsonResponse({ items: pages[offset / 1000] ?? [], total, offset, limit: 1000 })
      }),
    )
  }

  const idRange = (from: number, to: number) => Array.from({ length: to - from }, (_, i) => ({ id: `r${from + i}` }))

  it('B-03: строка, пришедшая на стыке страниц дважды (запись добавили во время загрузки), остаётся в результате один раз', async () => {
    // вставка в начало сдвинула данные: r999 попала и в конец страницы 0, и в начало страницы 1; r1999 при этом не пришла
    stubShiftingServer([idRange(0, 1000), idRange(999, 1999)], 2000)

    const res = await listAllResource<{ id: string }>('connections')

    const ids = res.items.map((i) => i.id)
    expect(ids.filter((id) => id === 'r999')).toHaveLength(1)
    expect(new Set(ids).size).toBe(ids.length)
    // потеря соседней строки не скрыта: записей меньше total → экран, которому нужна полнота, не примет набор за целый
    expect(res.items).toHaveLength(1999)
    expect(res.limit).toBe(1999)
    expect(res.truncated).toBe(true)
  })

  it('B-03: при повторе первое вхождение (меньший offset) сохраняется, порядок остальных строк не меняется', async () => {
    // PAGE_LIMIT = 1000: чтобы вторая страница вообще запросилась, total должен требовать двух страниц
    stubShiftingServer(
      [
        [...idRange(0, 998), { id: 'dup' }],
        [{ id: 'dup' }, ...idRange(998, 999)],
      ],
      1001,
    )

    const res = await listAllResource<{ id: string }>('connections')

    const ids = res.items.map((i) => i.id)
    expect(ids.indexOf('dup')).toBe(998) // первое вхождение — на странице 0
    expect(ids.filter((id) => id === 'dup')).toHaveLength(1)
    expect(ids.at(-1)).toBe('r998')
  })

  it('B-03: без повторов результат не меняется — truncated=false при полном наборе', async () => {
    stubShiftingServer([idRange(0, 1000), idRange(1000, 1500)], 1500)

    const res = await listAllResource<{ id: string }>('connections')

    expect(res.items).toHaveLength(1500)
    expect(res.truncated).toBe(false)
  })

  it('B-03: строки без id (нестандартный ресурс) не отбрасываются и не считаются повторами друг друга', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ items: [{ name: 'x' }, { name: 'x' }, { id: null, name: 'y' }], total: 3, offset: 0, limit: 1000 })),
    )

    const res = await listAllResource<{ name: string }>('connections')

    expect(res.items).toHaveLength(3)
    expect(res.truncated).toBe(false)
  })

  it('B-03: числовые и строковые id различаются (1 и "1" — разные записи)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ items: [{ id: 1 }, { id: '1' }, { id: 1 }], total: 3, offset: 0, limit: 1000 })),
    )

    const res = await listAllResource<{ id: number | string }>('connections')

    expect(res.items).toEqual([{ id: 1 }, { id: '1' }])
    expect(res.truncated).toBe(true) // 2 записи из заявленных 3: повтор убран, и это честно видно как неполнота
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

  it('запрос с телом отправляет Content-Type: application/json, и Bearer-токен', async () => {
    setStoredToken('tok-1')
    const fetchMock = stubOk()

    await api.post('/resources/devices', { name: 'sw-01' })

    expect(sent(fetchMock).get('Content-Type')).toBe('application/json')
    expect(sent(fetchMock).get('Authorization')).toBe('Bearer tok-1')
  })

  it('R2-04: запрос без тела (GET, DELETE) не отправляет Content-Type, но Bearer-токен отправляет', async () => {
    setStoredToken('tok-1')
    for (const call of [() => api.get('/resources/devices'), () => api.delete('/resources/devices/d1')]) {
      const fetchMock = stubOk()

      await call()

      expect(sent(fetchMock).has('Content-Type')).toBe(false)
      expect(sent(fetchMock).get('Authorization')).toBe('Bearer tok-1')
    }
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
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 204 })),
    )
    await expect(api.delete('/resources/devices/d1')).resolves.toBeNull()
  })

  it('ошибка с detail-объектом: message и code берутся из detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: { message: 'Позиция занята', code: 'RACK_POSITION_OCCUPIED' } }, 409)),
    )

    const error = await api.post('/resources/devices', {}).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 409, message: 'Позиция занята', code: 'RACK_POSITION_OCCUPIED' })
  })

  it('R2-04: 502 от прокси с HTML-страницей: сообщение — «502 Bad Gateway», а разметка не показывается и лежит только в ApiError.body', async () => {
    const page = '<html><head><title>502</title></head><body><h1>Bad Gateway</h1><p>nginx</p></body></html>'
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(page, { status: 502, statusText: 'Bad Gateway' })),
    )

    const error = (await api.get('/devices').catch((e: unknown) => e)) as ApiError

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 502, message: '502 Bad Gateway', code: null, body: page })
    expect(error.message).not.toContain('<')
  })

  it('R2-04: у HTTP/2 statusText пуст — сообщение «502»; пустое тело ошибки не даёт пустого сообщения', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('', { status: 502 })),
    )

    await expect(api.get('/devices')).rejects.toMatchObject({ status: 502, message: '502', code: null, body: null })
  })

  it('R2-04: тело не-JSON хранится в ApiError.body не длиннее предела', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('x'.repeat(10_000), { status: 504, statusText: 'Gateway Timeout' })),
    )

    const error = (await api.get('/devices').catch((e: unknown) => e)) as ApiError

    expect(error.message).toBe('504 Gateway Timeout')
    expect(error.body).toHaveLength(4096)
  })

  it('R2-04: JSON без читаемого detail (ошибки валидации FastAPI) по-прежнему показывается текстом целиком — видно, какое поле не прошло', async () => {
    const validation = [{ loc: ['body', 'name'], msg: 'Field required', type: 'missing' }]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: validation }, 422)),
    )

    const error = (await api.post('/resources/devices', {}).catch((e: unknown) => e)) as ApiError

    expect(error.status).toBe(422)
    expect(error.message).toBe(JSON.stringify({ detail: validation }))
    expect(error.code).toBeNull()
  })

  it('R2-04: 200 с пустым телом возвращает null (как 204), а не SyntaxError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('', { status: 200 })),
    )

    await expect(api.get('/devices')).resolves.toBeNull()
  })

  it('R2-04: 200 с JSON разбирается как раньше, а повреждённый (обрезанный) JSON не маскируется под null', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ items: [1, 2], total: 2 })),
    )
    await expect(api.get('/devices')).resolves.toEqual({ items: [1, 2], total: 2 })

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{"items": [1,', { status: 200 })),
    )
    // B-01: раньше здесь был «голый» SyntaxError; теперь — ApiError, который распознают проверки instanceof ApiError / code.
    await expect(api.get('/devices')).rejects.toMatchObject({ code: ClientErrorCode.INVALID_RESPONSE })
  })

  it('B-01: 200 с HTML вместо JSON (прокси, captive portal, SPA-фолбэк) — ApiError INVALID_RESPONSE с понятным сообщением, а не SyntaxError', async () => {
    const page = '<!doctype html><html><head><title>Вход в сеть</title></head><body>Войдите</body></html>'
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(page, { status: 200, headers: { 'Content-Type': 'text/html' } })),
    )

    const error = (await api.get('/devices').catch((e: unknown) => e)) as ApiError

    expect(error).toBeInstanceOf(ApiError)
    expect(error).not.toBeInstanceOf(SyntaxError)
    expect(error).toMatchObject({ status: 200, code: ClientErrorCode.INVALID_RESPONSE, retryAfter: null, body: page })
    expect(error.message).toBe('Сервер вернул ответ в неожиданном формате. Проверьте адрес сервера и настройки прокси.')
    // техническая фраза JSON.parse и разметка пользователю не показываются
    expect(error.message).not.toMatch(/JSON|Unexpected token|</)
  })

  it('B-01: тело неожиданного ответа хранится в ApiError.body не длиннее предела; код INVALID_RESPONSE отличается от REQUEST_TIMEOUT', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('<'.repeat(10_000), { status: 200 })),
    )

    const error = (await api.get('/devices').catch((e: unknown) => e)) as ApiError

    expect(error.body).toHaveLength(4096)
    expect(ClientErrorCode.INVALID_RESPONSE).not.toBe(ClientErrorCode.REQUEST_TIMEOUT)
  })

  it('B-01: не-JSON при 200 не отправляет UNAUTHORIZED_EVENT и не превращается в таймаут', async () => {
    const onUnauthorized = vi.fn()
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    try {
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => new Response('<html></html>', { status: 200 })),
      )
      await expect(api.get('/devices')).rejects.toMatchObject({ code: ClientErrorCode.INVALID_RESPONSE })
      expect(onUnauthorized).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    }
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
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: FetchInit) => {
        seenSignal = init?.signal
        return jsonResponse({ ok: true })
      }),
    )

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
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: FetchInit) => {
        seen.push(init?.signal)
        if (seen.length === 1) {
          controller.abort() // отмена между страницами
          return jsonResponse({ items: [{ id: 'a' }], total: 2500, offset: 0, limit: 1000 })
        }
        throw init?.signal?.reason
      }),
    )

    const error = await listAllResource('connections', {}, { signal: controller.signal }).catch((e: unknown) => e)

    expect((error as DOMException).name).toBe('AbortError')
    expect(seen.every((signal) => signal !== undefined)).toBe(true)
  })

  it('R2-01: отмена во время пакета прерывает все его запросы и не начинает следующие пакеты', async () => {
    const controller = new AbortController()
    const seen: AbortSignal[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: FetchInit) => {
        const signal = init!.signal as AbortSignal
        seen.push(signal)
        if (seen.length === 1) return Promise.resolve(jsonResponse({ items: [{ id: 'a' }], total: 20_000, offset: 0, limit: 1000 }))
        // запросы пакета «висят», пока их не отменят
        return new Promise<Response>((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(signal.reason), { once: true })
          if (seen.length === 5) controller.abort() // последний запрос пакета ушёл — отменяем всё
        })
      }),
    )

    const error = await listAllResource('connections', {}, { signal: controller.signal }).catch((e: unknown) => e)

    expect((error as DOMException).name).toBe('AbortError')
    expect(seen).toHaveLength(5) // страница 0 + один пакет из 4; следующих пакетов нет
    expect(seen.every((signal) => signal.aborted || signal === seen[0])).toBe(true) // висящих запросов не осталось
  })
})

describe('api/client: Retry-After и новые коды ошибок (B-12)', () => {
  beforeEach(() => localStorage.clear())

  it('429 TOO_MANY_ATTEMPTS: ApiError хранит code и retryAfter из заголовка Retry-After', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: { code: 'TOO_MANY_ATTEMPTS', message: 'Слишком много неудачных попыток входа. Повторите через 7 с.' } }), {
            status: 429,
            headers: { 'Retry-After': '7' },
          }),
      ),
    )

    const error = await api.post('/auth/login', { username: 'a', password: 'b' }).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 429, code: ErrorCode.TOO_MANY_ATTEMPTS, retryAfter: 7 })
  })

  it('без заголовка Retry-After retryAfter = null; у обычных ошибок он тоже null', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'Нет доступа' }, 403)),
    )
    await expect(api.get('/devices')).rejects.toMatchObject({ status: 403, retryAfter: null })
  })

  it.each<[string | null | undefined, number | null]>([
    ['7', 7],
    ['0', 0],
    [' 15 ', 15],
    ['', null],
    [null, null],
    [undefined, null],
    ['-5', null],
    ['1.5', null],
    ['скоро', null],
    ['99999999999999999999999', null], // не безопасное целое
  ])('parseRetryAfter(%j) → %j', (value, expected) => {
    expect(parseRetryAfter(value)).toBe(expected)
  })

  it('parseRetryAfter понимает HTTP-дату: секунды до неё, округление вверх; дата в прошлом даёт 0', () => {
    const now = Date.UTC(2026, 9, 25, 12, 0, 0)
    expect(parseRetryAfter('Sun, 25 Oct 2026 12:00:30 GMT', now)).toBe(30)
    expect(parseRetryAfter('Sun, 25 Oct 2026 12:00:30 GMT', now - 500)).toBe(31)
    expect(parseRetryAfter('Sun, 25 Oct 2026 11:59:00 GMT', now)).toBe(0)
  })

  it('413 REQUEST_BODY_TOO_LARGE (F-06): ApiError несёт код и русское сообщение сервера с названием предела', async () => {
    const message = 'Запрос слишком большой: тело превышает допустимые 2 МБ. Уменьшите объём отправляемых данных.'
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: { code: ErrorCode.REQUEST_BODY_TOO_LARGE, message } }, 413)),
    )
    const error = await api.post('/diagrams', { name: 'x' }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(413)
    expect((error as ApiError).code).toBe('REQUEST_BODY_TOO_LARGE')
    expect((error as ApiError).message).toBe(message)
  })

  it('ErrorCode содержит четыре кода, которых раньше не было', () => {
    expect(ErrorCode).toMatchObject({
      SETUP_ACCESS_DENIED: 'SETUP_ACCESS_DENIED',
      CLIENT_NOT_ALLOWED: 'CLIENT_NOT_ALLOWED',
      TOO_MANY_ATTEMPTS: 'TOO_MANY_ATTEMPTS',
      INTEGRITY_ERROR: 'INTEGRITY_ERROR',
    })
  })

  // Контрактный тест: список кодов фронтенда обязан совпадать с backend/app/constants.py:ErrorCode — иначе новый код
  // сервера молча остаётся без обработки (причина B-12). Репозиторий целиком есть в CI; если фронтенд собирают
  // отдельно от бэкенда, файла нет, и проверка пропускается.
  const backendConstants = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../backend/app/constants.py')
  it.skipIf(!existsSync(backendConstants))('набор ErrorCode совпадает с backend/app/constants.py', () => {
    const source = readFileSync(backendConstants, 'utf-8')
    const block = source.split('class ErrorCode:')[1].split(/\nclass /)[0]
    const backendCodes = [...block.matchAll(/^\s+([A-Z_]+) = "([A-Z_]+)"/gm)].map((m) => {
      expect(m[1]).toBe(m[2]) // имя константы и значение совпадают
      return m[2]
    })
    expect(backendCodes.length).toBeGreaterThanOrEqual(12)
    expect(Object.keys(ErrorCode).sort()).toEqual([...backendCodes].sort())
  })
})
