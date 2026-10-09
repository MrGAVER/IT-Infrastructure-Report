import { describe, it, expect } from 'vitest'
import {
  emptySubinterface,
  groupSubinterfacesByParent,
  stripSubinterfaceIds,
  subinterfacesPayload,
  suggestSubinterfaceName,
  toSubinterfaceDraftRow,
  validateSubinterfaceRows,
} from '../subinterfaces'
import type { DeviceSubinterface, InterfaceDraftRow, ProtocolPortCatalogEntry, SubinterfaceDraftRow, VLANDefinition } from '../../api/types'

const vlan10: VLANDefinition = { id: 'v-10', vlan_id: 10, name: 'Серверы', description: '', domain_id: null, domain_name: '', devices: [] }

const catalog: ProtocolPortCatalogEntry[] = [
  { id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null },
  { id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null },
]

function sub(patch: Partial<SubinterfaceDraftRow> = {}): SubinterfaceDraftRow {
  return { ...emptySubinterface('Gi0/0', vlan10), ...patch }
}

function port(name: string, subinterfaces?: SubinterfaceDraftRow[]): InterfaceDraftRow {
  return {
    name,
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
    ...(subinterfaces ? { subinterfaces } : {}),
  }
}

const serverSub: DeviceSubinterface = {
  id: 'sub-1',
  parent_interface_id: 'if-1',
  name: 'Gi0/0.10',
  vlan_id: 'v-10',
  is_management: false,
  is_data_transfer: true,
  description: null,
  ips: [{ id: 'ip-1', ip_address: '10.0.10.1', prefix_length: 24, purpose: null, is_management: false }],
  open_ports: [{ id: 'op-1', protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: null }],
} as unknown as DeviceSubinterface

describe('suggestSubinterfaceName', () => {
  it('«<порт>.<VLAN>», как у сетевого оборудования', () => {
    expect(suggestSubinterfaceName('Gi0/0', 10)).toBe('Gi0/0.10')
    expect(suggestSubinterfaceName('  eth1 ', 200)).toBe('eth1.200')
  })

  it('у порта без имени подсказывать нечего', () => {
    expect(suggestSubinterfaceName('', 10)).toBe('')
    expect(suggestSubinterfaceName('   ', 10)).toBe('')
  })
})

describe('emptySubinterface', () => {
  it('без VLAN — пустая строка без имени, у каждой строки свой ключ', () => {
    const a = emptySubinterface('Gi0/0')
    const b = emptySubinterface('Gi0/0')
    expect(a).toMatchObject({ name: '', vlan_id: '', is_management: false, is_data_transfer: false, ips: [], open_ports: [] })
    expect(a.id).toBeUndefined()
    expect(a.key).not.toBe(b.key)
  })

  it('с VLAN — подставляет VLAN и подсказку имени', () => {
    expect(emptySubinterface('Gi0/0', vlan10)).toMatchObject({ name: 'Gi0/0.10', vlan_id: 'v-10' })
  })
})

describe('toSubinterfaceDraftRow / groupSubinterfacesByParent', () => {
  it('приводит ответ сервера к строке формы: числа — в строки, null — в пустые строки, ключ = id', () => {
    expect(toSubinterfaceDraftRow(serverSub)).toEqual({
      id: 'sub-1',
      key: 'sub-1',
      name: 'Gi0/0.10',
      vlan_id: 'v-10',
      is_management: false,
      is_data_transfer: true,
      description: '',
      ips: [{ id: 'ip-1', ip_address: '10.0.10.1', prefix_length: '24', purpose: '' }],
      open_ports: [{ id: 'op-1', protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }],
    })
  })

  it('группирует по порту-родителю и сохраняет порядок сервера', () => {
    const grouped = groupSubinterfacesByParent([
      serverSub,
      { ...serverSub, id: 'sub-2', parent_interface_id: 'if-2', name: 'Gi0/1.20' },
      { ...serverSub, id: 'sub-3', name: 'Gi0/0.30' },
    ])
    expect(grouped.get('if-1')!.map((s) => s.name)).toEqual(['Gi0/0.10', 'Gi0/0.30'])
    expect(grouped.get('if-2')!.map((s) => s.id)).toEqual(['sub-2'])
    expect(grouped.get('if-3')).toBeUndefined()
  })
})

describe('stripSubinterfaceIds', () => {
  it('убирает id у подинтерфейсов, их IP и открытых портов (копирование устройства), пересоздаёт ключи', () => {
    const source = [toSubinterfaceDraftRow(serverSub)]
    const [copy] = stripSubinterfaceIds(source)!
    expect(copy.id).toBeUndefined()
    expect(copy.key).not.toBe('sub-1')
    expect(copy.ips[0].id).toBeUndefined()
    expect(copy.open_ports[0].id).toBeUndefined()
    expect(copy).toMatchObject({ name: 'Gi0/0.10', vlan_id: 'v-10', is_data_transfer: true })
    // исходные строки не мутируются
    expect(source[0].id).toBe('sub-1')
    expect(source[0].ips[0].id).toBe('ip-1')
  })

  it('undefined остаётся undefined («не трогали»), пустой список — пустым', () => {
    expect(stripSubinterfaceIds(undefined)).toBeUndefined()
    expect(stripSubinterfaceIds([])).toEqual([])
  })
})

describe('validateSubinterfaceRows', () => {
  it('порты без подинтерфейсов и корректные подинтерфейсы проходят', () => {
    expect(validateSubinterfaceRows([port('Gi0/0'), port('Gi0/1', [])])).toBeNull()
    expect(validateSubinterfaceRows([port('Gi0/0', [sub({ ips: [{ ip_address: '10.0.10.1', prefix_length: '24', purpose: '' }] })])])).toBeNull()
  })

  it('требует имя и VLAN', () => {
    expect(validateSubinterfaceRows([port('Gi0/0', [sub({ name: '  ' })])])).toMatch(/должно быть имя/)
    expect(validateSubinterfaceRows([port('Gi0/0', [sub({ vlan_id: '' })])])).toMatch(/не выбран VLAN/)
  })

  it('имя не длиннее 100 символов', () => {
    expect(validateSubinterfaceRows([port('Gi0/0', [sub({ name: 'x'.repeat(101) })])])).toMatch(/100 символов/)
  })

  it('имя уникально на устройстве без учёта регистра (в том числе между разными портами)', () => {
    const rows = [port('Gi0/0', [sub({ name: 'Sub.10', vlan_id: 'v-10' })]), port('Gi0/1', [sub({ name: 'sub.10', vlan_id: 'v-20' })])]
    expect(validateSubinterfaceRows(rows)).toMatch(/повторяется/)
  })

  it('имя не совпадает с именем порта устройства', () => {
    expect(validateSubinterfaceRows([port('Gi0/0', [sub({ name: 'gi0/1' })]), port('Gi0/1')])).toMatch(/совпадает с именем порта/)
  })

  it('на одном порту VLAN используется один раз, на разных портах — можно', () => {
    const twiceOnOnePort = port('Gi0/0', [sub({ name: 'a', vlan_id: 'v-10' }), sub({ name: 'b', vlan_id: 'v-10' })])
    expect(validateSubinterfaceRows([twiceOnOnePort])).toMatch(/на одном VLAN/)
    const onTwoPorts = [port('Gi0/0', [sub({ name: 'a', vlan_id: 'v-10' })]), port('Gi0/1', [sub({ name: 'b', vlan_id: 'v-10' })])]
    expect(validateSubinterfaceRows(onTwoPorts)).toBeNull()
  })

  it('проверяет IP-адрес и префикс', () => {
    expect(validateSubinterfaceRows([port('Gi0/0', [sub({ ips: [{ ip_address: '10.0.10.999', prefix_length: '24', purpose: '' }] })])])).toMatch(/Некорректный IP-адрес/)
    expect(validateSubinterfaceRows([port('Gi0/0', [sub({ ips: [{ ip_address: '10.0.10.1', prefix_length: '33', purpose: '' }] })])])).toMatch(/Некорректный префикс/)
  })

  it('номера открытых портов подинтерфейса не повторяются', () => {
    const dup = sub({
      open_ports: [
        { protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' },
        { protocol_catalog_id: 'cat-ssh', transport_protocol: 'UDP', description: '' },
      ],
    })
    expect(validateSubinterfaceRows([port('Gi0/0', [dup])], catalog)).toMatch(/повторяются: 22/)
  })
})

describe('subinterfacesPayload', () => {
  it('обрезает имя и IP, приводит префикс к числу, пустые значения — к null, пропускает пустые плейсхолдеры', () => {
    const payload = subinterfacesPayload([
      sub({
        id: 'sub-1',
        name: '  Gi0/0.10 ',
        description: '',
        is_data_transfer: true,
        ips: [
          { id: 'ip-1', ip_address: ' 10.0.10.1 ', prefix_length: '24', purpose: 'Шлюз' },
          { ip_address: '  ', prefix_length: '', purpose: '' },
          { ip_address: '10.0.10.2', prefix_length: '', purpose: '' },
        ],
        open_ports: [
          { id: 'op-1', protocol_catalog_id: 'cat-ssh', transport_protocol: '', description: '' },
          { protocol_catalog_id: '', transport_protocol: 'TCP', description: '' },
        ],
      }),
    ])
    expect(payload).toEqual([
      {
        id: 'sub-1',
        name: 'Gi0/0.10',
        vlan_id: 'v-10',
        is_management: false,
        is_data_transfer: true,
        description: null,
        ips: [
          { id: 'ip-1', ip_address: '10.0.10.1', prefix_length: 24, purpose: 'Шлюз' },
          { id: undefined, ip_address: '10.0.10.2', prefix_length: null, purpose: null },
        ],
        open_ports: [{ id: 'op-1', protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: null }],
      },
    ])
  })

  it('пустой список остаётся пустым (на сервере — «удалить все подинтерфейсы порта»)', () => {
    expect(subinterfacesPayload([])).toEqual([])
  })
})
