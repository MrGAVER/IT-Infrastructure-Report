import { describe, it, expect, vi } from 'vitest'
import { loadDeviceInterfaceDraftRows, loadDeviceInterfaceGroups, persistDeviceInterfaces, validateInterfaceDraftRows } from '../deviceInterfaces'
import type { InterfaceDraftRow, InterfaceGroupDraft } from '../types'

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
    open_ports: [],
  }
}

describe('loadDeviceInterfaceDraftRows', () => {
  it('фильтрует IP и VLAN общих списков по interface_id и приводит числа к строкам формы', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes('/resources/interfaces')) {
        return jsonResponse({
          items: [
            { id: 'if-1', physical_device_id: 'dev-1', name: 'eth0', interface_type_id: null, mac_address: null, speed_id: null, is_management: true, is_data_transfer: false, description: null, vlan_mode: 'access' },
          ],
          total: 1,
          offset: 0,
          limit: 1000,
        })
      }
      if (url.includes('/resources/ip-addresses')) {
        // Общий список по ВСЕМ устройствам — включает IP чужого интерфейса (if-2), который
        // не должен попасть в результат для if-1.
        return jsonResponse({
          items: [
            { id: 'ip-1', owner_type: 'device_interface', owner_id: 'if-1', ip_address: '10.0.0.1', prefix_length: 24, purpose: 'Управление', is_management: true },
            { id: 'ip-2', owner_type: 'device_interface', owner_id: 'if-2', ip_address: '10.0.0.2', prefix_length: 24, purpose: '', is_management: false },
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

  // Фикс п.1.4 (батч4): открытые порты интерфейса грузятся тем же приёмом, что IP/VLAN выше —
  // широким запросом по owner_type='device_interface' (без owner_id), с фильтрацией по
  // interface_id на клиенте (см. комментарий к самому запросу в loadDeviceInterfaceDraftRows).
  it('фикс п.1.4: подгружает открытые порты интерфейса, отфильтрованные по owner_id и отсортированные по номеру порта', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes('/resources/interfaces')) {
        return jsonResponse({
          items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0', interface_type_id: null, mac_address: null, speed_id: null, is_management: false, is_data_transfer: false, description: null, vlan_mode: 'trunk' }],
          total: 1,
          offset: 0,
          limit: 1000,
        })
      }
      if (url.includes('/resources/open-ports')) {
        expect(url).toContain('owner_type=device_interface')
        // Порт чужого интерфейса (if-2) не должен попасть в результат для if-1; порядок в
        // ответе намеренно "неправильный" — 443 раньше 22 — чтобы проверить сортировку.
        return jsonResponse({
          items: [
            { id: 'op-2', owner_type: 'device_interface', owner_id: 'if-1', port: 443, protocol: 'HTTPS', transport_protocol: 'TCP', protocol_catalog_id: null, description: null },
            { id: 'op-3', owner_type: 'device_interface', owner_id: 'if-2', port: 22, protocol: 'SSH', transport_protocol: 'TCP', protocol_catalog_id: null, description: null },
            { id: 'op-1', owner_type: 'device_interface', owner_id: 'if-1', port: 22, protocol: 'SSH', transport_protocol: 'TCP', protocol_catalog_id: null, description: null },
          ],
          total: 3,
          offset: 0,
          limit: 1000,
        })
      }
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const [row] = await loadDeviceInterfaceDraftRows('dev-1')
    expect(row.open_ports).toEqual([
      { id: 'op-1', protocol_catalog_id: '', transport_protocol: 'TCP', description: '' },
      { id: 'op-2', protocol_catalog_id: '', transport_protocol: 'TCP', description: '' },
    ])
  })

  it('устройство без интерфейсов — пустой массив, без падения на пустых IP/VLAN', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })))
    const rows = await loadDeviceInterfaceDraftRows('dev-empty')
    expect(rows).toEqual([])
  })

  // Фикс п.1.3.9: vlan_mode на InterfaceDraftRow берётся напрямую с самого интерфейса
  // (DeviceInterface.vlan_mode), а не выводится из InterfaceVLAN.mode связанных записей — раньше
  // при 0 VLAN-связях режим access было неоткуда восстановить, и он молча откатывался в trunk.
  describe('vlan_mode читается с интерфейса напрямую (фикс п.1.3.9)', () => {
    async function loadWithInterfaceVlanMode(vlan_mode: 'access' | 'trunk', links: Array<{ vlan_id: string; mode: string | null }> = []): Promise<InterfaceDraftRow> {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          if (url.includes('/resources/interfaces')) {
            return jsonResponse({
              items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0', interface_type_id: null, mac_address: null, speed_id: null, is_management: false, is_data_transfer: false, description: null, vlan_mode }],
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

    it('access без единого VLAN на порту остаётся access — сам баг 1.3.9', async () => {
      const row = await loadWithInterfaceVlanMode('access', [])
      expect(row.vlan_mode).toBe('access')
      expect(row.vlan_ids).toEqual([])
    })

    it('access с одним VLAN — access', async () => {
      const row = await loadWithInterfaceVlanMode('access', [{ vlan_id: 'v-1', mode: 'access' }])
      expect(row.vlan_mode).toBe('access')
    })

    it('trunk остаётся trunk независимо от количества VLAN-связей', async () => {
      const row = await loadWithInterfaceVlanMode('trunk', [
        { vlan_id: 'v-1', mode: 'trunk' },
        { vlan_id: 'v-2', mode: 'trunk' },
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

  describe('повторяющиеся номера открытых портов на порту', () => {
    const portCatalog = [
      { id: 'c-http', port: 80, protocol_type: 'HTTP', description: null },
      { id: 'c-http-alt', port: 80, protocol_type: 'HTTP-Proxy', description: null },
      { id: 'c-ssh', port: 22, protocol_type: 'SSH', description: null },
    ]
    const withPorts = (name: string, ids: string[]) => ({
      ...emptyRow(),
      name,
      open_ports: ids.map((protocol_catalog_id) => ({ protocol_catalog_id, transport_protocol: 'TCP', description: '' })),
    })

    it('не пропускает повтор номера порта (в т.ч. из разных записей справочника) и называет порт', () => {
      const rows = [withPorts('Gi0/1', ['c-http', 'c-ssh', 'c-http-alt'])]
      expect(validateInterfaceDraftRows(rows, portCatalog)).toBe('На порту «Gi0/1» номера открытых портов повторяются: 80.')
    })

    it('один и тот же номер на РАЗНЫХ портах устройства — не повтор', () => {
      const rows = [withPorts('Gi0/1', ['c-http']), withPorts('Gi0/2', ['c-http'])]
      expect(validateInterfaceDraftRows(rows, portCatalog)).toBeNull()
    })

    it('без справочника портов проверка пропускается (номер не определить), остальные проверки работают', () => {
      const rows = [withPorts('Gi0/1', ['c-http', 'c-http-alt'])]
      expect(validateInterfaceDraftRows(rows)).toBeNull()
      expect(validateInterfaceDraftRows([...rows, emptyRow()])).toBe('У каждого интерфейса должно быть имя.')
    })
  })

  describe('фикс п.2.1.3: IP-адрес и префикс на портах', () => {
    it('пропускает корректный IP и префикс', () => {
      const rows = [{ ...emptyRow(), name: 'eth0', ips: [{ ip_address: '10.0.0.1', prefix_length: '24', purpose: '' }] }]
      expect(validateInterfaceDraftRows(rows)).toBeNull()
    })

    it('не пропускает некорректный IP-адрес', () => {
      const rows = [{ ...emptyRow(), name: 'eth0', ips: [{ ip_address: 'не ip адрес', prefix_length: '', purpose: '' }] }]
      expect(validateInterfaceDraftRows(rows)).toBe('Некорректный IP-адрес «не ip адрес» на порту «eth0».')
    })

    it('не пропускает некорректный префикс', () => {
      const rows = [{ ...emptyRow(), name: 'eth0', ips: [{ ip_address: '10.0.0.1', prefix_length: '999', purpose: '' }] }]
      expect(validateInterfaceDraftRows(rows)).toBe('Некорректный префикс «999» на порту «eth0» — допустимо 0-32.')
    })
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
          open_ports: [],
        },
      ],
    })
    expect(result.items).toEqual([{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0' }])
  })

  // Правка "убрать текстовые поля Порт/Протокол": port/protocol больше не приходят от клиента —
  // единственный вход теперь protocol_catalog_id, сервер сам выводит порт/протокол из него (см.
  // backend/app/services/crud.py:_apply_open_port_catalog). Раньше здесь же жили правила
  // приведения типов/фильтрации пустых строк из DeviceFormModal.vue:persistOpenPorts (удалена).
  it('фикс "убрать текстовые поля Порт/Протокол": пропускает строки без protocol_catalog_id, сохраняет id для обновления существующих', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ items: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await persistDeviceInterfaces('dev-1', [
      {
        ...emptyRow(),
        id: 'if-1',
        name: 'eth0',
        open_ports: [
          { id: 'op-1', protocol_catalog_id: 'cat-1', transport_protocol: 'TCP', description: 'Консоль' },
          { protocol_catalog_id: '', transport_protocol: 'TCP', description: '' }, // без справочника — незаполненная строка-плейсхолдер, отфильтровывается
          { protocol_catalog_id: 'cat-2', transport_protocol: '', description: '' }, // новая строка без id, пустой transport_protocol — по умолчанию TCP
        ],
      },
    ])

    const body = JSON.parse(fetchMock.mock.calls[0][1]!.body as string)
    expect(body.interfaces[0].open_ports).toEqual([
      { id: 'op-1', protocol_catalog_id: 'cat-1', transport_protocol: 'TCP', description: 'Консоль' },
      { id: undefined, protocol_catalog_id: 'cat-2', transport_protocol: 'TCP', description: null },
    ])
  })

  it('отправляет vlan_mode строки как есть (п.1.4.3.2)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [] })))
    await persistDeviceInterfaces('dev-1', [{ ...emptyRow(), id: 'if-1', name: 'eth0', vlan_mode: 'access', vlan_ids: ['v-1'] }])

    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body.interfaces[0].vlan_mode).toBe('access')
  })
})

describe('группы портов', () => {
  function groupDraft(patch: Partial<InterfaceGroupDraft> = {}): InterfaceGroupDraft {
    return { key: 'new-1', name: ' Серверные ', vlan_mode: 'access', vlan_ids: ['v10'], ip_address: ' 10.0.0.5 ', prefix_length: '24', ip_purpose: ' Администрирование ', manage_open_ports: true, open_ports: [{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'админ' }, { protocol_catalog_id: '', transport_protocol: 'TCP', description: '' }], ...patch }
  }

  it('loadDeviceInterfaceGroups: ключ сохранённой группы равен её id, пустые значения превращаются в пустые строки формы', async () => {
    const fetchMock = vi.fn(async (_url: string) =>
      jsonResponse({
        items: [
          { id: 'g-1', physical_device_id: 'dev-1', name: 'Серверные', vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], ip_address: '10.0.0.5', prefix_length: 24, ip_purpose: 'Администрирование', manage_open_ports: true, open_ports: [{ id: 'op-1', protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: null }] },
          { id: 'g-2', physical_device_id: 'dev-1', name: 'Пустая', vlan_mode: null, vlan_ids: [], ip_address: null, prefix_length: null, ip_purpose: null, manage_open_ports: false, open_ports: [] },
        ],
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const groups = await loadDeviceInterfaceGroups('dev-1')

    expect(fetchMock.mock.calls[0][0]).toContain('/devices/dev-1/interface-groups')
    expect(groups[0]).toEqual({ id: 'g-1', key: 'g-1', name: 'Серверные', vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], ip_address: '10.0.0.5', prefix_length: '24', ip_purpose: 'Администрирование', manage_open_ports: true, open_ports: [{ id: 'op-1', protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: '' }] })
    expect(groups[1]).toMatchObject({ vlan_mode: '', ip_address: '', prefix_length: '', ip_purpose: '', manage_open_ports: false })
  })

  it('loadDeviceInterfaceDraftRows: принадлежность порта группе приходит как group_key', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/resources/interfaces')) {
          return jsonResponse({ items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0', interface_type_id: null, mac_address: null, speed_id: null, is_management: false, is_data_transfer: false, description: null, vlan_mode: 'access', group_id: 'g-1' }, { id: 'if-2', physical_device_id: 'dev-1', name: 'eth1', interface_type_id: null, mac_address: null, speed_id: null, is_management: false, is_data_transfer: false, description: null, vlan_mode: 'access', group_id: null }], total: 2, offset: 0, limit: 1000 })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    const rows = await loadDeviceInterfaceDraftRows('dev-1')

    expect(rows.map((r) => r.group_key)).toEqual(['g-1', ''])
  })

  it('persist с группами отправляет полный список groups и group_key каждого порта', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], groups: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await persistDeviceInterfaces('dev-1', [{ ...emptyRow(), name: 'eth0', group_key: 'new-1' }, { ...emptyRow(), name: 'eth1' }], [groupDraft()])

    const body = JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)
    expect(body.groups).toEqual([
      { id: undefined, key: 'new-1', name: 'Серверные', vlan_mode: 'access', vlan_ids: ['v10'], ip_address: '10.0.0.5', prefix_length: 24, ip_purpose: 'Администрирование', manage_open_ports: true, open_ports: [{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'админ' }] },
    ].map((g) => JSON.parse(JSON.stringify(g))))
    expect(body.interfaces.map((i: { group_key: string | null }) => i.group_key)).toEqual(['new-1', null])
  })

  it('persist: параметры, которыми группа не управляет, уходят пустыми (режим не задан — без VLAN, без IP, без открытых портов)', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], groups: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await persistDeviceInterfaces('dev-1', [], [groupDraft({ vlan_mode: '', vlan_ids: ['v10'], ip_address: '', prefix_length: '24', manage_open_ports: false })])

    const body = JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)
    expect(body.groups[0]).toMatchObject({ vlan_mode: null, vlan_ids: [], ip_address: null, prefix_length: null, ip_purpose: null, manage_open_ports: false, open_ports: [] })
  })

  it('persist отправляет назначение общего IP обрезанным, а без IP-адреса группы — не отправляет', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], groups: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await persistDeviceInterfaces('dev-1', [], [groupDraft(), groupDraft({ key: 'new-2', name: 'Без IP', ip_address: '', ip_purpose: 'Администрирование' })])

    const body = JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)
    expect(body.groups[0].ip_purpose).toBe('Администрирование')
    expect(body.groups[1].ip_purpose).toBeNull()
  })

  it('persist без groups (вызывающий код групп не знает) не шлёт ни groups, ни group_key — сервер группы не трогает', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], groups: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await persistDeviceInterfaces('dev-1', [{ ...emptyRow(), name: 'eth0', group_key: 'g-1' }])

    const body = JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)
    expect('groups' in body).toBe(false)
    expect('group_key' in body.interfaces[0]).toBe(false)
  })
})

describe('persistDeviceInterfaces: подключения портов (ключ connection)', () => {
  const peerDraft = { peer_device_id: 'dev-2', peer_interface_id: 'if-peer', connection_type_id: 'ct-1', description: ' патч-корд ' }

  async function sentInterfaces(rows: InterfaceDraftRow[], baseline?: Parameters<typeof persistDeviceInterfaces>[3]) {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ items: [], groups: [] }))
    vi.stubGlobal('fetch', fetchMock)
    await persistDeviceInterfaces('dev-1', rows, undefined, baseline)
    return JSON.parse(fetchMock.mock.calls[0][1]!.body as string).interfaces as Array<Record<string, unknown>>
  }

  it('без снимка подключений (окно «Управлять портами») ключ connection не отправляется вовсе', async () => {
    const sent = await sentInterfaces([{ ...emptyRow(), id: 'if-1', name: 'eth0', connection: peerDraft }])
    expect(sent[0]).not.toHaveProperty('connection')
  })

  it('новый порт с подключением отправляет объект без служебного peer_device_id; порт без подключения — без ключа', async () => {
    const sent = await sentInterfaces([{ ...emptyRow(), name: 'eth0', connection: peerDraft }, { ...emptyRow(), name: 'eth1', connection: null }], new Map())
    expect(sent[0].connection).toEqual({ peer_interface_id: 'if-peer', connection_type_id: 'ct-1', description: 'патч-корд' })
    expect(sent[1]).not.toHaveProperty('connection')
  })

  it('уже сохранённое неизменённое подключение не отправляется, снятое — отправляется как null', async () => {
    const baseline = new Map([
      ['if-1', { ...peerDraft, description: 'патч-корд' }],
      ['if-2', { ...peerDraft, peer_interface_id: 'if-peer-2' }],
    ])
    const sent = await sentInterfaces(
      [
        { ...emptyRow(), id: 'if-1', name: 'eth0', connection: { ...peerDraft } },
        { ...emptyRow(), id: 'if-2', name: 'eth1', connection: null },
      ],
      baseline,
    )
    expect(sent[0]).not.toHaveProperty('connection')
    expect(sent[1].connection).toBeNull()
  })

  it('сосед — другая строка формы: уходит номер её элемента в массиве interfaces (peer_row), а не ключ строки', async () => {
    const toSecond = { ...peerDraft, peer_interface_id: '', peer_row_key: 'k-second' }
    const sent = await sentInterfaces(
      [
        { ...emptyRow(), name: 'eth0', connection: toSecond },
        { ...emptyRow(), name: 'eth1', key: 'k-second' },
      ],
      new Map(),
    )
    expect(sent[0].connection).toEqual({ peer_row: 1, connection_type_id: 'ct-1', description: 'патч-корд' })
    expect(sent[1]).not.toHaveProperty('connection')
    expect(sent[1]).not.toHaveProperty('key') // служебный ключ строки на сервер не уходит
  })
})
