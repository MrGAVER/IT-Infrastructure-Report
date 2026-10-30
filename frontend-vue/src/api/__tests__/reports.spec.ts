import { describe, it, expect, vi } from 'vitest'
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
    function mockBlobResponse(status = 200) {
      return {
        ok: status >= 200 && status < 300,
        status,
        blob: vi.fn(async () => new Blob(['fake-file-content'])),
      } as unknown as Response
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

    it('401 (просроченная сессия) выбрасывает понятную ошибку вместо тихого "файл недоступен"', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_url: string, _init?: RequestInit) => mockBlobResponse(401)),
      )

      await expect(downloadReport({ file_name: 'a.xlsx', download_url: '/api/v1/reports/download/a.xlsx' })).rejects.toThrow(/сессия истекла/i)
    })

    it('освобождает object URL после скачивания', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_url: string, _init?: RequestInit) => mockBlobResponse()),
      )
      const revokeSpy = vi.fn()
      vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:fake'), revokeObjectURL: revokeSpy })

      await downloadReport({ file_name: 'a.xlsx', download_url: '/api/v1/reports/download/a.xlsx' })

      expect(revokeSpy).toHaveBeenCalledWith('blob:fake')
    })
  })
})
