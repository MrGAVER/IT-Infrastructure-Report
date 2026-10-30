import { describe, it, expect } from 'vitest'
import type { InterfaceDraftRow, InterfaceGroupDraft, SubinterfaceDraftRow, VLANDefinition } from '../../api/types'
import {
  applyGroupToRow,
  applyGroupsToRows,
  cloneGroupsForCopy,
  copyValuesFromRow,
  copyableFields,
  subinterfaceTemplatesFromRow,
  describeGroup,
  emptyGroup,
  eraseGroupValues,
  managedFields,
  memberIndices,
  setGroupMembers,
  validateInterfaceGroups,
} from '../interfaceGroups'

function row(name: string, patch: Partial<InterfaceDraftRow> = {}): InterfaceDraftRow {
  return {
    name,
    interface_type_id: '',
    mac_address: '',
    speed_id: '',
    is_management: false,
    is_data_transfer: false,
    description: '',
    vlan_ids: [],
    vlan_mode: 'access',
    ips: [],
    open_ports: [],
    ...patch,
  }
}

function group(patch: Partial<InterfaceGroupDraft> = {}): InterfaceGroupDraft {
  return { ...emptyGroup('Серверные'), key: 'g1', ...patch }
}

describe('managedFields', () => {
  it('группа управляет только заданными параметрами', () => {
    expect(managedFields(group())).toEqual({ vlan: false, ip: false, openPorts: false, subinterfaces: false })
    expect(managedFields(group({ vlan_mode: 'trunk', ips: [{ ip_address: ' 10.0.0.5 ', prefix_length: '', purpose: '' }], manage_open_ports: true }))).toEqual({
      vlan: true,
      ip: true,
      openPorts: true,
      subinterfaces: false,
    })
    expect(managedFields(group({ manage_subinterfaces: true }))).toEqual({ vlan: false, ip: false, openPorts: false, subinterfaces: true })
    expect(managedFields(undefined)).toEqual({ vlan: false, ip: false, openPorts: false, subinterfaces: false })
  })
})

describe('applyGroupToRow', () => {
  it('записывает в порт режим, VLAN, общий IP и открытые порты группы', () => {
    const g = group({
      vlan_mode: 'access',
      vlan_ids: ['v10'],
      ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }],
      manage_open_ports: true,
      open_ports: [{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'админ' }],
    })

    const result = applyGroupToRow(row('Gi0/1', { vlan_mode: 'trunk', vlan_ids: ['v20'] }), g)

    expect(result.vlan_mode).toBe('access')
    expect(result.vlan_ids).toEqual(['v10'])
    expect(result.ips).toEqual([{ id: undefined, ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }])
    expect(result.open_ports).toEqual([{ id: undefined, protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'админ' }])
  })

  it('не трогает параметры, которыми группа не управляет', () => {
    const own = row('Gi0/1', { vlan_mode: 'trunk', vlan_ids: ['v20'], ips: [{ ip_address: '192.168.1.9', prefix_length: '24', purpose: '' }] })
    expect(applyGroupToRow(own, group({ manage_open_ports: false }))).toEqual(own)
  })

  it('сохраняет id существующих IP и открытых портов, чтобы сервер обновил их на месте', () => {
    const existing = row('Gi0/1', {
      ips: [
        { id: 'ip-1', ip_address: '1.1.1.1', prefix_length: '8', purpose: 'Управление' },
        { id: 'ip-2', ip_address: '2.2.2.2', prefix_length: '8', purpose: '' },
      ],
      open_ports: [{ id: 'op-1', protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'старое' }],
    })
    const g = group({
      ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'Администрирование' }],
      manage_open_ports: true,
      open_ports: [{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'новое' }],
    })

    const result = applyGroupToRow(existing, g)

    // id первой строки IP сохраняется (сервер обновит её на месте); адрес, префикс и назначение — группы
    expect(result.ips).toEqual([{ id: 'ip-1', ip_address: '10.0.0.5', prefix_length: '24', purpose: 'Администрирование' }])
    expect(result.open_ports).toEqual([{ id: 'op-1', protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'новое' }])
  })

  it('пропускает пустые строки справочника и дубли порта с тем же транспортом; управление открытыми портами с пустым списком стирает их', () => {
    const g = group({
      manage_open_ports: true,
      open_ports: [
        { protocol_catalog_id: '', transport_protocol: 'TCP', description: '' },
        { protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'a' },
        { protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'b' },
      ],
    })
    expect(applyGroupToRow(row('p'), g).open_ports).toHaveLength(1)
    expect(
      applyGroupToRow(
        row('p', { open_ports: [{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: '' }] }),
        group({ manage_open_ports: true }),
      ).open_ports,
    ).toEqual([])
  })
})

describe('applyGroupsToRows / setGroupMembers / memberIndices', () => {
  it('применяет группу только к её портам; порт переходит между группами, исключённый остаётся без группы', () => {
    const g1 = group({ key: 'g1', ips: [{ ip_address: '10.0.0.1', prefix_length: '', purpose: '' }] })
    const g2 = group({ key: 'g2', name: 'Вторая', ips: [{ ip_address: '10.0.0.2', prefix_length: '', purpose: '' }] })
    let rows = [row('a', { group_key: 'g1' }), row('b'), row('c', { group_key: 'g2' })]

    rows = setGroupMembers(rows, 'g1', new Set([0, 2]))
    expect(memberIndices(rows, 'g1')).toEqual([0, 2])
    expect(memberIndices(rows, 'g2')).toEqual([])

    rows = setGroupMembers(rows, 'g1', new Set([1]))
    expect(rows.map((r) => r.group_key)).toEqual(['', 'g1', ''])

    const applied = applyGroupsToRows(rows, [g1, g2])
    expect(applied[1].ips[0].ip_address).toBe('10.0.0.1')
    expect(applied[0].ips).toEqual([])
  })

  it('порт с неизвестным ключом группы не меняется', () => {
    const r = row('a', { group_key: 'нет-такой' })
    expect(applyGroupsToRows([r], [group()])[0]).toBe(r)
  })
})

describe('eraseGroupValues', () => {
  it('стирает только управляемые группой параметры; режим порта возвращается к access', () => {
    const full = row('a', {
      vlan_mode: 'trunk',
      vlan_ids: ['v1'],
      ips: [{ ip_address: '1.1.1.1', prefix_length: '24', purpose: '' }],
      open_ports: [{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: '' }],
    })

    const onlyIp = eraseGroupValues(full, group({ ips: [{ ip_address: '1.1.1.1', prefix_length: '', purpose: '' }] }))
    expect(onlyIp.ips).toEqual([])
    expect(onlyIp.vlan_ids).toEqual(['v1'])
    expect(onlyIp.open_ports).toHaveLength(1)

    const all = eraseGroupValues(full, group({ vlan_mode: 'trunk', ips: [{ ip_address: '1.1.1.1', prefix_length: '', purpose: '' }], manage_open_ports: true }))
    expect(all).toMatchObject({ vlan_mode: 'access', vlan_ids: [], ips: [], open_ports: [] })
  })
})

describe('describeGroup', () => {
  const vlanLabel = (id: string) => `VLAN ${id}`
  const portLabel = (id: string) => id.toUpperCase()

  it('перечисляет заданные параметры', () => {
    const g = group({
      vlan_mode: 'access',
      vlan_ids: ['10'],
      ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }],
      manage_open_ports: true,
      open_ports: [{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: '' }],
    })
    expect(describeGroup(g, vlanLabel, portLabel)).toBe('Access · VLAN 10 · IP 10.0.0.5/24 · Открытые порты: SSH')
  })

  it('группа без параметров — так и сказано', () => {
    expect(describeGroup(group(), vlanLabel, portLabel)).toBe('Параметры не заданы')
  })
})

describe('validateInterfaceGroups', () => {
  it('принимает корректные группы', () => {
    expect(validateInterfaceGroups([group({ ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] })])).toBeNull()
  })

  it.each([
    [{ name: '  ' }, 'наименование'],
    [{ vlan_mode: 'access', vlan_ids: ['a', 'b'] } as Partial<InterfaceGroupDraft>, 'access'],
    [{ ips: [{ ip_address: '999.1.1.1', prefix_length: '', purpose: '' }] }, 'IP-адрес'],
    [{ ips: [{ ip_address: '10.0.0.1', prefix_length: '40', purpose: '' }] }, 'префикс'],
    [
      {
        ips: [
          { ip_address: '10.0.0.1', prefix_length: '24', purpose: '' },
          { ip_address: '10.0.0.2', prefix_length: '', purpose: '' },
          { ip_address: '10.0.0.3x', prefix_length: '', purpose: '' },
        ],
      },
      '10.0.0.3x',
    ],
    [
      {
        ips: [
          { ip_address: '10.0.0.1', prefix_length: '24', purpose: '' },
          { ip_address: ' 10.0.0.1 ', prefix_length: '16', purpose: '' },
        ],
      },
      'несколько раз',
    ],
  ] as [Partial<InterfaceGroupDraft>, string][])('отклоняет некорректную группу %j', (patch, fragment) => {
    const error = validateInterfaceGroups([group(patch)])
    expect(error?.toLowerCase()).toContain(fragment.toLowerCase())
  })

  it('отклоняет повтор наименования без учёта регистра', () => {
    expect(validateInterfaceGroups([group({ key: 'a', name: 'Одна' }), group({ key: 'b', name: 'одна' })])).toContain('уникальны')
  })

  describe('повторяющиеся номера открытых портов группы', () => {
    const portCatalog = [
      { id: 'c-http', port: 80, protocol_type: 'HTTP', description: null },
      { id: 'c-http-alt', port: 80, protocol_type: 'HTTP-Proxy', description: null },
      { id: 'c-ssh', port: 22, protocol_type: 'SSH', description: null },
    ]
    const ports = (...ids: string[]) => ids.map((protocol_catalog_id) => ({ protocol_catalog_id, transport_protocol: 'TCP', description: '' }))

    it('не пропускает повтор номера, когда группа управляет открытыми портами', () => {
      const g = group({ manage_open_ports: true, open_ports: ports('c-http', 'c-ssh', 'c-http-alt') })
      expect(validateInterfaceGroups([g], portCatalog)).toBe('В группе «Серверные» номера открытых портов повторяются: 80.')
    })

    it('список портов игнорируется, если группа ими не управляет', () => {
      const g = group({ manage_open_ports: false, open_ports: ports('c-http', 'c-http-alt') })
      expect(validateInterfaceGroups([g], portCatalog)).toBeNull()
    })

    it('без справочника портов проверка пропускается', () => {
      const g = group({ manage_open_ports: true, open_ports: ports('c-http', 'c-http-alt') })
      expect(validateInterfaceGroups([g])).toBeNull()
    })
  })
})

describe('cloneGroupsForCopy', () => {
  it('копирует группы без id под новыми ключами и перевязывает порты', () => {
    const source = group({
      id: 'srv-id',
      key: 'srv-id',
      vlan_ids: ['v1'],
      open_ports: [{ id: 'op-1', protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: '' }],
    })
    const rows = [row('a', { group_key: 'srv-id' }), row('b')]

    const cloned = cloneGroupsForCopy([source], rows)

    expect(cloned.groups[0].id).toBeUndefined()
    expect(cloned.groups[0].key).not.toBe('srv-id')
    expect(cloned.groups[0].open_ports[0].id).toBeUndefined()
    expect(cloned.rows[0].group_key).toBe(cloned.groups[0].key)
    expect(cloned.rows[1].group_key).toBe('')
    expect(source.vlan_ids).toEqual(['v1'])
  })
})

describe('copyableFields / copyValuesFromRow — копирование значений с порта в группу', () => {
  const full = () =>
    row('Gi0/1', {
      vlan_mode: 'trunk',
      vlan_ids: ['v10', 'v20'],
      ips: [{ id: 'ip-1', ip_address: ' 10.0.0.5 ', prefix_length: '24', purpose: 'Управление' }],
      open_ports: [
        { id: 'op-1', protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'админ' },
        { protocol_catalog_id: '', transport_protocol: 'TCP', description: '' },
      ],
    })
  const all = { vlan: true, ip: true, openPorts: true, subinterfaces: false } // подинтерфейсов у порта нет — копируются остальные

  it('копируемо только то, что на порту реально задано', () => {
    expect(copyableFields(full())).toEqual(all)
    expect(copyableFields(row('пустой'))).toEqual({ vlan: false, ip: false, openPorts: false, subinterfaces: false })
    // режим без VLAN, строка IP без адреса и строка открытых портов без протокола — значений нет
    expect(
      copyableFields(
        row('заготовки', {
          ips: [{ ip_address: '  ', prefix_length: '', purpose: '' }],
          open_ports: [{ protocol_catalog_id: '', transport_protocol: 'TCP', description: '' }],
        }),
      ),
    ).toEqual({ vlan: false, ip: false, openPorts: false, subinterfaces: false })
  })

  it('копирует режим, VLAN, IP и открытые порты в черновик группы без id строк порта', () => {
    const result = copyValuesFromRow(group(), full(), all)

    expect(result).toMatchObject({
      vlan_mode: 'trunk',
      vlan_ids: ['v10', 'v20'],
      ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'Управление' }],
      manage_open_ports: true,
    })
    expect(result.open_ports).toEqual([{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'админ' }])
    expect('id' in result.open_ports[0]).toBe(false)
  })

  it('копирует только отмеченное, остальные параметры группы не трогает', () => {
    const base = group({ vlan_mode: 'access', vlan_ids: ['v99'], ips: [{ ip_address: '1.1.1.1', prefix_length: '8', purpose: '' }] })

    const onlyIp = copyValuesFromRow(base, full(), { vlan: false, ip: true, openPorts: false, subinterfaces: false })

    expect(onlyIp).toMatchObject({
      vlan_mode: 'access',
      vlan_ids: ['v99'],
      ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'Управление' }],
      manage_open_ports: false,
    })
  })

  it('отмеченное, но отсутствующее на порту, не копируется — пустое значение не стирает параметры группы', () => {
    const base = group({
      vlan_mode: 'access',
      vlan_ids: ['v99'],
      ips: [{ ip_address: '1.1.1.1', prefix_length: '8', purpose: '' }],
      manage_open_ports: true,
      open_ports: [{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: '' }],
    })

    expect(copyValuesFromRow(base, row('пустой'), all)).toEqual(base)
  })

  it('режим access копирует не более одного VLAN; массивы порта не делятся с группой', () => {
    const source = row('a', { vlan_mode: 'access', vlan_ids: ['v10', 'v20'] })
    expect(copyValuesFromRow(group(), source, all).vlan_ids).toEqual(['v10'])

    const trunk = row('t', { vlan_mode: 'trunk', vlan_ids: ['v10'] })
    const copied = copyValuesFromRow(group(), trunk, all)
    copied.vlan_ids.push('v30')
    expect(trunk.vlan_ids).toEqual(['v10'])
  })

  it('у порта с несколькими IP копируются все непустые, пустые строки пропускаются', () => {
    const source = row('a', {
      ips: [
        { ip_address: '', prefix_length: '', purpose: '' },
        { ip_address: '10.0.0.7', prefix_length: '25', purpose: '' },
        { ip_address: '10.0.0.8', prefix_length: '26', purpose: '' },
      ],
    })
    expect(copyValuesFromRow(group(), source, all).ips).toEqual([
      { ip_address: '10.0.0.7', prefix_length: '25', purpose: '' },
      { ip_address: '10.0.0.8', prefix_length: '26', purpose: '' },
    ])
  })
})

describe('назначение общего IP-адреса группы', () => {
  const ipRow = (purpose = '') => row('Gi0/1', { ips: [{ id: 'ip-1', ip_address: '1.1.1.1', prefix_length: '8', purpose }] })

  it('applyGroupToRow записывает назначение группы в IP порта, перекрывая назначение порта', () => {
    const g = group({ ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: ' Администрирование ' }] })

    const result = applyGroupToRow(ipRow('Своё'), g)

    expect(result.ips).toEqual([{ id: 'ip-1', ip_address: '10.0.0.5', prefix_length: '24', purpose: 'Администрирование' }])
  })

  it('applyGroupToRow: пустое назначение группы очищает назначение IP порта — как адрес и префикс, оно управляется безусловно', () => {
    const g = group({ ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] })

    expect(applyGroupToRow(ipRow('Своё'), g).ips[0]).toMatchObject({ ip_address: '10.0.0.5', purpose: '' })
    expect(applyGroupToRow(row('Gi0/2'), g).ips[0].purpose).toBe('')
  })

  it('applyGroupToRow: группа без IP не трогает IP порта и его назначение', () => {
    const own = ipRow('Своё')

    expect(applyGroupToRow(own, group({ ips: [{ ip_address: '', prefix_length: '', purpose: 'Администрирование' }] }))).toEqual(own)
  })

  it('copyValuesFromRow копирует назначение вместе с адресом и префиксом (у порта с пустым назначением — пустое)', () => {
    const ips = [{ ip_address: ' 10.0.0.7 ', prefix_length: '25', purpose: ' Резерв ' }]
    const old = group({ ips: [{ ip_address: '1.1.1.1', prefix_length: '', purpose: 'Старое' }] })
    const withPurpose = copyValuesFromRow(old, row('a', { ips }), { vlan: false, ip: true, openPorts: false, subinterfaces: false })
    expect(withPurpose.ips).toEqual([{ ip_address: '10.0.0.7', prefix_length: '25', purpose: 'Резерв' }])

    const without = copyValuesFromRow(old, row('b', { ips: [{ ip_address: '10.0.0.8', prefix_length: '24', purpose: '' }] }), {
      vlan: false,
      ip: true,
      openPorts: false,
      subinterfaces: false,
    })
    expect(without.ips[0].purpose).toBe('')
  })

  it('copyValuesFromRow: без отметки «IP-адрес» назначение группы не трогается', () => {
    const base = group({ ips: [{ ip_address: '1.1.1.1', prefix_length: '', purpose: 'Старое' }] })
    const source = row('a', { ips: [{ ip_address: '10.0.0.7', prefix_length: '25', purpose: 'Новое' }], vlan_ids: ['v1'], vlan_mode: 'trunk' })

    expect(copyValuesFromRow(base, source, { vlan: true, ip: false, openPorts: false, subinterfaces: false }).ips).toEqual(base.ips)
  })

  it('describeGroup показывает назначение рядом с IP', () => {
    const label = (g: InterfaceGroupDraft) =>
      describeGroup(
        g,
        (id) => id,
        (id) => id,
      )
    expect(label(group({ ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'Администрирование' }] }))).toBe('IP 10.0.0.5/24 (Администрирование)')
    expect(label(group({ ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] }))).toBe('IP 10.0.0.5/24')
  })

  it('emptyGroup и cloneGroupsForCopy: назначение пустое по умолчанию и сохраняется при копировании устройства', () => {
    expect(emptyGroup().ips).toEqual([])
    const { groups } = cloneGroupsForCopy([group({ ips: [{ ip_address: '10.0.0.5', prefix_length: '', purpose: 'Администрирование' }] })], [])
    expect(groups[0].ips[0].purpose).toBe('Администрирование')
  })
})

describe('открытые порты группы: строки порта не пересоздаются, список упорядочен', () => {
  const tcp = (protocol_catalog_id: string, description = '', id?: string) => ({ id, protocol_catalog_id, transport_protocol: 'TCP', description })
  const catalogEntries = [
    { id: 'ssh', port: 22, protocol_type: 'SSH', description: null },
    { id: 'telnet', port: 23, protocol_type: 'Telnet', description: null },
    { id: 'https', port: 443, protocol_type: 'HTTPS', description: null },
  ]

  it('applyGroupToRow: лишняя сохранённая строка переиспользуется под новый порт группы (id сохраняется), остаток удаляется', () => {
    const existing = row('Gi0/1', { open_ports: [tcp('ssh', '', 'op-ssh'), tcp('https', '', 'op-https'), tcp('telnet', '', 'op-extra')] })
    // Группа: оставить https и добавить новый порт; ssh и telnet группе больше не нужны.
    const g = group({ manage_open_ports: true, open_ports: [tcp('https', 'внешний'), tcp('new-port', 'новый')] })

    const result = applyGroupToRow(existing, g)

    // https остался на своей строке, новый порт занял первую «лишнюю» строку (ssh), строка telnet пропадёт (её нет в списке).
    expect(result.open_ports).toEqual([
      { id: 'op-https', protocol_catalog_id: 'https', transport_protocol: 'TCP', description: 'внешний' },
      { id: 'op-ssh', protocol_catalog_id: 'new-port', transport_protocol: 'TCP', description: 'новый' },
    ])
  })

  it('applyGroupToRow: портов больше, чем строк у порта, — недостающие создаются без id', () => {
    const existing = row('Gi0/1', { open_ports: [tcp('ssh', '', 'op-ssh')] })
    const g = group({ manage_open_ports: true, open_ports: [tcp('ssh'), tcp('telnet'), tcp('https')] })

    expect(applyGroupToRow(existing, g).open_ports.map((p) => p.id)).toEqual(['op-ssh', undefined, undefined])
  })

  it('applyGroupToRow: несохранённые строки порта (без id) не дают чужих id', () => {
    const existing = row('Gi0/1', { open_ports: [tcp('ssh'), tcp('https', '', 'op-https')] })
    const g = group({ manage_open_ports: true, open_ports: [tcp('telnet')] })

    // ssh — черновая строка без id; под telnet освобождается сохранённая строка https.
    expect(applyGroupToRow(existing, g).open_ports).toEqual([{ id: 'op-https', protocol_catalog_id: 'telnet', transport_protocol: 'TCP', description: '' }])
  })

  it('copyValuesFromRow: открытые порты, скопированные с порта, упорядочиваются по номеру порта', () => {
    const source = row('a', { open_ports: [tcp('https'), tcp(''), tcp('ssh'), tcp('telnet')] })

    const result = copyValuesFromRow(group(), source, { vlan: false, ip: false, openPorts: true, subinterfaces: false }, catalogEntries)

    expect(result.open_ports.map((p) => p.protocol_catalog_id)).toEqual(['ssh', 'telnet', 'https'])
  })

  it('copyValuesFromRow без справочника сохраняет порядок порта (номер не определить)', () => {
    const source = row('a', { open_ports: [tcp('https'), tcp('ssh')] })
    const result = copyValuesFromRow(group(), source, { vlan: false, ip: false, openPorts: true, subinterfaces: false })
    expect(result.open_ports.map((p) => p.protocol_catalog_id)).toEqual(['https', 'ssh'])
  })
})

describe('подинтерфейсы группы портов', () => {
  const v10: VLANDefinition = { id: 'v10', vlan_id: 10, name: 'Серверы', description: '', domain_id: null, domain_name: '', devices: [] }
  const v20: VLANDefinition = { id: 'v20', vlan_id: 20, name: 'Гости', description: '', domain_id: null, domain_name: '', devices: [] }
  const vlans = [v10, v20]
  const tpl = (patch: Partial<SubinterfaceDraftRow> = {}): SubinterfaceDraftRow => ({
    key: 't-10',
    name: '',
    vlan_id: 'v10',
    is_management: false,
    is_data_transfer: false,
    description: '',
    ips: [],
    open_ports: [],
    ...patch,
  })
  const sub = (patch: Partial<SubinterfaceDraftRow> = {}): SubinterfaceDraftRow => ({ ...tpl(), key: 'p-10', name: 'Gi0/1.10', ...patch })
  const managing = (subinterfaces: SubinterfaceDraftRow[], patch: Partial<InterfaceGroupDraft> = {}) =>
    group({ vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], manage_subinterfaces: true, subinterfaces, ...patch })

  describe('applyGroupToRow', () => {
    it('записывает в порт по подинтерфейсу на каждый VLAN шаблона с именем «<порт>.<номер VLAN>»', () => {
      const g = managing([
        tpl({ is_management: true, description: 'упр', ips: [{ ip_address: ' 10.0.10.1 ', prefix_length: '24', purpose: 'шлюз' }] }),
        tpl({ key: 't-20', vlan_id: 'v20', is_data_transfer: true }),
      ])

      const result = applyGroupToRow(row('Gi0/1', { vlan_mode: 'trunk' }), g, vlans)

      expect(result.subinterfaces!.map((s) => [s.name, s.vlan_id, s.is_management, s.is_data_transfer])).toEqual([
        ['Gi0/1.10', 'v10', true, false],
        ['Gi0/1.20', 'v20', false, true],
      ])
      expect(result.subinterfaces![0].ips).toEqual([{ id: undefined, ip_address: '10.0.10.1', prefix_length: '24', purpose: 'шлюз' }])
      expect(result.subinterfaces![0].description).toBe('упр')
    })

    it('подинтерфейс порта на том же VLAN сохраняет id (и id своих IP и открытых портов), прочие подинтерфейсы порта убираются', () => {
      const g = managing([
        tpl({
          ips: [
            { ip_address: '10.0.10.2', prefix_length: '24', purpose: '' },
            { ip_address: '10.0.10.3', prefix_length: '24', purpose: '' },
          ],
          open_ports: [{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: '' }],
        }),
      ])
      const current = row('Gi0/1', {
        subinterfaces: [
          sub({
            id: 'sub-10',
            key: 'k-10',
            ips: [
              { id: 'ip-old', ip_address: '10.0.10.1', prefix_length: '24', purpose: '' },
              { id: 'ip-keep', ip_address: '10.0.10.3', prefix_length: '24', purpose: '' },
            ],
            open_ports: [{ id: 'op-1', protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: '' }],
          }),
          sub({ id: 'sub-30', key: 'k-30', name: 'wan', vlan_id: 'v30' }),
        ],
      })

      const result = applyGroupToRow(current, g, vlans)

      expect(result.subinterfaces).toHaveLength(1) // «wan» на VLAN вне шаблона не остался
      const [only] = result.subinterfaces!
      expect(only).toMatchObject({ id: 'sub-10', key: 'k-10' })
      // ip-keep — тот же адрес остаётся на своей строке; новый 10.0.10.2 занимает освободившуюся строку ip-old
      expect(only.ips.map((i) => [i.id, i.ip_address])).toEqual([
        ['ip-old', '10.0.10.2'],
        ['ip-keep', '10.0.10.3'],
      ])
      expect(only.open_ports[0].id).toBe('op-1')
    })

    it('пустой список шаблонов очищает подинтерфейсы порта; без признака порт не меняется', () => {
      const current = row('Gi0/1', { subinterfaces: [sub({ id: 'sub-10' })] })

      expect(applyGroupToRow(current, managing([]), vlans).subinterfaces).toEqual([])
      expect(applyGroupToRow(current, group({ manage_subinterfaces: false, subinterfaces: [tpl()] }), vlans)).toBe(current)
    })

    it('VLAN шаблона, которого нет в списке, оставляет прежнее имя подинтерфейса порта, у нового имя пустое', () => {
      const g = managing([tpl({ vlan_id: 'v10' }), tpl({ key: 't-99', vlan_id: 'v99' })])
      const current = row('Gi0/1', { subinterfaces: [sub({ id: 'sub-99', name: 'свой', vlan_id: 'v99' })] })

      const result = applyGroupToRow(current, g, [v10])

      expect(result.subinterfaces!.map((s) => [s.vlan_id, s.name, s.id])).toEqual([
        ['v10', 'Gi0/1.10', undefined],
        ['v99', 'свой', 'sub-99'],
      ])
    })

    it('повтор VLAN в шаблонах и шаблон без VLAN пропускаются', () => {
      const g = managing([tpl(), tpl({ key: 't-dup' }), tpl({ key: 't-empty', vlan_id: '' })])

      expect(applyGroupToRow(row('Gi0/1'), g, vlans).subinterfaces).toHaveLength(1)
    })
  })

  it('applyGroupsToRows передаёт VLAN: подинтерфейсы каждого порта группы получают своё имя', () => {
    const rows = [row('Gi0/1', { group_key: 'g1' }), row('Gi0/2', { group_key: 'g1' }), row('Gi0/3')]

    const result = applyGroupsToRows(rows, [managing([tpl()])], vlans)

    expect(result[0].subinterfaces![0].name).toBe('Gi0/1.10')
    expect(result[1].subinterfaces![0].name).toBe('Gi0/2.10')
    expect(result[2]).toBe(rows[2])
  })

  it('eraseGroupValues: «стереть значения» убирает и подинтерфейсы, которыми управляла группа', () => {
    const current = row('Gi0/1', { subinterfaces: [sub()] })

    expect(eraseGroupValues(current, managing([tpl()])).subinterfaces).toEqual([])
    expect(eraseGroupValues(current, group()).subinterfaces).toEqual(current.subinterfaces)
  })

  it('describeGroup: перечисляет VLAN подинтерфейсов; «нет» — если список пуст', () => {
    const label = (id: string) => `VLAN ${id}`
    expect(describeGroup(managing([tpl(), tpl({ key: 't-20', vlan_id: 'v20' })], { vlan_mode: '', vlan_ids: [] }), label, label)).toBe(
      'Подинтерфейсы: VLAN v10, VLAN v20',
    )
    expect(describeGroup(managing([], { vlan_mode: '', vlan_ids: [] }), label, label)).toBe('Подинтерфейсы: нет')
  })

  it('cloneGroupsForCopy: шаблоны копируются без id (у самих строк, IP и открытых портов), исходные не меняются', () => {
    const source = managing(
      [
        tpl({
          id: 'gs-1',
          ips: [{ id: 'gip-1', ip_address: '10.0.10.1', prefix_length: '24', purpose: '' }],
          open_ports: [{ id: 'gop-1', protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: '' }],
        }),
      ],
      { id: 'g-id', key: 'g-id' },
    )

    const cloned = cloneGroupsForCopy([source], [row('a', { group_key: 'g-id' })])

    const [copy] = cloned.groups[0].subinterfaces!
    expect(copy.id).toBeUndefined()
    expect(copy.ips[0].id).toBeUndefined()
    expect(copy.open_ports[0].id).toBeUndefined()
    expect(copy.key).not.toBe('t-10')
    expect(source.subinterfaces![0].id).toBe('gs-1')
  })

  describe('копирование подинтерфейсов с порта в группу', () => {
    const none = { vlan: false, ip: false, openPorts: false, subinterfaces: false }
    const portWithSubs = (subs: SubinterfaceDraftRow[], patch: Partial<InterfaceDraftRow> = {}) =>
      row('Gi0/1', { vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], subinterfaces: subs, ...patch })
    const richSub = () =>
      sub({
        id: 'sub-10',
        is_management: true,
        is_data_transfer: true,
        description: 'сеть серверов',
        ips: [
          { id: 'ip-1', ip_address: ' 10.0.10.1 ', prefix_length: '24', purpose: 'шлюз' },
          { ip_address: '  ', prefix_length: '', purpose: '' },
        ],
        open_ports: [
          { id: 'op-1', protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'админ' },
          { protocol_catalog_id: '', transport_protocol: 'TCP', description: '' },
        ],
      })

    it('copyableFields: подинтерфейсы копируемы, если есть хотя бы один с выбранным VLAN', () => {
      expect(copyableFields(portWithSubs([sub()])).subinterfaces).toBe(true)
      expect(copyableFields(portWithSubs([sub({ vlan_id: '' })])).subinterfaces).toBe(false)
      expect(copyableFields(portWithSubs([])).subinterfaces).toBe(false)
    })

    it('шаблоны получают значения подинтерфейса порта без id и без имени; группа начинает ими управлять', () => {
      const target = group({ vlan_mode: 'trunk', vlan_ids: ['v10'] })

      const result = copyValuesFromRow(target, portWithSubs([richSub()]), { ...none, subinterfaces: true })

      expect(result.manage_subinterfaces).toBe(true)
      expect(result.subinterfaces).toHaveLength(1)
      const [template] = result.subinterfaces!
      expect(template).toMatchObject({ name: '', vlan_id: 'v10', is_management: true, is_data_transfer: true, description: 'сеть серверов' })
      expect(template.id).toBeUndefined()
      expect(template.ips).toEqual([{ ip_address: '10.0.10.1', prefix_length: '24', purpose: 'шлюз' }]) // без id, пустая строка отброшена
      expect(template.open_ports).toEqual([{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'админ' }])
      expect(template.key).not.toBe(richSub().key)
    })

    it('вместе с режимом и VLAN порт копируется целиком: VLAN группы берутся с порта, ничего не отбрасывается', () => {
      const source = portWithSubs([richSub(), sub({ key: 'k-20', vlan_id: 'v20', name: 'Gi0/1.20' })])

      const result = copyValuesFromRow(group(), source, { ...none, vlan: true, subinterfaces: true })

      expect(result.vlan_ids).toEqual(['v10', 'v20'])
      expect(result.subinterfaces!.map((t) => t.vlan_id)).toEqual(['v10', 'v20'])
    })

    it('подинтерфейс на VLAN вне VLAN группы шаблоном не становится (skipped), остальные копируются', () => {
      const target = group({ vlan_mode: 'trunk', vlan_ids: ['v10'] })
      const source = portWithSubs([richSub(), sub({ key: 'k-20', vlan_id: 'v20', name: 'Gi0/1.20' })])

      const { templates, skipped } = subinterfaceTemplatesFromRow(source, target)
      const result = copyValuesFromRow(target, source, { ...none, subinterfaces: true })

      expect(templates.map((t) => t.vlan_id)).toEqual(['v10'])
      expect(skipped.map((s) => s.name)).toEqual(['Gi0/1.20'])
      expect(result.subinterfaces!.map((t) => t.vlan_id)).toEqual(['v10'])
    })

    it('если группе не подошёл ни один подинтерфейс (или режим порта не задан), список группы не меняется — копирование не «стирает»', () => {
      const existing = tpl({ vlan_id: 'v10' })
      const noMode = group({ manage_subinterfaces: true, subinterfaces: [existing] })
      const foreignVlan = group({ vlan_mode: 'trunk', vlan_ids: ['v99'], manage_subinterfaces: true, subinterfaces: [existing] })

      expect(copyValuesFromRow(noMode, portWithSubs([richSub()]), { ...none, subinterfaces: true })).toBe(noMode)
      expect(copyValuesFromRow(foreignVlan, portWithSubs([richSub()]), { ...none, subinterfaces: true })).toBe(foreignVlan)
    })

    it('«Все VLAN» у группы: подходят VLAN устройства; без списка VLAN устройства фильтра нет', () => {
      const target = group({ vlan_mode: 'trunk', all_vlans: true })
      const source = portWithSubs([richSub(), sub({ key: 'k-99', vlan_id: 'v99', name: 'Gi0/1.99' })])

      expect(subinterfaceTemplatesFromRow(source, target, new Set(['v10'])).templates.map((t) => t.vlan_id)).toEqual(['v10'])
      expect(subinterfaceTemplatesFromRow(source, target).templates.map((t) => t.vlan_id)).toEqual(['v10', 'v99'])
    })

    it('не отмеченное или отсутствующее на порту не копируется; исходные подинтерфейсы порта не меняются', () => {
      const source = portWithSubs([richSub()])
      const before = JSON.stringify(source)
      const base = group({ vlan_mode: 'trunk', vlan_ids: ['v10'] })

      expect(copyValuesFromRow(base, source, none)).toBe(base)
      expect(copyValuesFromRow(base, portWithSubs([]), { ...none, subinterfaces: true })).toBe(base)
      copyValuesFromRow(base, source, { ...none, subinterfaces: true }).subinterfaces![0].ips.push({ ip_address: '1.1.1.1', prefix_length: '8', purpose: '' })
      expect(JSON.stringify(source)).toBe(before)
    })
  })

  describe('validateInterfaceGroups', () => {
    const deviceVlans = new Set(['v10', 'v20'])

    it('корректные подинтерфейсы проходят; без признака подинтерфейсы не проверяются', () => {
      expect(validateInterfaceGroups([managing([tpl(), tpl({ key: 't-20', vlan_id: 'v20' })])], [], deviceVlans)).toBeNull()
      expect(validateInterfaceGroups([group({ manage_subinterfaces: false, subinterfaces: [tpl({ vlan_id: '' })] })], [], deviceVlans)).toBeNull()
    })

    it.each([
      ['без режима порта и VLAN группы', () => managing([tpl()], { vlan_mode: '', vlan_ids: [] }), /только вместе с режимом порта и VLAN/],
      ['VLAN не выбран', () => managing([tpl({ vlan_id: '' })]), /не выбран VLAN/],
      ['VLAN не входит в VLAN группы', () => managing([tpl({ vlan_id: 'v20' })], { vlan_ids: ['v10'] }), /не входит в VLAN группы/],
      ['VLAN повторяется', () => managing([tpl(), tpl({ key: 't-dup' })]), /несколько подинтерфейсов на одном VLAN/],
      ['некорректный IP', () => managing([tpl({ ips: [{ ip_address: '10.0.0.999', prefix_length: '24', purpose: '' }] })]), /Некорректный IP-адрес/],
      ['некорректный префикс', () => managing([tpl({ ips: [{ ip_address: '10.0.0.1', prefix_length: '40', purpose: '' }] })]), /Некорректный префикс/],
    ])('%s — сохранение блокируется', (_title, build, expected) => {
      expect(validateInterfaceGroups([build()], [], deviceVlans)).toMatch(expected)
    })

    it('«Все VLAN»: допустимы VLAN устройства; без списка VLAN устройства проверка пропускается', () => {
      const all = managing([tpl({ vlan_id: 'v20' })], { vlan_ids: [], all_vlans: true })
      expect(validateInterfaceGroups([all], [], deviceVlans)).toBeNull()
      expect(validateInterfaceGroups([managing([tpl({ vlan_id: 'v99' })], { vlan_ids: [], all_vlans: true })], [], deviceVlans)).toMatch(
        /не входит в VLAN группы/,
      )
      expect(validateInterfaceGroups([managing([tpl({ vlan_id: 'v99' })], { vlan_ids: [], all_vlans: true })])).toBeNull()
    })
  })
})

describe('несколько общих IP-адресов группы', () => {
  const ip = (ip_address: string, prefix_length = '24', purpose = '') => ({ ip_address, prefix_length, purpose })
  const two = [ip('10.0.0.5', '24', 'Управление'), ip('10.0.1.5', '24', 'Данные')]

  it('managedFields: группа управляет IP, пока есть хотя бы один адрес; строки-плейсхолдеры без адреса не в счёт', () => {
    expect(managedFields(group({ ips: two })).ip).toBe(true)
    expect(managedFields(group({ ips: [ip('', '24', 'Назначение')] })).ip).toBe(false)
    expect(managedFields(group({ ips: [ip('  '), ip(' 10.0.0.5 ')] })).ip).toBe(true)
  })

  it('applyGroupToRow записывает в порт ВСЕ IP группы, а собственные IP порта заменяются', () => {
    const own = row('Gi0/1', { ips: [{ id: 'own-1', ...ip('192.168.1.9', '24', 'Своё') }] })

    const result = applyGroupToRow(own, group({ ips: two }))

    expect(result.ips.map(({ ip_address, purpose }) => [ip_address, purpose])).toEqual([
      ['10.0.0.5', 'Управление'],
      ['10.0.1.5', 'Данные'],
    ])
  })

  it('applyGroupToRow не пересоздаёт записи: совпавший адрес и префикс сохраняют id, лишняя запись порта переиспользуется, остаток удаляется', () => {
    const port = row('Gi0/1', {
      ips: [
        { id: 'a', ...ip('10.0.1.5') },
        { id: 'b', ...ip('192.168.1.9') },
        { id: 'c', ...ip('172.16.0.1') },
      ],
    })

    const result = applyGroupToRow(port, group({ ips: two }))

    expect(result.ips.map((x) => [x.id, x.ip_address])).toEqual([
      ['b', '10.0.0.5'],
      ['a', '10.0.1.5'],
    ]) // 10.0.1.5 — по смыслу, 10.0.0.5 — под лишнюю запись; 'c' удалена
  })

  it('applyGroupToRow: группа без адресов IP порта не трогает (в том числе при заполненном назначении плейсхолдера)', () => {
    const own = row('Gi0/1', { ips: [{ id: 'own-1', ...ip('192.168.1.9') }] })

    expect(applyGroupToRow(own, group({ ips: [ip('', '', 'Назначение')] }))).toEqual(own)
  })

  it('eraseGroupValues стирает все IP порта, пока группа ими управляла', () => {
    const port = row('Gi0/1', {
      ips: [
        { id: 'a', ...ip('10.0.0.5') },
        { id: 'b', ...ip('10.0.1.5') },
      ],
    })

    expect(eraseGroupValues(port, group({ ips: two })).ips).toEqual([])
  })

  it('copyValuesFromRow копирует все непустые IP порта без id; повторы адреса схлопываются, пустые строки пропускаются', () => {
    const source = row('a', {
      ips: [
        { id: 'x', ...ip(' 10.0.0.7 ', '25', ' Резерв ') },
        { id: 'y', ...ip('') },
        { id: 'z', ...ip('10.0.1.7', '24') },
        { id: 'w', ...ip('10.0.0.7', '16') },
      ],
    })

    const result = copyValuesFromRow(group({ ips: [ip('1.1.1.1', '8')] }), source, { vlan: false, ip: true, openPorts: false, subinterfaces: false })

    expect(result.ips).toEqual([ip('10.0.0.7', '25', 'Резерв'), ip('10.0.1.7', '24')])
  })

  it('describeGroup перечисляет все IP группы с префиксом и назначением', () => {
    const label = (g: InterfaceGroupDraft) =>
      describeGroup(
        g,
        (id) => id,
        (id) => id,
      )

    expect(label(group({ ips: [...two, ip('10.0.2.5', '')] }))).toBe('IP 10.0.0.5/24 (Управление), 10.0.1.5/24 (Данные), 10.0.2.5')
    expect(label(group({ ips: [ip('')] }))).toBe('Параметры не заданы')
  })

  it('validateInterfaceGroups: адрес, повторяющийся в группе (с другим префиксом тоже), отклоняется; одинаковые адреса в разных группах допустимы', () => {
    const dup = group({ ips: [ip('10.0.0.5', '24'), ip(' 10.0.0.5 ', '16')] })

    expect(validateInterfaceGroups([dup])).toBe('В группе «Серверные» IP-адрес «10.0.0.5» указан несколько раз.')
    expect(validateInterfaceGroups([group({ key: 'a', name: 'А', ips: two }), group({ key: 'b', name: 'Б', ips: two })])).toBeNull()
  })

  it('validateInterfaceGroups: ошибка указывает на конкретный адрес, а не на первый в списке', () => {
    expect(validateInterfaceGroups([group({ ips: [ip('10.0.0.5'), ip('10.0.0.6', '33')] })])).toContain('«10.0.0.6»')
  })

  it('cloneGroupsForCopy копирует общие IP без id, не разделяя строки с исходной группой', () => {
    const source = group({ ips: [{ id: 'gip-1', ...ip('10.0.0.5', '24', 'Управление') }] })

    const { groups } = cloneGroupsForCopy([source], [])

    expect(groups[0].ips).toEqual([{ id: undefined, ...ip('10.0.0.5', '24', 'Управление') }])
    expect(groups[0].ips[0]).not.toBe(source.ips[0])
  })
})
