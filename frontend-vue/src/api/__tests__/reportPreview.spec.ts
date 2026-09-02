import { describe, it, expect, vi } from 'vitest'
import { previewDocxConfig, previewGridConfig } from '../reportPreview'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

describe('previewGridConfig', () => {
  it('отправляет POST с format=xlsx, config и limit по умолчанию 15', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ sections: [] }))
    vi.stubGlobal('fetch', fetchMock)

    const config = { sheets: [{ title: 'Лист 1', columns: [], rows: [] }] }
    await previewGridConfig(config)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/report-builder/preview')
    const body = JSON.parse(init!.body as string)
    expect(body).toEqual({ format: 'xlsx', config, limit: 15 })
  })

  it('принимает произвольный limit', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ sections: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await previewGridConfig({ sheets: [] }, 5)

    const body = JSON.parse(fetchMock.mock.calls[0][1]!.body as string)
    expect(body.limit).toBe(5)
  })
})

describe('previewDocxConfig', () => {
  it('отправляет POST с format=docx, config и limit по умолчанию 20', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ sections: [] }))
    vi.stubGlobal('fetch', fetchMock)

    const config = { blocks: [{ type: 'heading', text: 'x' }] }
    await previewDocxConfig(config)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/report-builder/preview')
    const body = JSON.parse(init!.body as string)
    expect(body).toEqual({ format: 'docx', config, limit: 20 })
  })
})
