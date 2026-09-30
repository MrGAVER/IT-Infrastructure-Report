import { describe, it, expect } from 'vitest'
import type { InterfaceDraftRow, InterfaceGroupDraft } from '../../api/types'
import {
  applyGroupToRow,
  applyGroupsToRows,
  cloneGroupsForCopy,
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
    name, interface_type_id: '', mac_address: '', speed_id: '', is_management: false, is_data_transfer: false,
    description: '', vlan_ids: [], vlan_mode: 'access', ips: [], open_ports: [], ...patch,
  }
}

function group(patch: Partial<InterfaceGroupDraft> = {}): InterfaceGroupDraft {
  return { ...emptyGroup('Серверные'), key: 'g1', ...patch }
}

describe('managedFields', () => {
  it('группа управляет только заданными параметрами', () => {
    expect(managedFields(group())).toEqual({ vlan: false, ip: false, openPorts: false })
    expect(managedFields(group({ vlan_mode: 'trunk', ip_address: ' 10.0.0.5 ', manage_open_ports: true }))).toEqual({ vlan: true, ip: true, openPorts: true })
    expect(managedFields(undefined)).toEqual({ vlan: false, ip: false, openPorts: false })
  })
})

describe('applyGroupToRow', () => {
  it('записывает в порт режим, VLAN, общий IP и открытые порты группы', () => {
    const g = group({
      vlan_mode: 'access', vlan_ids: ['v10'], ip_address: '10.0.0.5', prefix_length: '24', manage_open_ports: true,
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
      ips: [{ id: 'ip-1', ip_address: '1.1.1.1', prefix_length: '8', purpose: 'Управление' }, { id: 'ip-2', ip_address: '2.2.2.2', prefix_length: '8', purpose: '' }],
      open_ports: [{ id: 'op-1', protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'старое' }],
    })
    const g = group({ ip_address: '10.0.0.5', prefix_length: '24', manage_open_ports: true, open_ports: [{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: 'новое' }] })

    const result = applyGroupToRow(existing, g)

    expect(result.ips).toEqual([{ id: 'ip-1', ip_address: '10.0.0.5', prefix_length: '24', purpose: 'Управление' }])
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
    expect(applyGroupToRow(row('p', { open_ports: [{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: '' }] }), group({ manage_open_ports: true })).open_ports).toEqual([])
  })
})

describe('applyGroupsToRows / setGroupMembers / memberIndices', () => {
  it('применяет группу только к её портам; порт переходит между группами, исключённый остаётся без группы', () => {
    const g1 = group({ key: 'g1', ip_address: '10.0.0.1' })
    const g2 = group({ key: 'g2', name: 'Вторая', ip_address: '10.0.0.2' })
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
    const full = row('a', { vlan_mode: 'trunk', vlan_ids: ['v1'], ips: [{ ip_address: '1.1.1.1', prefix_length: '24', purpose: '' }], open_ports: [{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: '' }] })

    const onlyIp = eraseGroupValues(full, group({ ip_address: '1.1.1.1' }))
    expect(onlyIp.ips).toEqual([])
    expect(onlyIp.vlan_ids).toEqual(['v1'])
    expect(onlyIp.open_ports).toHaveLength(1)

    const all = eraseGroupValues(full, group({ vlan_mode: 'trunk', ip_address: '1.1.1.1', manage_open_ports: true }))
    expect(all).toMatchObject({ vlan_mode: 'access', vlan_ids: [], ips: [], open_ports: [] })
  })
})

describe('describeGroup', () => {
  const vlanLabel = (id: string) => `VLAN ${id}`
  const portLabel = (id: string) => id.toUpperCase()

  it('перечисляет заданные параметры', () => {
    const g = group({ vlan_mode: 'access', vlan_ids: ['10'], ip_address: '10.0.0.5', prefix_length: '24', manage_open_ports: true, open_ports: [{ protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: '' }] })
    expect(describeGroup(g, vlanLabel, portLabel)).toBe('Access · VLAN 10 · IP 10.0.0.5/24 · Открытые порты: SSH')
  })

  it('группа без параметров — так и сказано', () => {
    expect(describeGroup(group(), vlanLabel, portLabel)).toBe('Параметры не заданы')
  })
})

describe('validateInterfaceGroups', () => {
  it('принимает корректные группы', () => {
    expect(validateInterfaceGroups([group({ ip_address: '10.0.0.5', prefix_length: '24' })])).toBeNull()
  })

  it.each([
    [{ name: '  ' }, 'наименование'],
    [{ vlan_mode: 'access', vlan_ids: ['a', 'b'] } as Partial<InterfaceGroupDraft>, 'access'],
    [{ ip_address: '999.1.1.1' }, 'IP-адрес'],
    [{ ip_address: '10.0.0.1', prefix_length: '40' }, 'префикс'],
  ])('отклоняет некорректную группу %j', (patch, fragment) => {
    const error = validateInterfaceGroups([group(patch)])
    expect(error?.toLowerCase()).toContain(fragment.toLowerCase())
  })

  it('отклоняет повтор наименования без учёта регистра', () => {
    expect(validateInterfaceGroups([group({ key: 'a', name: 'Одна' }), group({ key: 'b', name: 'одна' })])).toContain('уникальны')
  })
})

describe('cloneGroupsForCopy', () => {
  it('копирует группы без id под новыми ключами и перевязывает порты', () => {
    const source = group({ id: 'srv-id', key: 'srv-id', vlan_ids: ['v1'], open_ports: [{ id: 'op-1', protocol_catalog_id: 'ssh', transport_protocol: 'TCP', description: '' }] })
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
