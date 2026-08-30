import { describe, it, expect, vi } from 'vitest'
import { getReportEntities } from '../reportEntities'

describe('getReportEntities', () => {
  it('запрашивает GET /report-builder/entities и возвращает голый массив', async () => {
    const fixture = [{ key: 'devices', label: 'Физические устройства', fields: [], to_one: [], to_many: [] }]
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify(fixture)))
    vi.stubGlobal('fetch', fetchMock)

    const result = await getReportEntities()

    expect(result).toEqual(fixture)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/report-builder/entities')
  })
})
