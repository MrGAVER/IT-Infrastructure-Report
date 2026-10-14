import { describe, it, expect } from 'vitest'
import {
  attachConnectionDrafts,
  changedConnectionRowIds,
  connectionConfigDiffKinds,
  connectionConfigDiffs,
  connectionPayload,
  connectionPointsTo,
  hasConnectionChanges,
  isConnectionChanged,
  newRowKey,
  peerRef,
  rowRef,
  sameConnection,
  snapshotConnections,
  validateConnectionDrafts,
} from '../interfaceConnections'
import type { DeviceInterfaceConnection } from '../../api/deviceConnectivity'
import type { InterfaceConnectionDraft, InterfaceDraftRow } from '../../api/types'

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

function serverConnection(overrides: Partial<DeviceInterfaceConnection> = {}): DeviceInterfaceConnection {
  return {
    interface_id: 'if-1',
    connection_id: 'c-1',
    connection_type_id: 'ct-1',
    description: null,
    peer_interface_id: 'if-peer',
    peer_interface_name: 'Gi0/1',
    peer_device_id: 'dev-2',
    peer_device_name: 'sw-2',
    peer_is_management: false,
    peer_is_data_transfer: true,
    peer_vlan_mode: 'trunk',
    peer_all_vlans: false,
    ...overrides,
  }
}

describe('attachConnectionDrafts', () => {
  it('подставляет подключение порта из ответа сервера: сосед, порт соседа, тип линии, описание', () => {
    const [result] = attachConnectionDrafts([row()], [serverConnection({ description: 'патч-корд' })])
    // Подписи устройства и порта соседа берутся из ответа сервера: полного списка устройств у формы нет.
    expect(result.connection).toEqual({ peer_device_id: 'dev-2', peer_device_name: 'sw-2', peer_interface_id: 'if-peer', peer_interface_name: 'Gi0/1', connection_type_id: 'ct-1', description: 'патч-корд' })
  })

  it('порт без подключения и строка без id (ещё не сохранённый порт) дают null', () => {
    expect(attachConnectionDrafts([row()], [])[0].connection).toBeNull()
    expect(attachConnectionDrafts([row({ id: undefined })], [serverConnection()])[0].connection).toBeNull()
    expect(attachConnectionDrafts([row({ id: 'if-other' })], [serverConnection()])[0].connection).toBeNull()
  })

  it('у порта несколько действующих подключений (исторические данные) — берётся первое в порядке ответа', () => {
    const [result] = attachConnectionDrafts([row()], [serverConnection({ peer_interface_id: 'first' }), serverConnection({ peer_interface_id: 'second' })])
    expect(result.connection?.peer_interface_id).toBe('first')
  })

  it('кабель между двумя портами одного устройства виден у обоих портов', () => {
    const rows = attachConnectionDrafts(
      [row({ id: 'a' }), row({ id: 'b' })],
      [serverConnection({ interface_id: 'a', peer_interface_id: 'b', peer_device_id: 'dev-1' }), serverConnection({ interface_id: 'b', peer_interface_id: 'a', peer_device_id: 'dev-1' })],
    )
    expect(rows.map((r) => r.connection?.peer_interface_id)).toEqual(['b', 'a'])
  })

  it('не меняет исходные строки', () => {
    const original = row()
    attachConnectionDrafts([original], [serverConnection()])
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

  it('«Все VLAN» сверяется только у двух trunk-портов: текст в обе стороны', () => {
    expect(connectionConfigDiffs({ ...peer, all_vlans: true }, { ...peer, all_vlans: false })).toEqual(['«Все VLAN»: да / у соседа нет'])
    expect(connectionConfigDiffs({ ...peer, all_vlans: false }, { ...peer, all_vlans: true })).toEqual(['«Все VLAN»: нет / у соседа да'])
    expect(connectionConfigDiffs({ ...peer, all_vlans: true }, { ...peer, all_vlans: true })).toEqual([])
    // разные режимы — только режим, признак отдельной строкой не показывается
    expect(connectionConfigDiffs({ ...peer, vlan_mode: 'access' }, { ...peer, all_vlans: true })).toEqual(['режим порта: access / у соседа trunk'])
  })
})

// ---- соседи из этой же формы: порты без id (peer_row_key) и другие порты того же устройства ----

describe('ссылки на строки формы', () => {
  it('newRowKey даёт разные ключи', () => {
    expect(newRowKey()).not.toBe(newRowKey())
  })

  it('peerRef: id сохранённого порта либо row:<key>; rowRef — то же для самой строки', () => {
    expect(peerRef(draft())).toBe('if-peer')
    expect(peerRef(draft({ peer_interface_id: '', peer_row_key: 'k1' }))).toBe('row:k1')
    expect(rowRef({ id: 'if-1', key: 'k1' })).toBe('if-1') // сохранённая строка — по id, даже если ключ есть
    expect(rowRef({ key: 'k1' })).toBe('row:k1')
    expect(rowRef({})).toBe('')
  })

  it('connectionPointsTo: указывает ли подключение на строку; пустые ссылки никуда не указывают', () => {
    expect(connectionPointsTo(draft({ peer_interface_id: 'if-9' }), { id: 'if-9' })).toBe(true)
    expect(connectionPointsTo(draft({ peer_interface_id: '', peer_row_key: 'k1' }), { key: 'k1' })).toBe(true)
    expect(connectionPointsTo(draft({ peer_interface_id: '', peer_row_key: 'k1' }), { key: 'k2' })).toBe(false)
    expect(connectionPointsTo(draft({ peer_interface_id: '' }), {})).toBe(false)
    expect(connectionPointsTo(null, { id: 'if-9' })).toBe(false)
  })

  it('sameConnection: разные строки-соседи — это изменение', () => {
    const a = draft({ peer_interface_id: '', peer_row_key: 'k1' })
    expect(sameConnection(a, { ...a })).toBe(true)
    expect(sameConnection(a, { ...a, peer_row_key: 'k2' })).toBe(false)
    expect(sameConnection(a, draft())).toBe(false)
  })

  it('isConnectionChanged сравнивает со снимком; у строки без id снимка нет', () => {
    const baseline = snapshotConnections([row({ connection: draft() })])
    expect(isConnectionChanged(row({ connection: draft() }), baseline)).toBe(false)
    expect(isConnectionChanged(row({ connection: null }), baseline)).toBe(true)
    expect(isConnectionChanged(row({ id: undefined, connection: draft() }), baseline)).toBe(true)
    expect(isConnectionChanged(row({ id: undefined, connection: null }), baseline)).toBe(false)
  })
})

describe('connectionPayload: сосед — строка этой же формы', () => {
  const empty = snapshotConnections([])
  const rows = [row({ id: undefined, key: 'k0', name: 'eth0' }), row({ id: undefined, key: 'k1', name: 'eth1' }), row({ id: 'if-3', name: 'eth2' })]

  it('несохранённая строка-сосед уходит номером элемента массива interfaces (peer_row), без peer_interface_id', () => {
    const payload = connectionPayload({ id: undefined, connection: draft({ peer_interface_id: '', peer_row_key: 'k1', description: ' кабель ' }) }, empty, rows)
    expect(payload).toEqual({ peer_row: 1, connection_type_id: 'ct-1', description: 'кабель' })
    expect(payload).not.toHaveProperty('peer_interface_id')
  })

  it('сохранённый сосед того же устройства уходит обычным peer_interface_id', () => {
    expect(connectionPayload({ id: undefined, connection: draft({ peer_interface_id: 'if-3' }) }, empty, rows)).toEqual({ peer_interface_id: 'if-3', connection_type_id: 'ct-1', description: null })
  })

  it('строки-соседа нет среди строк — исключение, а не отправка мусора', () => {
    expect(() => connectionPayload({ id: undefined, connection: draft({ peer_interface_id: '', peer_row_key: 'gone' }) }, empty, rows)).toThrow('не найден')
  })

  it('неизменённое подключение не требует списка строк', () => {
    const baseline = snapshotConnections([row({ connection: draft() })])
    expect(connectionPayload(row({ connection: draft() }), baseline)).toBeUndefined()
  })
})

describe('validateConnectionDrafts: соседи из этой же формы', () => {
  const empty = snapshotConnections([])
  const toKey = (key: string, extra: Partial<InterfaceConnectionDraft> = {}) => draft({ peer_interface_id: '', peer_row_key: key, ...extra })

  it('кабель между двумя новыми портами, описанный с одной стороны, — без ошибок', () => {
    const rows = [row({ id: undefined, key: 'k0', name: 'eth0', connection: toKey('k1') }), row({ id: undefined, key: 'k1', name: 'eth1' })]
    expect(validateConnectionDrafts(rows, empty)).toBeNull()
  })

  it('тот же кабель, описанный с обеих сторон, — не ошибка (сервер склеит в одно подключение)', () => {
    const rows = [row({ id: undefined, key: 'k0', name: 'eth0', connection: toKey('k1') }), row({ id: undefined, key: 'k1', name: 'eth1', connection: toKey('k0') })]
    expect(validateConnectionDrafts(rows, empty)).toBeNull()
  })

  it('сосед удалён из списка портов — ошибка с именем порта', () => {
    const rows = [row({ id: undefined, key: 'k0', name: 'eth0', connection: toKey('gone') })]
    expect(validateConnectionDrafts(rows, empty)).toContain('удалён из списка портов')
  })

  it('порт нельзя подключить к самому себе', () => {
    const rows = [row({ id: undefined, key: 'k0', name: 'eth0', connection: toKey('k0') }), row({ id: 'if-1', name: 'eth1', connection: draft({ peer_interface_id: 'if-1' }) })]
    expect(validateConnectionDrafts(rows.slice(0, 1), empty)).toContain('к самому себе')
    expect(validateConnectionDrafts(rows.slice(1), empty)).toContain('к самому себе')
  })

  it('сосед из этой же формы, подключённый в другое место, — ошибка: порт участвует только в одном подключении', () => {
    const rows = [
      row({ id: undefined, key: 'k0', name: 'eth0', connection: toKey('k1') }),
      row({ id: undefined, key: 'k1', name: 'eth1', connection: draft({ peer_interface_id: 'if-peer' }) }),
    ]
    expect(validateConnectionDrafts(rows, empty)).toContain('«eth1» выбран соседом для порта «eth0»')
  })

  it('одна и та же строка-сосед для двух портов — ошибка дублирования', () => {
    const rows = [
      row({ id: undefined, key: 'k0', name: 'eth0', connection: toKey('k2') }),
      row({ id: undefined, key: 'k1', name: 'eth1', connection: toKey('k2') }),
      row({ id: undefined, key: 'k2', name: 'eth2' }),
    ]
    expect(validateConnectionDrafts(rows, empty)).toContain('нескольких портов')
  })
})

describe('connectionConfigDiffKinds', () => {
  const peer = { is_management: false, is_data_transfer: true, vlan_mode: 'trunk' as const }

  it('совпадающие конфигурации — расхождений нет', () => {
    expect(connectionConfigDiffKinds({ ...peer }, peer)).toEqual([])
  })

  it('«Управление» и «Передача данных» — один вид flags, даже если расходятся оба признака', () => {
    expect(connectionConfigDiffKinds({ ...peer, is_management: true }, peer)).toEqual(['flags'])
    expect(connectionConfigDiffKinds({ ...peer, is_data_transfer: false }, peer)).toEqual(['flags'])
    expect(connectionConfigDiffKinds({ ...peer, is_management: true, is_data_transfer: false }, peer)).toEqual(['flags'])
  })

  it('режим порта — отдельный вид vlan_mode; оба вида сразу — в порядке «назначение, режим»', () => {
    expect(connectionConfigDiffKinds({ ...peer, vlan_mode: 'access' }, peer)).toEqual(['vlan_mode'])
    expect(connectionConfigDiffKinds({ is_management: true, is_data_transfer: true, vlan_mode: 'access' }, peer)).toEqual(['flags', 'vlan_mode'])
  })

  it('«Все VLAN» — отдельный вид all_vlans, только когда оба порта в trunk', () => {
    expect(connectionConfigDiffKinds({ ...peer, all_vlans: true }, peer)).toEqual(['all_vlans'])
    expect(connectionConfigDiffKinds(peer, { ...peer, all_vlans: true })).toEqual(['all_vlans'])
    expect(connectionConfigDiffKinds({ ...peer, is_management: true, all_vlans: true }, peer)).toEqual(['flags', 'all_vlans'])
    expect(connectionConfigDiffKinds({ ...peer, vlan_mode: 'access', all_vlans: true }, peer)).toEqual(['vlan_mode']) // в access признака нет
  })

  it('согласован с connectionConfigDiffs: пустой тогда и только тогда, когда пуст текстовый список', () => {
    for (const mgmt of [false, true])
      for (const data of [false, true])
        for (const mode of ['access', 'trunk'] as const) {
          const own = { is_management: mgmt, is_data_transfer: data, vlan_mode: mode }
          expect(connectionConfigDiffKinds(own, peer).length === 0).toBe(connectionConfigDiffs(own, peer).length === 0)
        }
  })
})

