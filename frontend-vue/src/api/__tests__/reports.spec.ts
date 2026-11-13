import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ApiError, UNAUTHORIZED_EVENT } from '../client'
import { BLOB_URL_REVOKE_DELAY_MS } from '../saveBlob'
import { generateInventoryReport, generateStructuralAppendixReport, generateAuditLogReport, downloadReport } from '../reports'

describe('reports API', () => {
  it('generateInventoryReport добавляет information_system_id в query, а не в тело', async () => {
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ file_name: 'a.xlsx', download_url: '/api/v1/reports/download/a.xlsx' })),
    )
    vi.stubGlobal('fetch', fetchMock)

    await generateInventoryReport('is-1', ['unit-1', 'unit-2'])

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/reports/inventory?information_system_id=is-1')
    expect(JSON.parse(init!.body as string)).toEqual({ structural_unit_ids: ['unit-1', 'unit-2'] })
  })

  it('generateInventoryReport без ИС не добавляет query-параметр, а пустой список единиц -> null', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ file_name: 'a.xlsx', download_url: '/x' })))
    vi.stubGlobal('fetch', fetchMock)

    await generateInventoryReport(null, [])

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/reports/inventory')
    expect(JSON.parse(init!.body as string)).toEqual({ structural_unit_ids: null })
  })

  it('generateStructuralAppendixReport шлёт имя ИС и единицы в теле, пустой список единиц -> null', async () => {
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ file_name: 'a.docx', download_url: '/api/v1/reports/download/a.docx' })),
    )
    vi.stubGlobal('fetch', fetchMock)

    await generateStructuralAppendixReport('ТО', ['unit-1'])
    await generateStructuralAppendixReport('ТО', [])

    const [[url, first], [, second]] = fetchMock.mock.calls
    expect(url).toBe('/api/v1/reports/structural-appendix')
    expect(JSON.parse(first!.body as string)).toEqual({ is_name: 'ТО', structural_unit_ids: ['unit-1'] })
    expect(JSON.parse(second!.body as string)).toEqual({ is_name: 'ТО', structural_unit_ids: null })
  })

  it('generateAuditLogReport собирает date_from/date_to в query', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ file_name: 'a.xlsx', download_url: '/x' })))
    vi.stubGlobal('fetch', fetchMock)

    await generateAuditLogReport('2026-01-01', '2026-01-31')

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/reports/audit-log?date_from=2026-01-01&date_to=2026-01-31')
  })

  describe('downloadReport (фикс п.5: скачивание должно нести токен авторизации)', () => {
    // ИБ-02: blob-ссылка освобождается по таймеру (saveBlob), а реальный таймер на 30 с пережил бы тест.
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    /** Успешный ответ с файлом. */
    function mockBlobResponse() {
      return {
        ok: true,
        status: 200,
        blob: vi.fn(async () => new Blob(['fake-file-content'])),
      } as unknown as Response
    }

    /** Неуспешный ответ — настоящий Response: ошибка разбирается тем же apiErrorFromResponse, что и у request(). */
    function errorResponse(status: number, detail: string, headers: Record<string, string> = {}) {
      return new Response(JSON.stringify({ detail }), { status, headers })
    }

    it('запрашивает файл через fetch с заголовком Authorization — не голым <a href> (без заголовков)', async () => {
      localStorage.setItem('itr:auth-token', 'test-token-123')
      const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => mockBlobResponse())
      vi.stubGlobal('fetch', fetchMock)
      vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:fake'), revokeObjectURL: vi.fn() })
      const clickSpy = vi.fn()
      const originalCreateElement = document.createElement.bind(document)
      vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
        const el = originalCreateElement(tag)
        if (tag === 'a') el.click = clickSpy
        return el
      })

      await downloadReport({ file_name: 'отчёт.xlsx', download_url: '/api/v1/reports/download/отчёт.xlsx' })

      const [url, init] = fetchMock.mock.calls[0]
      expect(url).toBe('/api/v1/reports/download/отчёт.xlsx')
      expect(init!.headers).toEqual({ Authorization: 'Bearer test-token-123' })
      expect(clickSpy).toHaveBeenCalled()
      localStorage.clear()
    })

    it('без токена скачивает без заголовка Authorization (неаутентифицированный режим приложения)', async () => {
      localStorage.clear()
      const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => mockBlobResponse())
      vi.stubGlobal('fetch', fetchMock)
      vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:fake'), revokeObjectURL: vi.fn() })

      await downloadReport({ file_name: 'a.xlsx', download_url: '/api/v1/reports/download/a.xlsx' })

      const [, init] = fetchMock.mock.calls[0]
      expect(init!.headers).toEqual({})
    })

    // ИБ-02: раньше при любой ошибке показывалось «Не удалось скачать файл (403)»; текст сервера пользователь не видел.
    it.each([
      [403, 'Недостаточно прав для скачивания отчёта.'],
      [503, 'Сервер занят формированием отчётов, повторите через 10 с.'],
    ])('ИБ-02: %i — пользователь видит сообщение сервера из {detail}, а не общий текст со статусом', async (status, detail) => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_url: string, _init?: RequestInit) => errorResponse(status, detail)),
      )

      const error = (await downloadReport({ file_name: 'a.xlsx', download_url: '/api/v1/reports/download/a.xlsx' }).catch((e: unknown) => e)) as ApiError

      expect(error).toBeInstanceOf(ApiError)
      expect(error.status).toBe(status)
      expect(error.message).toBe(detail)
      expect(error.message).not.toContain('Не удалось скачать файл')
    })

    it('ИБ-02: 401 (просроченная сессия) — сообщение сервера и UNAUTHORIZED_EVENT, как у любого запроса к API', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_url: string, _init?: RequestInit) => errorResponse(401, 'Требуется аутентификация.')),
      )
      const onUnauthorized = vi.fn()
      window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)

      try {
        const error = (await downloadReport({ file_name: 'a.xlsx', download_url: '/api/v1/reports/download/a.xlsx' }).catch((e: unknown) => e)) as ApiError

        expect(error).toBeInstanceOf(ApiError)
        expect(error.status).toBe(401)
        expect(error.message).toBe('Требуется аутентификация.')
        expect(onUnauthorized).toHaveBeenCalledTimes(1)
      } finally {
        window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
      }
    })

    it('ИБ-02: ошибка не 401 событие UNAUTHORIZED_EVENT не отправляет', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_url: string, _init?: RequestInit) => errorResponse(403, 'Недостаточно прав.')),
      )
      const onUnauthorized = vi.fn()
      window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)

      try {
        await downloadReport({ file_name: 'a.xlsx', download_url: '/api/v1/reports/download/a.xlsx' }).catch(() => undefined)

        expect(onUnauthorized).not.toHaveBeenCalled()
      } finally {
        window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
      }
    })

    it('ИБ-02: освобождает object URL по таймеру, а не сразу после клика (иначе часть браузеров обрывает загрузку)', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_url: string, _init?: RequestInit) => mockBlobResponse()),
      )
      const revokeSpy = vi.fn()
      vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:fake'), revokeObjectURL: revokeSpy })

      await downloadReport({ file_name: 'a.xlsx', download_url: '/api/v1/reports/download/a.xlsx' })

      expect(revokeSpy).not.toHaveBeenCalled()
      vi.advanceTimersByTime(BLOB_URL_REVOKE_DELAY_MS)
      expect(revokeSpy).toHaveBeenCalledWith('blob:fake')
    })
  })
})
