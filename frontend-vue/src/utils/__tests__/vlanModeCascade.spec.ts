import { describe, it, expect } from 'vitest'
import type { InterfaceDraftRow, InterfaceGroupDraft } from '../../api/types'
import { applyCascadeToDraft, buildEditedState, isFormOnlyPlan, isTrivialPlan, modeLabel, vlansForMode } from '../vlanModeCascade'
import { groupChange, makePlan, portChange, vlanRef } from './cascadePlanFixture'

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
    vlan_mode: 'trunk',
    ips: [],
    open_ports: [],
    ...patch,
  }
}

function group(patch: Partial<InterfaceGroupDraft> = {}): InterfaceGroupDraft {
  return { id: 'g1', key: 'g1', name: 'Серверные', vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], ip_address: '', prefix_length: '', ip_purpose: '', manage_open_ports: false, open_ports: [], ...patch }
}

describe('buildEditedState', () => {
  it('режим, группа, VLAN и имя сохранённых портов и ВСЕ группы (в т.ч. новые — по временному ключу) из черновика', () => {
    const rows = [
      row('a', { id: 'if-1', vlan_mode: 'access', vlan_ids: ['v10'], group_key: 'g1' }),
      row('b', { id: 'if-2', vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'] }),
      row('в новой группе', { id: 'if-3', group_key: 'new-1' }),
      row('новая строка', { vlan_mode: 'access' }),
    ]
    const groups = [group({ id: 'g1', vlan_mode: 'trunk' }), group({ id: 'g2', key: 'g2', vlan_mode: '', vlan_ids: [] }), group({ id: undefined, key: 'new-1', name: 'Новая', vlan_mode: 'access', vlan_ids: ['v10'] })]

    expect(buildEditedState('dev-1', rows, groups)).toEqual({
      device_id: 'dev-1',
      ports: {
        'if-1': { name: 'a', mode: 'access', group: 'g1', vlan_ids: ['v10'] },
        'if-2': { name: 'b', mode: 'trunk', group: null, vlan_ids: ['v10', 'v20'] },
        'if-3': { name: 'в новой группе', mode: 'trunk', group: 'new-1', vlan_ids: [] },
      },
      groups: {
        g1: { name: 'Серверные', mode: 'trunk', vlan_ids: ['v10', 'v20'] },
        g2: { name: 'Серверные', mode: '', vlan_ids: [] },
        'new-1': { name: 'Новая', mode: 'access', vlan_ids: ['v10'] },
      },
    })
  })

  it('без устройства (создание нового) состояния нет', () => {
    expect(buildEditedState(null, [row('a', { id: 'if-1' })], [])).toBeNull()
    expect(buildEditedState(undefined, [], [])).toBeNull()
  })

  it('отражает именно текущий черновик: переключённый в форме режим и перенесённый в другую группу порт попадают как есть', () => {
    const state = buildEditedState('dev-1', [row('a', { id: 'if-1', vlan_mode: 'access', group_key: '' })], [])
    expect(state?.ports['if-1']).toMatchObject({ mode: 'access', group: null })
  })

  it('копирует списки VLAN: дальнейшие правки черновика не меняют уже собранный снимок', () => {
    const rows = [row('a', { id: 'if-1', vlan_ids: ['v10'] })]
    const state = buildEditedState('dev-1', rows, [])!

    rows[0].vlan_ids.push('v20')

    expect(state.ports['if-1'].vlan_ids).toEqual(['v10'])
  })
})

describe('vlansForMode', () => {
  it('trunk и access с одним VLAN не меняют список', () => {
    expect(vlansForMode(['v10', 'v20'], 'trunk', ['v10'])).toEqual(['v10', 'v20'])
    expect(vlansForMode(['v20'], 'access', ['v10'])).toEqual(['v20'])
    expect(vlansForMode([], 'access', [])).toEqual([])
  })

  it('access с несколькими VLAN оставляет тот, что выбрал сервер (наименьший номер), а не первый в списке', () => {
    expect(vlansForMode(['v20', 'v10'], 'access', ['v10'])).toEqual(['v10'])
  })

  it('если выбранного сервером VLAN в черновике нет — первый из имеющихся, как у переключателя режима в форме', () => {
    expect(vlansForMode(['v30', 'v20'], 'access', ['v10'])).toEqual(['v30'])
  })
})

describe('applyCascadeToDraft', () => {
  it('группа редактируемого устройства: режим и VLAN группы, затем значения в её портах черновика', () => {
    const rows = [row('Gi0/1', { id: 'if-1', group_key: 'g1', vlan_ids: ['v10', 'v20'] }), row('Gi0/2', { id: 'if-3', group_key: 'g1', vlan_ids: ['v10', 'v20'] }), row('Gi0/9', { id: 'if-9', vlan_ids: ['v10', 'v20'] })]
    const plan = makePlan({
      groups: [groupChange({ id: 'g1', deferred: true, vlans_after: [vlanRef(10)], dropped_vlans: [vlanRef(20)], ports: [{ id: 'if-1', name: 'Gi0/1' }, { id: 'if-3', name: 'Gi0/2' }] })],
      ports: [],
    })

    const result = applyCascadeToDraft(rows, [group()], plan)

    expect(result.groups[0]).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'] })
    expect(result.rows.map((r) => [r.vlan_mode, r.vlan_ids])).toEqual([
      ['access', ['v10']],
      ['access', ['v10']],
      ['trunk', ['v10', 'v20']], // порт вне группы не затронут
    ])
    expect(result.changedPorts).toBe(2)
  })

  it('одиночный порт редактируемого устройства: режим и VLAN по правилу access', () => {
    const rows = [row('Gi0/1', { id: 'if-1', vlan_ids: ['v20', 'v10'] })]
    const plan = makePlan({ ports: [portChange({ id: 'if-1', deferred: true, vlans_after: [vlanRef(10)], dropped_vlans: [vlanRef(20)] })] })

    const result = applyCascadeToDraft(rows, [], plan)

    expect(result.rows[0]).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'] })
    expect(result.changedPorts).toBe(1)
  })

  it('trunk: VLAN порта и группы остаются как есть, «все VLAN» не добавляются', () => {
    const rows = [row('Gi0/1', { id: 'if-1', group_key: 'g1', vlan_mode: 'access', vlan_ids: ['v10'] })]
    const plan = makePlan({ target_mode: 'trunk', groups: [groupChange({ id: 'g1', deferred: true, vlans_after: [vlanRef(10)], ports: [{ id: 'if-1', name: 'Gi0/1' }] })], ports: [] })

    const result = applyCascadeToDraft(rows, [group({ vlan_mode: 'access', vlan_ids: ['v10'] })], plan)

    expect(result.groups[0]).toMatchObject({ vlan_mode: 'trunk', vlan_ids: ['v10'] })
    expect(result.rows[0]).toMatchObject({ vlan_mode: 'trunk', vlan_ids: ['v10'] })
  })

  it('изменения других устройств (не deferred) в черновик не попадают', () => {
    const rows = [row('Gi0/1', { id: 'if-1' })]
    const plan = makePlan({ groups: [groupChange({ id: 'g1', deferred: false })], ports: [portChange({ id: 'if-1', deferred: false })] })

    const result = applyCascadeToDraft(rows, [group()], plan)

    expect(result).toMatchObject({ rows, groups: [group()], changedPorts: 0 })
  })

  it('порт или группа, которых нет в черновике (новая строка без id, удалённая группа), пропускаются без ошибки', () => {
    const rows = [row('новый')]
    const plan = makePlan({ groups: [groupChange({ id: 'g-gone', deferred: true })], ports: [portChange({ id: 'if-gone', deferred: true })] })

    const result = applyCascadeToDraft(rows, [group()], plan)

    expect(result.rows).toEqual(rows)
    expect(result.changedPorts).toBe(0)
  })

  it('новая (несохранённая) группа формы: группа находится по ключу, строки без id тоже получают режим', () => {
    const rows = [row('Gi0/1', { id: 'if-1', group_key: 'new-1', vlan_ids: ['v10', 'v20'] }), row('новая', { group_key: 'new-1', vlan_ids: ['v10', 'v20'] })]
    const draftGroup = group({ id: undefined, key: 'new-1', name: 'Новая' })
    const plan = makePlan({
      groups: [groupChange({ id: 'new-1', deferred: true, vlans_after: [vlanRef(10)], dropped_vlans: [vlanRef(20)], ports: [{ id: 'if-1', name: 'Gi0/1' }] })],
      ports: [],
    })

    const result = applyCascadeToDraft(rows, [draftGroup], plan)

    expect(result.groups[0]).toMatchObject({ key: 'new-1', vlan_mode: 'access', vlan_ids: ['v10'] })
    expect(result.rows.map((r) => [r.vlan_mode, r.vlan_ids])).toEqual([['access', ['v10']], ['access', ['v10']]])
    expect(result.changedPorts).toBe(1) // считаются только сохранённые порты (с id)
  })

  it('порт, выведенный из группы в черновике, режим группы не получает: состав группы — по черновику', () => {
    const rows = [row('Gi0/1', { id: 'if-1', vlan_ids: ['v10', 'v20'] })] // group_key пуст — вышел из группы без сохранения
    const plan = makePlan({
      groups: [groupChange({ id: 'g1', deferred: true, vlans_after: [vlanRef(10)], dropped_vlans: [vlanRef(20)], ports: [] })],
      ports: [],
    })

    const result = applyCascadeToDraft(rows, [group()], plan)

    expect(result.groups[0]).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'] })
    expect(result.rows[0]).toMatchObject({ vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'] }) // не тронут
    expect(result.changedPorts).toBe(0)
  })
})

describe('isTrivialPlan, isFormOnlyPlan и modeLabel', () => {
  it('тривиален только план из одного порта без групп и снимаемых VLAN', () => {
    expect(isTrivialPlan(makePlan())).toBe(true)
    expect(isTrivialPlan(makePlan({ groups: [groupChange()], totals: { ...makePlan().totals, groups: 1 } }))).toBe(false)
    expect(isTrivialPlan(makePlan({ totals: { ...makePlan().totals, ports: 2 } }))).toBe(false)
    expect(isTrivialPlan(makePlan({ totals: { ...makePlan().totals, dropped_vlans: 1 } }))).toBe(false)
  })

  it('«только форма» — тривиальный план, в котором на других устройствах ничего не пишется', () => {
    const own = makePlan({ ports: [portChange({ deferred: true })], totals: { ...makePlan().totals, deferred_ports: 1, immediate_ports: 0, immediate_devices: 0 } })
    expect(isFormOnlyPlan(own)).toBe(true)
    expect(isFormOnlyPlan(makePlan())).toBe(false) // единственный порт на другом устройстве
    expect(isFormOnlyPlan(makePlan({ totals: { ...makePlan().totals, ports: 2, deferred_ports: 1, immediate_ports: 1 } }))).toBe(false)
  })

  it('modeLabel подписывает режим', () => {
    expect([modeLabel('access'), modeLabel('trunk')]).toEqual(['Access', 'Trunk'])
  })
})
