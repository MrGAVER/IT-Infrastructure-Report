// A-13: GET /diagrams/{id}/export больше не запоминает формат сам — клиент просит об этом явно (persist_export=true), потому что
// именно скачивание из интерфейса должно обновлять «последний формат экспорта» диаграммы.
// Замечание Исполнителя А ревью merge/review-r1-r2-executors: ошибка экспорта (новый 503 от A-06 и прежние 500) разбирается так же, как
// ошибки `request()`, — пользователь видит текст из `{detail}`, а не сырое тело ответа.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ApiError } from '../client'
import { exportDiagram } from '../diagrams'

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
})
