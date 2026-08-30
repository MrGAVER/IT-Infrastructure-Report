import { describe, it, expect, vi } from 'vitest'
import { computePortVlanOptions, loadAssignedDeviceVlanIds, loadDeviceTypeVlanIds } from '../portVlans'
import type { VLANDefinition } from '../types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function vlan(id: string, vlan_id: number, name: string, domain_name = ''): VLANDefinition {
  return { id, vlan_id, name, description: '', domain_id: domain_name ? 'dom-1' : null, domain_name, devices: [] }
}

describe('computePortVlanOptions', () => {
  const guest = vlan('v-guest', 20, 'Гостевой')
  const mgmt = vlan('v-mgmt', 10, 'Управление')
  const legacy = vlan('v-legacy', 99, 'Устаревший (не в каталоге)')

  it('объединяет каталог типа устройства и уже назначенные, без дублей', () => {
    const options = computePortVlanOptions([guest, mgmt, legacy], new Set(['v-mgmt']), new Set(['v-guest', 'v-mgmt']))
    expect(options.map((v) => v.id)).toEqual(['v-mgmt', 'v-guest']) // v-mgmt в обоих наборах — не задублирован
  })

  it('сортирует результат по номеру VLAN по возрастанию', () => {
    const options = computePortVlanOptions([guest, mgmt], new Set(['v-guest', 'v-mgmt']), new Set())
    expect(options.map((v) => v.vlan_id)).toEqual([10, 20])
  })

  it('id, отсутствующий в общем списке определений VLAN, тихо пропускается (не падает)', () => {
    const options = computePortVlanOptions([guest], new Set(['v-ghost']), new Set(['v-guest']))
    expect(options.map((v) => v.id)).toEqual(['v-guest'])
  })

  it('пустые наборы -> пустой список опций', () => {
    expect(computePortVlanOptions([guest, mgmt], new Set(), new Set())).toEqual([])
  })
})

describe('loadDeviceTypeVlanIds', () => {
  it('пустой device_type_id -> пустой набор без запроса к сети', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    expect(await loadDeviceTypeVlanIds('')).toEqual(new Set())
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('фильтрует /resources/device-type-vlans по device_type_id и возвращает набор vlan_id', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      expect(url).toContain('device_type_id=dt-server')
      return jsonResponse({ items: [{ id: 'l-1', device_type_id: 'dt-server', vlan_id: 'v-mgmt' }], total: 1, offset: 0, limit: 1000 })
    })
    vi.stubGlobal('fetch', fetchMock)
    expect(await loadDeviceTypeVlanIds('dt-server')).toEqual(new Set(['v-mgmt']))
  })
})

describe('loadAssignedDeviceVlanIds', () => {
  it('возвращает набор vlan_id, уже назначенных устройству в /resources/device-vlans', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ items: [{ id: 'dv-1', vlan_id: 'v-guest' }, { id: 'dv-2', vlan_id: 'v-mgmt' }], total: 2, offset: 0, limit: 1000 })),
    )
    expect(await loadAssignedDeviceVlanIds('dev-1')).toEqual(new Set(['v-guest', 'v-mgmt']))
  })
})
