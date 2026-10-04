import { describe, it, expect } from 'vitest'
import {
  attachConnectionDrafts,
  changedConnectionRowIds,
  connectionConfigDiffs,
  connectionPayload,
  hasConnectionChanges,
  sameConnection,
  snapshotConnections,
  validateConnectionDrafts,
} from '../interfaceConnections'
import type { Connection, InterfaceConnectionDraft, InterfaceDraftRow } from '../../api/types'

function row(overrides: Partial<InterfaceDraftRow> = {}): InterfaceDraftRow {
  return {
    id: 'if-1',
    name: 'eth0',
    interface_type_id: '',
    mac_address: '',
    speed_id: '',
    is_management: false,
    is_data_transfer: true,
    description: '',
    vlan_ids: [],
    vlan_mode: 'trunk',
    ips: [],
    open_ports: [],
    ...overrides,
  }
}

function draft(overrides: Partial<InterfaceConnectionDraft> = {}): InterfaceConnectionDraft {
  return { peer_device_id: 'dev-2', peer_interface_id: 'if-peer', connection_type_id: 'ct-1', description: '', ...overrides }
}

function connection(overrides: Partial<Connection> = {}): Connection {
  return { id: 'c-1', source_interface_id: 'if-1', destination_interface_id: 'if-peer', connection_type_id: 'ct-1', is_active: true, description: null, ...overrides } as Connection
}

const interfaces = [
  { id: 'if-1', physical_device_id: 'dev-1' },
  { id: 'if-peer', physical_device_id: 'dev-2' },
]

describe('attachConnectionDrafts', () => {
  it('подключает активное подключение порта; сосед — другая сторона подключения', () => {
    const [asSource] = attachConnectionDrafts([row()], [connection({ description: 'патч-корд' })], interfaces)
    expect(asSource.connection).toEqual({ peer_device_id: 'dev-2', peer_interface_id: 'if-peer', connection_type_id: 'ct-1', description: 'патч-корд' })

    const [asDestination] = attachConnectionDrafts([row({ id: 'if-peer' })], [connection()], interfaces)
    expect(asDestination.connection).toMatchObject({ peer_device_id: 'dev-1', peer_interface_id: 'if-1' })
  })

  it('порт без подключения, неактивное подключение и строка без id дают null', () => {
    expect(attachConnectionDrafts([row()], [], interfaces)[0].connection).toBeNull()
    expect(attachConnectionDrafts([row()], [connection({ is_active: false })], interfaces)[0].connection).toBeNull()
    expect(attachConnectionDrafts([row({ id: undefined })], [connection()], interfaces)[0].connection).toBeNull()
  })

  it('сосед, которого нет в каталоге портов, не роняет загрузку — устройство остаётся пустым', () => {
    const [result] = attachConnectionDrafts([row()], [connection()], [])
    expect(result.connection).toMatchObject({ peer_device_id: '', peer_interface_id: 'if-peer' })
  })

  it('не меняет исходные строки', () => {
    const original = row()
    attachConnectionDrafts([original], [connection()], interfaces)
    expect(original.connection).toBeUndefined()
  })
})

describe('sameConnection', () => {
  it('null и null — одно и то же, null и подключение — разное', () => {
    expect(sameConnection(null, null)).toBe(true)
    expect(sameConnection(undefined, null)).toBe(true)
    expect(sameConnection(null, draft())).toBe(false)
  })

  it('служебный peer_device_id и пробелы по краям описания не считаются изменением', () => {
    expect(sameConnection(draft({ peer_device_id: '' }), draft({ description: '  ' }))).toBe(true)
    expect(sameConnection(draft({ description: 'a ' }), draft({ description: 'a' }))).toBe(true)
  })

  it('другой порт, другой тип линии или другое описание — изменение', () => {
    expect(sameConnection(draft(), draft({ peer_interface_id: 'other' }))).toBe(false)
    expect(sameConnection(draft(), draft({ connection_type_id: 'ct-2' }))).toBe(false)
    expect(sameConnection(draft(), draft({ description: 'новое' }))).toBe(false)
  })
})

describe('connectionPayload', () => {
  const baseline = snapshotConnections([row({ connection: draft() }), row({ id: 'if-free', connection: null })])

  it('подключение не менялось — undefined (ключ в запрос не попадает)', () => {
    expect(connectionPayload(row({ connection: draft() }), baseline)).toBeUndefined()
    expect(connectionPayload(row({ id: 'if-free', connection: null }), baseline)).toBeUndefined()
    expect(connectionPayload(row({ id: 'if-free' }), baseline)).toBeUndefined() // не задано = не подключён
  })

  it('подключение снято — null', () => {
    expect(connectionPayload(row({ connection: null }), baseline)).toBeNull()
  })

  it('создано или изменено — объект без служебного peer_device_id, пустое описание становится null', () => {
    expect(connectionPayload(row({ id: 'if-free', connection: draft({ description: '  ' }) }), baseline)).toEqual({
      peer_interface_id: 'if-peer',
      connection_type_id: 'ct-1',
      description: null,
    })
    expect(connectionPayload(row({ connection: draft({ connection_type_id: 'ct-2', description: ' uplink ' }) }), baseline)).toEqual({
      peer_interface_id: 'if-peer',
      connection_type_id: 'ct-2',
      description: 'uplink',
    })
  })

  it('новый порт без id: подключение отправляется, отсутствие подключения — нет', () => {
    expect(connectionPayload(row({ id: undefined, connection: draft() }), baseline)).toMatchObject({ peer_interface_id: 'if-peer' })
    expect(connectionPayload(row({ id: undefined, connection: null }), baseline)).toBeUndefined()
  })
})

describe('changedConnectionRowIds / hasConnectionChanges', () => {
  const baseline = snapshotConnections([row({ connection: draft() }), row({ id: 'if-2', connection: null })])

  it('перечисляет только сохранённые порты с изменённым подключением', () => {
    const rows = [row({ connection: draft() }), row({ id: 'if-2', connection: draft({ peer_interface_id: 'x' }) }), row({ id: undefined, connection: draft() })]
    expect([...changedConnectionRowIds(rows, baseline)]).toEqual(['if-2'])
  })

  it('hasConnectionChanges учитывает и новые порты', () => {
    expect(hasConnectionChanges([row({ connection: draft() })], baseline)).toBe(false)
    expect(hasConnectionChanges([row({ connection: draft() }), row({ id: undefined, connection: draft() })], baseline)).toBe(true)
    expect(hasConnectionChanges([row({ connection: null })], baseline)).toBe(true) // отключение
  })
})

describe('validateConnectionDrafts', () => {
  const empty = snapshotConnections([])

  it('нет подключений — нет ошибки', () => {
    expect(validateConnectionDrafts([row(), row({ id: undefined })], empty)).toBeNull()
  })

  it('незаконченный черновик (нет порта соседа или типа линии) — ошибка с именем порта', () => {
    expect(validateConnectionDrafts([row({ connection: draft({ peer_interface_id: '' }) })], empty)).toContain('«eth0»')
    expect(validateConnectionDrafts([row({ connection: draft({ connection_type_id: '' }) })], empty)).toContain('тип физической линии связи')
  })

  it('уже сохранённое подключение не проверяется на полноту — оно не мешает сохранить остальное', () => {
    const baseline = snapshotConnections([row({ connection: draft({ connection_type_id: '' }) })])
    expect(validateConnectionDrafts([row({ connection: draft({ connection_type_id: '' }) })], baseline)).toBeNull()
  })

  it('один порт соседа в двух строках — ошибка, даже если одно из подключений уже сохранено', () => {
    const baseline = snapshotConnections([row({ connection: draft() })])
    const rows = [row({ connection: draft() }), row({ id: undefined, name: 'eth1', connection: draft() })]
    expect(validateConnectionDrafts(rows, baseline)).toContain('нескольких портов')
  })
})

describe('connectionConfigDiffs', () => {
  const peer = { is_management: false, is_data_transfer: true, vlan_mode: 'trunk' as const }

  it('совпадающие конфигурации — пустой список', () => {
    expect(connectionConfigDiffs({ ...peer }, peer)).toEqual([])
  })

  it('перечисляет различающиеся роли и режим порта', () => {
    expect(connectionConfigDiffs({ is_management: true, is_data_transfer: false, vlan_mode: 'access' }, peer)).toEqual([
      '«Управление»: да / у соседа нет',
      '«Передача данных»: нет / у соседа да',
      'режим порта: access / у соседа trunk',
    ])
  })
})
