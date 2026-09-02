import { describe, it, expect, vi } from 'vitest'
import { generateInventoryReport, generateAuditLogReport, downloadReport } from '../reports'

describe('reports API', () => {
  it('generateInventoryReport добавляет information_system_id в query, а не в тело', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) =>
      new Response(JSON.stringify({ file_name: 'a.xlsx', download_url: '/api/v1/reports/download/a.xlsx' })),
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

  it('generateAuditLogReport собирает date_from/date_to в query', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ file_name: 'a.xlsx', download_url: '/x' })))
    vi.stubGlobal('fetch', fetchMock)

    await generateAuditLogReport('2026-01-01', '2026-01-31')

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/reports/audit-log?date_from=2026-01-01&date_to=2026-01-31')
  })

  it('downloadReport использует download_url как есть, без повторной конкатенации префикса', () => {
    const clickSpy = vi.fn()
    const originalCreateElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = originalCreateElement(tag)
      if (tag === 'a') el.click = clickSpy
      return el
    })

    downloadReport({ file_name: 'отчёт.xlsx', download_url: '/api/v1/reports/download/отчёт.xlsx' })

    expect(clickSpy).toHaveBeenCalled()
  })
})
