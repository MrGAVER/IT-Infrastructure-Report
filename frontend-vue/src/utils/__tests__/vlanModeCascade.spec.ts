import { describe, it, expect } from 'vitest'
import type { InterfaceDraftRow, InterfaceGroupDraft } from '../../api/types'
import { applyCascadeToDraft, buildEditedState, isTrivialPlan, modeLabel, vlansForMode } from '../vlanModeCascade'
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
  it('режимы сохранённых портов и групп из черновика; новые строки и группы без id пропускаются', () => {
    const rows = [row('a', { id: 'if-1', vlan_mode: 'access' }), row('b', { id: 'if-2', vlan_mode: 'trunk' }), row('новый', { vlan_mode: 'access' })]
    const groups = [group({ id: 'g1', vlan_mode: 'trunk' }), group({ id: 'g2', key: 'g2', vlan_mode: '' }), group({ id: undefined, key: 'new-1', vlan_mode: 'access' })]

    expect(buildEditedState('dev-1', rows, groups)).toEqual({ device_id: 'dev-1', ports: { 'if-1': 'access', 'if-2': 'trunk' }, groups: { g1: 'trunk', g2: '' } })
  })

  it('без устройства (создание нового) состояния нет', () => {
    expect(buildEditedState(null, [row('a', { id: 'if-1' })], [])).toBeNull()
    expect(buildEditedState(undefined, [], [])).toBeNull()
  })

  it('отражает именно текущий черновик: переключённый в форме режим попадает как есть', () => {
    expect(buildEditedState('dev-1', [row('a', { id: 'if-1', vlan_mode: 'access' })], [])?.ports).toEqual({ 'if-1': 'access' })
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

  it('порт группы по БД, выведенный из неё в черновике, всё равно получает режим как одиночный', () => {
    const rows = [row('Gi0/1', { id: 'if-1', vlan_ids: ['v10', 'v20'] })] // group_key пуст — вышел из группы без сохранения
    const plan = makePlan({
      groups: [groupChange({ id: 'g1', deferred: true, vlans_after: [vlanRef(10)], dropped_vlans: [vlanRef(20)], ports: [{ id: 'if-1', name: 'Gi0/1' }] })],
      ports: [],
    })

    const result = applyCascadeToDraft(rows, [group()], plan)

    expect(result.rows[0]).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'] })
    expect(result.changedPorts).toBe(1)
  })
})

describe('isTrivialPlan и modeLabel', () => {
  it('тривиален только план из одного порта без групп, снимаемых VLAN и изменений в форме', () => {
    expect(isTrivialPlan(makePlan())).toBe(true)
    expect(isTrivialPlan(makePlan({ groups: [groupChange()], totals: { ...makePlan().totals, groups: 1 } }))).toBe(false)
    expect(isTrivialPlan(makePlan({ totals: { ...makePlan().totals, ports: 2 } }))).toBe(false)
    expect(isTrivialPlan(makePlan({ totals: { ...makePlan().totals, dropped_vlans: 1 } }))).toBe(false)
    expect(isTrivialPlan(makePlan({ totals: { ...makePlan().totals, deferred_ports: 1 } }))).toBe(false)
  })

  it('modeLabel подписывает режим', () => {
    expect([modeLabel('access'), modeLabel('trunk')]).toEqual(['Access', 'Trunk'])
  })
})
