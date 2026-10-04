import { describe, it, expect, vi } from 'vitest'
import { syncDeviceDeployedSoftware } from '../deviceDeployedSoftware'
import type { SoftwareAssetDraftRow } from '../types'

function stubFetch(responseBody: unknown = { items: [] }, status = 200) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(responseBody), { status }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const sentBody = (fetchMock: ReturnType<typeof stubFetch>) => JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)

describe('syncDeviceDeployedSoftware', () => {
  it('отправляет один PUT со всем списком ПО устройства, сохраняя id существующих строк', async () => {
    const fetchMock = stubFetch({ items: [{ id: 'sw-1' }, { id: 'sw-new' }] })
    const rows: SoftwareAssetDraftRow[] = [
      { id: 'sw-1', software_asset_id: 'asset-ad', version: '2022' },
      { software_asset_id: 'asset-nginx', version: '' },
    ]

    const saved = await syncDeviceDeployedSoftware('dev-1', rows)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/devices/dev-1/deployed-software')
    expect(init.method).toBe('PUT')
    expect(sentBody(fetchMock)).toEqual({
      deployed_software: [
        { id: 'sw-1', software_asset_id: 'asset-ad', version: '2022' },
        { software_asset_id: 'asset-nginx', version: null },
      ],
    })
    expect(saved).toEqual([{ id: 'sw-1' }, { id: 'sw-new' }])
  })

  it('не отправляет строки без выбранного актива; пустой список — пустой массив', async () => {
    const fetchMock = stubFetch()

    await syncDeviceDeployedSoftware('dev-1', [{ software_asset_id: '', version: '8.3' }])

    expect(sentBody(fetchMock)).toEqual({ deployed_software: [] })
  })

  it('ошибка сервера пробрасывается вызывающему', async () => {
    stubFetch({ detail: 'Программный актив не найден в справочнике' }, 422)

    await expect(syncDeviceDeployedSoftware('dev-1', [{ software_asset_id: 'нет', version: '' }])).rejects.toThrow()
  })
})
