// A-13: GET /diagrams/{id}/export больше не запоминает формат сам — клиент просит об этом явно (persist_export=true), потому что
// именно скачивание из интерфейса должно обновлять «последний формат экспорта» диаграммы.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { exportDiagram } from '../diagrams'

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('exportDiagram', () => {
  it('просит сервер запомнить выбранный формат (persist_export=true)', async () => {
    const fetchMock = vi.fn(async () => new Response('x', { status: 200, headers: { 'Content-Disposition': 'attachment; filename="d.svg"' } }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await exportDiagram('d-1', 'svg')

    const url = String((fetchMock.mock.calls[0] as unknown[])[0])
    expect(url).toBe('/api/v1/diagrams/d-1/export?format=svg&persist_export=true')
    expect(result.filename).toBe('d.svg')
  })

  it('ошибка сервера превращается в исключение с текстом ответа', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('нет такой диаграммы', { status: 404 })))

    await expect(exportDiagram('d-x', 'svg')).rejects.toThrow('нет такой диаграммы')
  })
})
