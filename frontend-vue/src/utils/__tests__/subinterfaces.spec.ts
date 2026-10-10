import { describe, it, expect } from 'vitest'
import {
  emptySubinterface,
  groupSubinterfacesByParent,
  isAutoSubinterfaceName,
  moveStaleMessage,
  moveStaleSubinterfaces,
  reassignSubinterfaceVlan,
  renameSubinterfacesForPort,
  staleSubinterfaces,
  stripSubinterfaceIds,
  subinterfaceVlanRemovalMessage,
  subinterfacesPayload,
  suggestSubinterfaceName,
  toSubinterfaceDraftRow,
  validateSubinterfaceRows,
} from '../subinterfaces'
import type { DeviceSubinterface, InterfaceDraftRow, ProtocolPortCatalogEntry, SubinterfaceDraftRow, VLANDefinition } from '../../api/types'

const vlan10: VLANDefinition = { id: 'v-10', vlan_id: 10, name: 'Серверы', description: '', domain_id: null, domain_name: '', devices: [] }
const vlan20: VLANDefinition = { id: 'v-20', vlan_id: 20, name: 'Гости', description: '', domain_id: null, domain_name: '', devices: [] }

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

describe('validateSubinterfaceRows: VLAN, недоступный устройству', () => {
  it('подинтерфейс на VLAN вне допустимых блокирует сохранение понятным текстом', () => {
    const rows = [port('Gi0/0', [sub({ name: 'Gi0/0.10', vlan_id: 'v-10' })])]
    expect(validateSubinterfaceRows(rows, [], new Set(['v-20']))).toMatch(/«Gi0\/0\.10» не назначен устройству/)
  })

  it('допустимый VLAN проходит; без списка допустимых проверка пропускается (серверная остаётся)', () => {
    const rows = [port('Gi0/0', [sub({ name: 'Gi0/0.10', vlan_id: 'v-10' })])]
    expect(validateSubinterfaceRows(rows, [], new Set(['v-10']))).toBeNull()
    expect(validateSubinterfaceRows(rows)).toBeNull()
  })

  it('«VLAN не выбран» сообщается раньше, чем «VLAN недоступен»', () => {
    const rows = [port('Gi0/0', [sub({ name: 'x', vlan_id: '' })])]
    expect(validateSubinterfaceRows(rows, [], new Set())).toMatch(/не выбран VLAN/)
  })
})

describe('isAutoSubinterfaceName', () => {
  it('автоимя — пустое либо «<порт>.<VLAN>»; введённое вручную — нет', () => {
    expect(isAutoSubinterfaceName('', 'Gi0/0', 10)).toBe(true)
    expect(isAutoSubinterfaceName('   ', 'Gi0/0', 10)).toBe(true)
    expect(isAutoSubinterfaceName('Gi0/0.10', 'Gi0/0', 10)).toBe(true)
    expect(isAutoSubinterfaceName('Gi0/0.20', 'Gi0/0', 10)).toBe(false)
    expect(isAutoSubinterfaceName('wan-uplink', 'Gi0/0', 10)).toBe(false)
  })
})

describe('renameSubinterfacesForPort', () => {
  const vlans = [vlan10, vlan20]

  it('автоимена следуют за новым именем порта, вручную заданные остаются; остальные поля и id не теряются', () => {
    const auto = sub({ id: 'sub-1', key: 'sub-1', name: 'Gi0/0.10', vlan_id: 'v-10', is_data_transfer: true })
    const manual = sub({ name: 'wan-uplink', vlan_id: 'v-20' })
    const result = renameSubinterfacesForPort([auto, manual], 'Gi0/0', 'Gi0/1', vlans)

    expect(result.map((s) => s.name)).toEqual(['Gi0/1.10', 'wan-uplink'])
    expect(result[0]).toMatchObject({ id: 'sub-1', key: 'sub-1', vlan_id: 'v-10', is_data_transfer: true })
    expect(auto.name).toBe('Gi0/0.10') // исходные строки не мутируются
  })

  it('подинтерфейс с автоимененем от ДРУГОГО VLAN (имя от прежнего порта, но с чужим номером) считается ручным', () => {
    const odd = sub({ name: 'Gi0/0.99', vlan_id: 'v-10' })
    expect(renameSubinterfacesForPort([odd], 'Gi0/0', 'Gi0/1', vlans)[0].name).toBe('Gi0/0.99')
  })

  it('пустое имя подинтерфейса заполняется именем по новому порту', () => {
    const empty = sub({ name: '', vlan_id: 'v-20' })
    expect(renameSubinterfacesForPort([empty], '', 'Gi0/1', vlans)[0].name).toBe('Gi0/1.20')
  })

  it('имя порта набирается по буквам: автоимя не теряется на каждом шаге, в том числе через пустое имя порта', () => {
    let subs = [sub({ name: 'Gi0/0.10', vlan_id: 'v-10' })]
    let previous = 'Gi0/0'
    for (const typed of ['', 'e', 'et', 'eth', 'eth1']) {
      subs = renameSubinterfacesForPort(subs, previous, typed, vlans)
      previous = typed
    }
    expect(subs[0].name).toBe('eth1.10')
  })

  it('подинтерфейс на недоступном VLAN не трогаем; нечего менять (то же имя порта, пробелы) — возвращается тот же массив', () => {
    const stale = sub({ name: 'Gi0/0.10', vlan_id: 'v-gone' })
    const subs = [stale]
    expect(renameSubinterfacesForPort(subs, 'Gi0/0', 'Gi0/1', vlans)).toBe(subs)
    expect(renameSubinterfacesForPort([sub({ name: 'Gi0/0.10' })], 'Gi0/0', ' Gi0/0 ', vlans)[0].name).toBe('Gi0/0.10')
    const same = [sub({ name: 'Gi0/0.10' })]
    expect(renameSubinterfacesForPort(same, 'Gi0/0', 'Gi0/0', vlans)).toBe(same)
  })
})

describe('reassignSubinterfaceVlan', () => {
  const vlan30: VLANDefinition = { id: 'v-30', vlan_id: 30, name: 'Резерв', description: '', domain_id: null, domain_name: '', devices: [] }

  it('автоимя («<порт>.<прежний VLAN>») пересчитывается под новый VLAN, прочие поля остаются', () => {
    const source = sub({ id: 'sub-1', name: 'Gi0/0.30', vlan_id: 'v-30', description: 'Резерв', is_data_transfer: true })
    const result = reassignSubinterfaceVlan(source, 'Gi0/0', vlan30, vlan10)

    expect(result).toMatchObject({ id: 'sub-1', vlan_id: 'v-10', name: 'Gi0/0.10', description: 'Резерв', is_data_transfer: true })
    expect(source.vlan_id).toBe('v-30') // исходная строка не мутируется
  })

  it('имя, введённое вручную, остаётся; пустое имя заполняется; без известного прежнего VLAN автоимя не угадывается', () => {
    expect(reassignSubinterfaceVlan(sub({ name: 'wan-uplink', vlan_id: 'v-30' }), 'Gi0/0', vlan30, vlan10).name).toBe('wan-uplink')
    expect(reassignSubinterfaceVlan(sub({ name: '', vlan_id: 'v-30' }), 'Gi0/0', undefined, vlan10).name).toBe('Gi0/0.10')
    expect(reassignSubinterfaceVlan(sub({ name: 'Gi0/0.30', vlan_id: 'v-30' }), 'Gi0/0', undefined, vlan10).name).toBe('Gi0/0.30')
  })
})

describe('moveStaleSubinterfaces', () => {
  const vlan30: VLANDefinition = { id: 'v-30', vlan_id: 30, name: 'Резерв', description: '', domain_id: null, domain_name: '', devices: [] }
  const vlan40: VLANDefinition = { id: 'v-40', vlan_id: 40, name: 'Архив', description: '', domain_id: null, domain_name: '', devices: [] }
  const allowed = new Set(['v-10', 'v-20'])
  const known = [vlan10, vlan20, vlan30, vlan40]
  const staleOn = (vlan: VLANDefinition, parent: string, patch: Partial<SubinterfaceDraftRow> = {}) => sub({ name: `${parent}.${vlan.vlan_id}`, vlan_id: vlan.id, ...patch })

  it('переносит подинтерфейсы всех портов с недоступных VLAN на выбранный, пересчитывая автоимена; остальное не трогает', () => {
    const rows = [
      port('Gi0/0', [staleOn(vlan30, 'Gi0/0'), sub({ name: 'Gi0/0.20', vlan_id: 'v-20' })]),
      port('Gi0/1', [staleOn(vlan40, 'Gi0/1', { name: 'wan-uplink' })]),
      port('Gi0/2'),
    ]
    const result = moveStaleSubinterfaces(rows, vlan10, allowed, known)

    expect(result.rows[0].subinterfaces!.map((s) => [s.name, s.vlan_id])).toEqual([['Gi0/0.10', 'v-10'], ['Gi0/0.20', 'v-20']])
    expect(result.rows[1].subinterfaces![0]).toMatchObject({ name: 'wan-uplink', vlan_id: 'v-10' })
    expect(result.rows[2]).toBe(rows[2]) // порт без подинтерфейсов — тот же объект
    expect(result.moved).toEqual(['Gi0/0.10', 'wan-uplink'])
    expect(result.skipped).toEqual([])
    expect(rows[0].subinterfaces![0].vlan_id).toBe('v-30') // исходные строки не мутируются
  })

  it('если на порту целевой VLAN уже занят — подинтерфейс остаётся и попадает в skipped (на порту VLAN один раз)', () => {
    const rows = [
      port('Gi0/0', [sub({ name: 'Gi0/0.10', vlan_id: 'v-10' }), staleOn(vlan30, 'Gi0/0')]), // v-10 уже занят
      port('Gi0/1', [staleOn(vlan30, 'Gi0/1'), staleOn(vlan40, 'Gi0/1')]), // только первый получит v-10
    ]
    const result = moveStaleSubinterfaces(rows, vlan10, allowed, known)

    expect(result.rows[0].subinterfaces![1]).toMatchObject({ name: 'Gi0/0.30', vlan_id: 'v-30' })
    expect(result.rows[1].subinterfaces!.map((s) => s.vlan_id)).toEqual(['v-10', 'v-40'])
    expect(result.moved).toEqual(['Gi0/1.10'])
    expect(result.skipped).toEqual(['Gi0/0.30', 'Gi0/1.40'])
    // итог проходит проверку формы: VLAN на порту не повторяется
    expect(validateSubinterfaceRows(result.rows, [], new Set(['v-10', 'v-20', 'v-30', 'v-40']))).toBeNull()
  })

  it('переносить нечего — возвращается тот же массив строк', () => {
    const rows = [port('Gi0/0', [sub({ name: 'Gi0/0.10', vlan_id: 'v-10' })]), port('Gi0/1')]
    const result = moveStaleSubinterfaces(rows, vlan20, allowed, known)

    expect(result.rows).toBe(rows)
    expect(result.moved).toEqual([])
    expect(result.skipped).toEqual([])
  })

  it('все недоступные подинтерфейсы пропущены — rows тот же, но skipped заполнен', () => {
    const rows = [port('Gi0/0', [sub({ name: 'Gi0/0.10', vlan_id: 'v-10' }), staleOn(vlan30, 'Gi0/0')])]
    const result = moveStaleSubinterfaces(rows, vlan10, allowed, known)

    expect(result.rows).toBe(rows)
    expect(result.skipped).toEqual(['Gi0/0.30'])
  })
})

describe('moveStaleMessage', () => {
  it('успех, частичный успех (предупреждение с перечнем), только пропуски и «нечего переносить»', () => {
    expect(moveStaleMessage({ moved: ['a', 'b'], skipped: [] }, vlan10)).toEqual({ text: 'Перенесено подинтерфейсов: 2 — на VLAN 10 — Серверы.', type: 'success' })

    const partial = moveStaleMessage({ moved: ['a'], skipped: ['Gi0/0.30'] }, vlan10)!
    expect(partial.type).toBe('warning')
    expect(partial.text).toContain('Перенесено подинтерфейсов: 1 — на VLAN 10 — Серверы.')
    expect(partial.text).toContain('Не перенесены (на их порту этот VLAN уже занят другим подинтерфейсом): «Gi0/0.30»')

    const none = moveStaleMessage({ moved: [], skipped: ['Gi0/0.30'] }, vlan10)!
    expect(none.type).toBe('warning')
    expect(none.text).not.toContain('Перенесено')

    expect(moveStaleMessage({ moved: [], skipped: [] }, vlan10)).toBeNull()
  })
})

describe('staleSubinterfaces / subinterfaceVlanRemovalMessage', () => {
  const vlans = [vlan10, vlan20]

  it('staleSubinterfaces: подинтерфейсы вне допустимых VLAN; undefined и пустой VLAN — не «устаревшие»', () => {
    const subs = [sub({ name: 'a', vlan_id: 'v-10' }), sub({ name: 'b', vlan_id: 'v-20' }), sub({ name: 'c', vlan_id: '' })]
    expect(staleSubinterfaces(subs, new Set(['v-10'])).map((s) => s.name)).toEqual(['b'])
    expect(staleSubinterfaces(undefined, new Set())).toEqual([])
  })

  it('сообщение называет снятый VLAN и подинтерфейсы на нём; нетронутые VLAN и порты без подинтерфейсов не упоминаются', () => {
    const rows = [
      port('Gi0/0', [sub({ name: 'Gi0/0.10', vlan_id: 'v-10' }), sub({ name: 'Gi0/0.20', vlan_id: 'v-20' })]),
      port('Gi0/1'),
      port('Gi0/2', [sub({ name: 'Gi0/2.20', vlan_id: 'v-20' })]),
    ]
    expect(subinterfaceVlanRemovalMessage(rows, vlans, [vlan10])).toBe(
      'Сняты VLAN (20 — Гости), но на них остались подинтерфейсы: «Gi0/0.20», «Gi0/2.20». Выберите другой VLAN или удалите их — иначе сохранить не получится.',
    )
  })

  it('null, если снятых VLAN нет или подинтерфейсов на них нет', () => {
    const rows = [port('Gi0/0', [sub({ name: 'Gi0/0.10', vlan_id: 'v-10' })])]
    expect(subinterfaceVlanRemovalMessage(rows, vlans, vlans)).toBeNull() // ничего не снято
    expect(subinterfaceVlanRemovalMessage(rows, vlans, [vlan10])).toBeNull() // снят v-20, на нём ничего нет
    expect(subinterfaceVlanRemovalMessage([port('Gi0/0')], vlans, [])).toBeNull()
  })

  it('уже «устаревший» подинтерфейс (VLAN не был в прежних опциях) повторно не упоминается', () => {
    const rows = [port('Gi0/0', [sub({ name: 'Gi0/0.99', vlan_id: 'v-gone' })])]
    expect(subinterfaceVlanRemovalMessage(rows, vlans, [vlan10])).toBeNull()
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
