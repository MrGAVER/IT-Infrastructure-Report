// A-13: GET /diagrams/{id}/export больше не запоминает формат сам — клиент просит об этом явно (persist_export=true), потому что
// именно скачивание из интерфейса должно обновлять «последний формат экспорта» диаграммы.
// Замечание Исполнителя А ревью merge/review-r1-r2-executors: ошибка экспорта (новый 503 от A-06 и прежние 500) разбирается так же, как
// ошибки `request()`, — пользователь видит текст из `{detail}`, а не сырое тело ответа.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ApiError } from '../client'
import { exportDiagram, filenameFromDisposition } from '../diagrams'

beforeEach(() => {
  vi.unstubAllGlobals()
})

function stubFetchResponse(body: string, init: ResponseInit) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(body, init)),
  )
}

describe('exportDiagram', () => {
  it('просит сервер запомнить выбранный формат (persist_export=true)', async () => {
    const fetchMock = vi.fn(async () => new Response('x', { status: 200, headers: { 'Content-Disposition': 'attachment; filename="d.svg"' } }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await exportDiagram('d-1', 'svg')

    const url = String((fetchMock.mock.calls[0] as unknown[])[0])
    expect(url).toBe('/api/v1/diagrams/d-1/export?format=svg&persist_export=true')
    expect(result.filename).toBe('d.svg')
  })

  it('ошибка сервера: сообщение берётся из detail, а не из сырого JSON-тела', async () => {
    stubFetchResponse(JSON.stringify({ detail: 'Диаграмма не найдена' }), { status: 404 })

    const error = await exportDiagram('d-x', 'svg').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).message).toBe('Диаграмма не найдена')
    expect((error as ApiError).message).not.toContain('{')
    expect((error as ApiError).status).toBe(404)
  })

  it('503 при занятых слотах экспорта (A-06): понятный текст и Retry-After, а не {"detail":…}', async () => {
    // Форма ответа — как у backend/app/api/diagrams.py:_heavy_export_slot: HTTPException(503, "<текст>", headers={"Retry-After": "10"}).
    const detail = 'Сервер занят формированием других тяжёлых экспортов диаграмм, повторите через 10 с.'
    stubFetchResponse(JSON.stringify({ detail }), { status: 503, headers: { 'Retry-After': '10' } })

    const error = (await exportDiagram('d-1', 'vsdx').catch((e: unknown) => e)) as ApiError

    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(503)
    expect(error.message).toBe(detail)
    expect(error.retryAfter).toBe(10)
  })

  it('не-JSON ответ об ошибке (страница прокси): в сообщении строка состояния, а не разметка', async () => {
    stubFetchResponse('<html><body>Bad Gateway</body></html>', { status: 502, statusText: 'Bad Gateway' })

    const error = (await exportDiagram('d-1', 'svg').catch((e: unknown) => e)) as ApiError

    expect(error).toBeInstanceOf(ApiError)
    expect(error.message).toBe('502 Bad Gateway')
    expect(error.body).toContain('<html>')
  })

  // ИБ-01 (ревью merge/review-r3-executors): сервер кладёт настоящее (кириллическое) имя только в filename*, а в ASCII-варианте
  // каждая буква заменена на «_». Раньше клиент брал только ASCII-вариант, и файл скачивался как «__________________.vsdx».
  it('ИБ-01: кириллическое имя диаграммы берётся из filename*, а не из ASCII-запасного варианта', async () => {
    const name = 'Диаграмма_сети_ЦОД.vsdx'
    const header = `attachment; filename="${'_'.repeat(18)}.vsdx"; filename*=UTF-8''${encodeURIComponent(name)}`
    stubFetchResponse('x', { status: 200, headers: { 'Content-Disposition': header } })

    const result = await exportDiagram('d-1', 'vsdx')

    expect(result.filename).toBe(name)
  })

  it('ИБ-01: заголовка Content-Disposition нет — имя по умолчанию «diagram.<формат>»', async () => {
    stubFetchResponse('x', { status: 200 })

    expect((await exportDiagram('d-1', 'svg')).filename).toBe('diagram.svg')
  })
})

describe('filenameFromDisposition (ИБ-01)', () => {
  it('filename* предпочтительнее ASCII-варианта', () => {
    expect(filenameFromDisposition(`attachment; filename="______.svg"; filename*=UTF-8''%D0%94.svg`, 'diagram.svg')).toBe('Д.svg')
  })

  it('только ASCII-вариант — прежнее поведение', () => {
    expect(filenameFromDisposition('attachment; filename="d.svg"', 'diagram.svg')).toBe('d.svg')
  })

  it('битая %-последовательность в filename* — берётся ASCII-вариант, а не исключение', () => {
    expect(filenameFromDisposition(`attachment; filename="fallback.svg"; filename*=UTF-8''%E0%A4%A`, 'diagram.svg')).toBe('fallback.svg')
  })

  it('битая %-последовательность и нет ASCII-варианта — имя по умолчанию', () => {
    expect(filenameFromDisposition(`attachment; filename*=UTF-8''%E0%A4%A`, 'diagram.svg')).toBe('diagram.svg')
  })

  it('разделители пути в filename* (%2F, %5C) заменяются на «_»', () => {
    expect(filenameFromDisposition(`attachment; filename*=UTF-8''%D0%9F%D0%BB%D0%B0%D0%BD%2F%D0%90%5C%D0%91.vsdx`, 'diagram.vsdx')).toBe('План_А_Б.vsdx')
  })

  it('заголовок отсутствует (пустая строка) — имя по умолчанию', () => {
    expect(filenameFromDisposition('', 'diagram.svg')).toBe('diagram.svg')
  })

  it("необязательный язык в filename* (UTF-8'ru'…) допустим; регистр названий параметров не важен", () => {
    expect(filenameFromDisposition(`attachment; FILENAME*=utf-8'ru'%D0%94.svg`, 'diagram.svg')).toBe('Д.svg')
  })

  it('пустое декодированное значение — переход к ASCII-варианту', () => {
    expect(filenameFromDisposition(`attachment; filename="a.svg"; filename*=UTF-8''`, 'diagram.svg')).toBe('a.svg')
  })
})
