import { describe, it, expect, vi } from 'vitest'
import { persistDeviceVlans } from '../deviceVlans'
import type { DeviceVlanDraftRow } from '../types'

function row(overrides: Partial<DeviceVlanDraftRow> = {}): DeviceVlanDraftRow {
  return { vlan_id: 'v-10', ip_address: '', prefix_length: '', is_management: false, description: '', ...overrides }
}

function stubFetch() {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ items: [] }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('persistDeviceVlans', () => {
  it('отправляет ОДИН PUT /devices/{id}/vlans с приведёнными типами (пустое → null, префикс → число)', async () => {
    const fetchMock = stubFetch()

    await persistDeviceVlans('dev-1', [
      row({ id: 'dv-1', ip_address: '10.0.10.1', prefix_length: '24', is_management: true, description: 'mgmt' }),
      row({ vlan_id: 'v-20' }),
    ])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/devices/dev-1/vlans')
    expect(init?.method).toBe('PUT')
    expect(JSON.parse(init!.body as string)).toEqual({
      vlans: [
        { vlan_id: 'v-10', ip_address: '10.0.10.1', prefix_length: 24, is_management: true, description: 'mgmt' },
        { vlan_id: 'v-20', ip_address: null, prefix_length: null, is_management: false, description: null },
      ],
    })
  })

  it('пропускает строки без выбранного VLAN; пустой черновик — PUT с пустым списком (снимает все VLAN устройства)', async () => {
    const fetchMock = stubFetch()

    await persistDeviceVlans('dev-1', [row({ vlan_id: '' })])

    expect(JSON.parse(fetchMock.mock.calls[0][1]!.body as string)).toEqual({ vlans: [] })
  })
})
