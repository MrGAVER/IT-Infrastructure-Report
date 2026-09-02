import { describe, it, expect, vi } from 'vitest'
import { loadDeviceInterfaceDraftRows, persistDeviceInterfaces, validateInterfaceDraftRows } from '../deviceInterfaces'
import type { InterfaceDraftRow } from '../types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function emptyRow(): InterfaceDraftRow {
  return {
    name: '',
    interface_type_id: '',
    mac_address: '',
    speed_id: '',
    is_management: false,
    is_data_transfer: false,
    description: '',
    vlan_ids: [],
    vlan_mode: 'trunk',
    ips: [],
  }
}

describe('loadDeviceInterfaceDraftRows', () => {
  it('фильтрует IP и VLAN общих списков по interface_id и приводит числа к строкам формы', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes('/resources/interfaces')) {
        return jsonResponse({
          items: [
            { id: 'if-1', physical_device_id: 'dev-1', name: 'eth0', interface_type_id: null, mac_address: null, speed_id: null, is_management: true, is_data_transfer: false, description: null },
          ],
          total: 1,
          offset: 0,
          limit: 1000,
        })
      }
      if (url.includes('/resources/interface-ips')) {
        // Общий список по ВСЕМ устройствам — включает IP чужого интерфейса (if-2), который
        // не должен попасть в результат для if-1.
        return jsonResponse({
          items: [
            { id: 'ip-1', interface_id: 'if-1', ip_address: '10.0.0.1', prefix_length: 24, purpose: 'Управление', is_management: true },
            { id: 'ip-2', interface_id: 'if-2', ip_address: '10.0.0.2', prefix_length: 24, purpose: '', is_management: false },
          ],
          total: 2,
          offset: 0,
          limit: 1000,
        })
      }
      if (url.includes('/resources/interface-vlans')) {
        return jsonResponse({ items: [{ id: 'iv-1', interface_id: 'if-1', vlan_id: 'vlan-10', mode: 'access' }], total: 1, offset: 0, limit: 1000 })
      }
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const rows = await loadDeviceInterfaceDraftRows('dev-1')

    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ id: 'if-1', name: 'eth0', vlan_ids: ['vlan-10'], vlan_mode: 'access' })
    expect(rows[0].ips).toEqual([{ id: 'ip-1', ip_address: '10.0.0.1', prefix_length: '24', purpose: 'Управление' }])

    // Запрос списка самих интерфейсов должен быть отфильтрован по устройству на бэкенде —
    // тот же принцип экономии трафика, что и в DeviceFormModal.vue.
    const interfacesCall = fetchMock.mock.calls.find(([url]) => (url as string).includes('/resources/interfaces?'))
    expect(interfacesCall?.[0]).toContain('physical_device_id=dev-1')
  })

  it('устройство без интерфейсов — пустой массив, без падения на пустых IP/VLAN', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })))
    const rows = await loadDeviceInterfaceDraftRows('dev-empty')
    expect(rows).toEqual([])
  })

  // п.1.4.3.2: vlan_mode на InterfaceDraftRow выводится из InterfaceVLAN.mode связанных записей.
  describe('вывод vlan_mode (п.1.4.3.2)', () => {
    async function loadWithVlanLinks(links: Array<{ vlan_id: string; mode: string | null }>): Promise<InterfaceDraftRow> {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          if (url.includes('/resources/interfaces')) {
            return jsonResponse({
              items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0', interface_type_id: null, mac_address: null, speed_id: null, is_management: false, is_data_transfer: false, description: null }],
              total: 1,
              offset: 0,
              limit: 1000,
            })
          }
          if (url.includes('/resources/interface-vlans')) {
            return jsonResponse({
              items: links.map((l, i) => ({ id: `iv-${i}`, interface_id: 'if-1', vlan_id: l.vlan_id, mode: l.mode })),
              total: links.length,
              offset: 0,
              limit: 1000,
            })
          }
          return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
        }),
      )
      const [row] = await loadDeviceInterfaceDraftRows('dev-1')
      return row
    }

    it('без единой VLAN-связи — trunk (пустой список — тоже валидный trunk)', async () => {
      const row = await loadWithVlanLinks([])
      expect(row.vlan_mode).toBe('trunk')
    })

    it('mode=null у всех связей (весь исторический массив данных до п.1.4.3.2) — trunk', async () => {
      const row = await loadWithVlanLinks([{ vlan_id: 'v-1', mode: null }])
      expect(row.vlan_mode).toBe('trunk')
    })

    it('mode="access" у единственной связи — access', async () => {
      const row = await loadWithVlanLinks([{ vlan_id: 'v-1', mode: 'access' }])
      expect(row.vlan_mode).toBe('access')
    })

    it('смешанные mode на разных связях одного интерфейса — trunk (не все access)', async () => {
      const row = await loadWithVlanLinks([
        { vlan_id: 'v-1', mode: 'access' },
        { vlan_id: 'v-2', mode: null },
      ])
      expect(row.vlan_mode).toBe('trunk')
    })
  })
})

describe('validateInterfaceDraftRows', () => {
  it('пропускает пустой список и список с именованными интерфейсами', () => {
    expect(validateInterfaceDraftRows([])).toBeNull()
    expect(validateInterfaceDraftRows([{ ...emptyRow(), name: 'eth0' }])).toBeNull()
  })

  it('требует имя у каждого интерфейса', () => {
    expect(validateInterfaceDraftRows([{ ...emptyRow(), name: 'eth0' }, emptyRow()])).toBe('У каждого интерфейса должно быть имя.')
    expect(validateInterfaceDraftRows([{ ...emptyRow(), name: '   ' }])).toBe('У каждого интерфейса должно быть имя.') // пробелы не считаются именем
  })

  it('п.1.4.3.2: не пропускает access-порт с более чем одним VLAN', () => {
    const bad = [{ ...emptyRow(), name: 'eth0', vlan_mode: 'access' as const, vlan_ids: ['v-1', 'v-2'] }]
    expect(validateInterfaceDraftRows(bad)).toBe('В режиме access у порта может быть не более одного VLAN.')

    const ok = [{ ...emptyRow(), name: 'eth0', vlan_mode: 'access' as const, vlan_ids: ['v-1'] }]
    expect(validateInterfaceDraftRows(ok)).toBeNull()
  })
})

describe('persistDeviceInterfaces', () => {
  it('отправляет PUT /devices/{id}/interfaces с приведёнными типами и без пустых IP', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0' }] }))
    vi.stubGlobal('fetch', fetchMock)

    const rows: InterfaceDraftRow[] = [
      {
        ...emptyRow(),
        id: 'if-1',
        name: '  eth0  ',
        vlan_ids: ['vlan-legacy'], // должен уйти как есть — см. комментарий к InterfaceDraftRow
        ips: [
          { ip_address: ' 10.0.0.1 ', prefix_length: '24', purpose: '' },
          { ip_address: '   ', prefix_length: '', purpose: '' }, // пустой IP отфильтровывается
        ],
      },
    ]

    const result = await persistDeviceInterfaces('dev-1', rows)

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/devices/dev-1/interfaces')
    expect(init?.method).toBe('PUT')
    const body = JSON.parse(init!.body as string)
    expect(body).toEqual({
      interfaces: [
        {
          id: 'if-1',
          name: 'eth0',
          interface_type_id: null,
          mac_address: null,
          speed_id: null,
          is_management: false,
          is_data_transfer: false,
          description: null,
          vlan_ids: ['vlan-legacy'],
          vlan_mode: 'trunk',
          ips: [{ id: undefined, ip_address: '10.0.0.1', prefix_length: 24, purpose: null }],
        },
      ],
    })
    expect(result.items).toEqual([{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0' }])
  })

  it('отправляет vlan_mode строки как есть (п.1.4.3.2)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [] })))
    await persistDeviceInterfaces('dev-1', [{ ...emptyRow(), id: 'if-1', name: 'eth0', vlan_mode: 'access', vlan_ids: ['v-1'] }])

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body.interfaces[0].vlan_mode).toBe('access')
  })
})
