import { describe, expect, it } from 'vitest'
import type { InterfaceGroupDraft, ProtocolPortCatalogEntry, SubinterfaceDraftRow } from '../../api/types'
import { emptyGroup } from '../interfaceGroups'
import {
  cloneGroupForEdit,
  countSelectedVlans,
  groupSubinterfaceVlans,
  normalizeGroupSubinterfaces,
  setGroupAccessVlan,
  setGroupAllVlans,
  setGroupVlanMode,
  toggleGroupVlan,
} from '../groupDraftEdit'
import { makeVlan } from './interfaceRowFixture'

const vlans = [makeVlan('v10', 10), makeVlan('v20', 20), makeVlan('v30', 30)]
const catalog: ProtocolPortCatalogEntry[] = [
  { id: 'c22', port: 22, protocol_type: 'SSH', description: null },
  { id: 'c443', port: 443, protocol_type: 'HTTPS', description: null },
]

function group(patch: Partial<InterfaceGroupDraft> = {}): InterfaceGroupDraft {
  return { ...emptyGroup('Серверные'), key: 'g1', ...patch }
}

function sub(key: string, vlanId: string, patch: Partial<SubinterfaceDraftRow> = {}): SubinterfaceDraftRow {
  return { key, name: '', vlan_id: vlanId, is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [], ...patch }
}

describe('cloneGroupForEdit', () => {
  it('копия глубокая: правка массивов и вложенных строк копии не задевает исходную группу', () => {
    const original = group({
      vlan_ids: ['v10'],
      open_ports: [{ protocol_catalog_id: 'c22', transport_protocol: 'TCP', description: 'ssh' }],
      subinterfaces: [
        sub('s1', 'v10', {
          ips: [{ ip_address: '10.0.0.1', prefix_length: '24', purpose: '' }],
          open_ports: [{ protocol_catalog_id: 'c443', transport_protocol: 'TCP', description: '' }],
        }),
      ],
    })
    const copy = cloneGroupForEdit(original)

    copy.vlan_ids.push('v20')
    copy.open_ports[0].description = 'changed'
    copy.subinterfaces![0].ips[0].ip_address = '10.9.9.9'
    copy.subinterfaces![0].open_ports[0].description = 'changed'

    expect(original.vlan_ids).toEqual(['v10'])
    expect(original.open_ports[0].description).toBe('ssh')
    expect(original.subinterfaces![0].ips[0].ip_address).toBe('10.0.0.1')
    expect(original.subinterfaces![0].open_ports[0].description).toBe('')
    expect(copy).not.toBe(original)
  })

  it('не заданные у сохранённой группы «Все VLAN» и подинтерфейсы становятся false и []', () => {
    const legacy = { ...group(), all_vlans: undefined, subinterfaces: undefined }
    expect(cloneGroupForEdit(legacy)).toMatchObject({ all_vlans: false, subinterfaces: [] })
  })

  it('остальные поля (ключ, id, имя, IP) переносятся как есть', () => {
    const copy = cloneGroupForEdit(group({ id: 'srv-1', ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'mgmt' }], manage_open_ports: true }))
    expect(copy).toMatchObject({
      id: 'srv-1',
      key: 'g1',
      name: 'Серверные',
      ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'mgmt' }],
      manage_open_ports: true,
    })
  })
})

describe('setGroupVlanMode', () => {
  it('access оставляет не более одного VLAN и снимает «Все VLAN»', () => {
    const next = setGroupVlanMode(group({ vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], all_vlans: true }), 'access', vlans)
    expect(next).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'], all_vlans: false })
  })

  it('trunk сразу отмечает «Все VLAN»: признак и все VLAN устройства', () => {
    const next = setGroupVlanMode(group({ vlan_mode: 'access', vlan_ids: ['v20'] }), 'trunk', vlans)
    expect(next).toMatchObject({ vlan_mode: 'trunk', vlan_ids: ['v10', 'v20', 'v30'], all_vlans: true })
  })

  it('trunk у устройства без VLAN признак «Все VLAN» не ставит', () => {
    expect(setGroupVlanMode(group(), 'trunk', [])).toMatchObject({ vlan_mode: 'trunk', vlan_ids: [], all_vlans: false })
  })

  it('«Не задавать» стирает VLAN и признак', () => {
    const next = setGroupVlanMode(group({ vlan_mode: 'trunk', vlan_ids: ['v10'], all_vlans: true }), '', vlans)
    expect(next).toMatchObject({ vlan_mode: '', vlan_ids: [], all_vlans: false })
  })

  it('исходный черновик не меняется', () => {
    const original = group({ vlan_mode: 'access', vlan_ids: ['v10'] })
    setGroupVlanMode(original, 'trunk', vlans)
    expect(original).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'], all_vlans: false })
  })
})

describe('setGroupAccessVlan', () => {
  it('записывает единственный VLAN, пустая строка — «VLAN не выбран»; «Все VLAN» снимается', () => {
    const base = group({ vlan_mode: 'access', all_vlans: true })
    expect(setGroupAccessVlan(base, 'v20')).toMatchObject({ vlan_ids: ['v20'], all_vlans: false })
    expect(setGroupAccessVlan(base, '')).toMatchObject({ vlan_ids: [], all_vlans: false })
  })
})

describe('toggleGroupVlan', () => {
  it('добавляет и убирает VLAN, не дублируя уже выбранный', () => {
    const base = group({ vlan_mode: 'trunk', vlan_ids: ['v10'] })
    expect(toggleGroupVlan(base, 'v20', true).vlan_ids).toEqual(['v10', 'v20'])
    expect(toggleGroupVlan(base, 'v10', true).vlan_ids).toEqual(['v10'])
    expect(toggleGroupVlan(base, 'v10', false).vlan_ids).toEqual([])
  })

  it('ручной выбор снимает «Все VLAN» — даже если в итоге выбраны все VLAN устройства', () => {
    const base = group({ vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], all_vlans: true })
    expect(toggleGroupVlan(base, 'v30', true)).toMatchObject({ vlan_ids: ['v10', 'v20', 'v30'], all_vlans: false })
  })
})

describe('setGroupAllVlans', () => {
  it('«Все VLAN» включён: признак и все VLAN устройства; выключен: признак снят и набор пуст', () => {
    const base = group({ vlan_mode: 'trunk', vlan_ids: ['v10'] })
    expect(setGroupAllVlans(base, true, vlans)).toMatchObject({ all_vlans: true, vlan_ids: ['v10', 'v20', 'v30'] })
    expect(setGroupAllVlans(group({ vlan_mode: 'trunk', vlan_ids: ['v10', 'v20', 'v30'], all_vlans: true }), false, vlans)).toMatchObject({
      all_vlans: false,
      vlan_ids: [],
    })
  })
})

describe('countSelectedVlans', () => {
  it('считает только VLAN устройства: чужие id не учитываются', () => {
    expect(countSelectedVlans(['v10', 'v30', 'gone'], vlans)).toBe(2)
    expect(countSelectedVlans([], vlans)).toBe(0)
    expect(countSelectedVlans(['v10'], [])).toBe(0)
  })
})

describe('groupSubinterfaceVlans', () => {
  it('без режима порта подинтерфейсы не задаются — список пуст, даже если VLAN выбраны', () => {
    expect(groupSubinterfaceVlans(group({ vlan_mode: '', vlan_ids: ['v10'] }), vlans)).toEqual([])
  })

  it('access и trunk без «Все VLAN» — только выбранные VLAN группы', () => {
    expect(groupSubinterfaceVlans(group({ vlan_mode: 'access', vlan_ids: ['v20'] }), vlans).map((v) => v.id)).toEqual(['v20'])
    expect(groupSubinterfaceVlans(group({ vlan_mode: 'trunk', vlan_ids: ['v10', 'v30'] }), vlans).map((v) => v.id)).toEqual(['v10', 'v30'])
  })

  it('trunk с «Все VLAN» — все VLAN устройства, а не набор vlan_ids', () => {
    const result = groupSubinterfaceVlans(group({ vlan_mode: 'trunk', vlan_ids: ['v10'], all_vlans: true }), vlans)
    expect(result.map((v) => v.id)).toEqual(['v10', 'v20', 'v30'])
  })

  it('признак «Все VLAN» без trunk (access) ничего не расширяет', () => {
    expect(groupSubinterfaceVlans(group({ vlan_mode: 'access', vlan_ids: ['v10'], all_vlans: true }), vlans).map((v) => v.id)).toEqual(['v10'])
  })
})

describe('normalizeGroupSubinterfaces', () => {
  it('шаблоны идут по возрастанию номера VLAN, шаблон на неизвестный VLAN — в конце', () => {
    const rows = [sub('a', 'v30'), sub('b', 'gone'), sub('c', 'v10'), sub('d', 'v20')]
    expect(normalizeGroupSubinterfaces(rows, vlans, catalog).map((s) => s.key)).toEqual(['c', 'd', 'a', 'b'])
  })

  it('открытые порты каждого шаблона — по возрастанию номера порта', () => {
    const rows = [
      sub('a', 'v10', {
        open_ports: [
          { protocol_catalog_id: 'c443', transport_protocol: 'TCP', description: '' },
          { protocol_catalog_id: 'c22', transport_protocol: 'TCP', description: '' },
        ],
      }),
    ]
    expect(normalizeGroupSubinterfaces(rows, vlans, catalog)[0].open_ports.map((p) => p.protocol_catalog_id)).toEqual(['c22', 'c443'])
  })

  it('исходный массив и его порядок не меняются', () => {
    const rows = [sub('a', 'v30'), sub('b', 'v10')]
    normalizeGroupSubinterfaces(rows, vlans, catalog)
    expect(rows.map((s) => s.key)).toEqual(['a', 'b'])
  })
})
