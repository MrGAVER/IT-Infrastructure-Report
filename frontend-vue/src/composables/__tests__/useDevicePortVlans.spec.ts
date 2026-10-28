import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, toRaw } from 'vue'
import type { DeviceVlanDraftRow } from '../../api/types'
import { emptyGroup } from '../../utils/interfaceGroups'
import { makeRow } from '../../utils/__tests__/interfaceRowFixture'
import { makeDraft, setVlanDefinitions, setupStores, vlanDef } from './deviceFormTestkit'
import { useDevicePortVlans } from '../useDevicePortVlans'
import { useToast } from '../useToast'

const dvRow = (vlan_id: string): DeviceVlanDraftRow => ({ vlan_id, ip_address: '', prefix_length: '', is_management: false, description: '' })

let stores: ReturnType<typeof setupStores>

function setup() {
  const draft = makeDraft()
  const revealStaleSubinterfaces = vi.fn()
  const ports = useDevicePortVlans(draft, { revealStaleSubinterfaces })
  return { draft, ports, revealStaleSubinterfaces }
}

beforeEach(() => {
  stores = setupStores()
  setVlanDefinitions(stores.vlans, [vlanDef('v10', 10), vlanDef('v20', 20), vlanDef('v30', 30)])
  useToast().toasts.splice(0)
})

describe('portVlanOptions', () => {
  it('допустимые VLAN порта = VLAN типа устройства ∪ VLAN из блока «VLAN устройства» (даже несохранённого), по номеру', () => {
    const { draft, ports } = setup()
    expect(ports.portVlanOptions.value).toEqual([])
    draft.deviceTypeVlanIds.value = new Set(['v30'])
    draft.deviceVlans.value = [dvRow('v10'), dvRow('')]
    expect(ports.portVlanOptions.value.map((v) => v.id)).toEqual(['v10', 'v30'])
  })

  it('VLAN, которых нет в справочнике, пропускаются', () => {
    const { draft, ports } = setup()
    draft.deviceTypeVlanIds.value = new Set(['v10', 'gone'])
    expect(ports.portVlanOptions.value.map((v) => v.id)).toEqual(['v10'])
  })
})

describe('согласование портов при смене допустимых VLAN', () => {
  async function withOptions(ids: string[]) {
    const ctx = setup()
    ctx.draft.deviceTypeVlanIds.value = new Set(ids)
    await nextTick()
    return ctx
  }

  it('первое заполнение опций порты не трогает: VLAN, назначенные вне каталога, не стираются', async () => {
    const { draft } = setup()
    const rows = [makeRow({ id: 'if-1', vlan_mode: 'trunk', vlan_ids: ['legacy'] })]
    draft.interfaces.value = rows
    draft.deviceTypeVlanIds.value = new Set(['v10'])
    await nextTick()
    expect(toRaw(draft.interfaces.value)).toBe(rows)
    expect(draft.interfaces.value[0].vlan_ids).toEqual(['legacy'])
  })

  it('VLAN, переставший быть допустимым, убирается из порта; нетронутые порты остаются теми же объектами', async () => {
    const { draft } = await withOptions(['v10', 'v20'])
    const untouched = makeRow({ id: 'if-2', vlan_mode: 'trunk', vlan_ids: ['v20'] })
    draft.interfaces.value = [makeRow({ id: 'if-1', vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'] }), untouched]

    draft.deviceTypeVlanIds.value = new Set(['v20'])
    await nextTick()

    expect(draft.interfaces.value[0].vlan_ids).toEqual(['v20'])
    expect(toRaw(draft.interfaces.value[1])).toBe(untouched)
  })

  it('«Все VLAN» следует за набором допустимых: новый VLAN подхватывается, снятый теряется', async () => {
    const { draft } = await withOptions(['v10', 'v20'])
    draft.interfaces.value = [makeRow({ id: 'if-1', vlan_mode: 'trunk', all_vlans: true, vlan_ids: ['v10', 'v20'] })]

    draft.deviceTypeVlanIds.value = new Set(['v10', 'v20', 'v30'])
    await nextTick()
    expect(draft.interfaces.value[0].vlan_ids.sort()).toEqual(['v10', 'v20', 'v30'])

    draft.deviceTypeVlanIds.value = new Set(['v10'])
    await nextTick()
    expect(draft.interfaces.value[0].vlan_ids).toEqual(['v10'])
  })

  it('вручную выбранный полный набор новых VLAN не получает', async () => {
    const { draft } = await withOptions(['v10', 'v20'])
    draft.interfaces.value = [makeRow({ id: 'if-1', vlan_mode: 'trunk', all_vlans: false, vlan_ids: ['v10', 'v20'] })]
    draft.deviceTypeVlanIds.value = new Set(['v10', 'v20', 'v30'])
    await nextTick()
    expect(draft.interfaces.value[0].vlan_ids).toEqual(['v10', 'v20'])
  })

  it('группы портов согласуются так же, а об убранных VLAN группы сообщается предупреждением', async () => {
    const { draft } = await withOptions(['v10', 'v20'])
    draft.interfaceGroups.value = [{ ...emptyGroup('Uplinks'), key: 'g1', vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'] }]

    draft.deviceTypeVlanIds.value = new Set(['v20'])
    await nextTick()

    expect(draft.interfaceGroups.value[0].vlan_ids).toEqual(['v20'])
    const toasts = useToast().toasts
    expect(toasts).toHaveLength(1)
    expect(toasts[0].type).toBe('warning')
    expect(toasts[0].message).toContain('Uplinks')
  })

  it('группа без потерь VLAN предупреждения не вызывает и остаётся тем же объектом', async () => {
    const { draft } = await withOptions(['v10', 'v20'])
    const groups = [{ ...emptyGroup('Uplinks'), key: 'g1', vlan_mode: 'trunk' as const, vlan_ids: ['v20'] }]
    draft.interfaceGroups.value = groups
    draft.deviceTypeVlanIds.value = new Set(['v20', 'v30'])
    await nextTick()
    expect(toRaw(draft.interfaceGroups.value)).toBe(groups)
    expect(useToast().toasts).toHaveLength(0)
  })

  it('подинтерфейс на снятом VLAN остаётся, но появляется предупреждение с кнопкой «Показать»', async () => {
    const { draft, revealStaleSubinterfaces } = await withOptions(['v10', 'v20'])
    const sub = { key: 's1', name: 'Gi0/1.20', vlan_id: 'v20', is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [] }
    draft.interfaces.value = [makeRow({ id: 'if-1', vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], subinterfaces: [sub] })]

    draft.deviceTypeVlanIds.value = new Set(['v10'])
    await nextTick()

    expect(draft.interfaces.value[0].subinterfaces).toEqual([sub])
    const toast = useToast().toasts.find((t) => t.type === 'warning')
    expect(toast?.action?.label).toBe('Показать')
    expect(revealStaleSubinterfaces).not.toHaveBeenCalled()
    toast!.action!.run()
    expect(revealStaleSubinterfaces).toHaveBeenCalledTimes(1)
  })

  it('смена блока «VLAN устройства» тоже меняет опции и тянет за собой порты', async () => {
    const { draft } = await withOptions([])
    draft.deviceVlans.value = [dvRow('v10'), dvRow('v20')]
    await nextTick()
    draft.interfaces.value = [makeRow({ id: 'if-1', vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'] })]
    draft.deviceVlans.value = [dvRow('v20')]
    await nextTick()
    expect(draft.interfaces.value[0].vlan_ids).toEqual(['v20'])
  })
})
