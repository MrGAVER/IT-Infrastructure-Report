import { describe, it, expect, vi } from 'vitest'
import { fetchStaleSubinterfaces, groupStaleByDevice, staleVlanText } from '../staleSubinterfaces'
import type { StaleSubinterface } from '../staleSubinterfaces'

function item(patch: Partial<StaleSubinterface> = {}): StaleSubinterface {
  return {
    subinterface_id: 's-1',
    subinterface_name: 'Gi0/0.30',
    port_id: 'p-1',
    port_name: 'Gi0/0',
    device_id: 'd-1',
    device_name: 'RTR-1',
    vlan_id: 'v-30',
    vlan_number: 30,
    vlan_name: 'Резерв',
    ...patch,
  }
}

describe('fetchStaleSubinterfaces', () => {
  it('читает GET /integrity/stale-subinterfaces и возвращает отчёт как есть', async () => {
    const report = { ok: false, total: 1, subinterfaces: [item()] }
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(report)))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchStaleSubinterfaces()).resolves.toEqual(report)

    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toMatch(/\/integrity\/stale-subinterfaces$/)
  })

  it('ошибку сервера не глотает', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Сбой' }), { status: 500 })))
    await expect(fetchStaleSubinterfaces()).rejects.toThrow()
  })
})

describe('groupStaleByDevice', () => {
  it('группирует по устройству, сохраняя порядок сервера (устройства и строки внутри)', () => {
    const groups = groupStaleByDevice([
      item({ subinterface_id: 'a', device_id: 'd-1', device_name: 'A-FW', subinterface_name: 'eth0.10' }),
      item({ subinterface_id: 'b', device_id: 'd-2', device_name: 'B-RTR', subinterface_name: 'Gi0/0.10' }),
      item({ subinterface_id: 'c', device_id: 'd-2', device_name: 'B-RTR', subinterface_name: 'Gi0/1.20' }),
    ])

    expect(groups.map((g) => [g.device_name, g.items.map((i) => i.subinterface_name)])).toEqual([
      ['A-FW', ['eth0.10']],
      ['B-RTR', ['Gi0/0.10', 'Gi0/1.20']],
    ])
  })

  it('пустой список — пустой результат', () => {
    expect(groupStaleByDevice([])).toEqual([])
  })
})

describe('staleVlanText', () => {
  it('«VLAN 30 — Резерв»; без имени — только номер', () => {
    expect(staleVlanText({ vlan_number: 30, vlan_name: 'Резерв' })).toBe('VLAN 30 — Резерв')
    expect(staleVlanText({ vlan_number: 30, vlan_name: '' })).toBe('VLAN 30')
  })
})
