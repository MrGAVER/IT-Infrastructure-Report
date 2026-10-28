import { beforeEach, describe, expect, it } from 'vitest'
import { ref } from 'vue'
import type { Device, DeviceStackVlans, DeviceVlanDraftRow } from '../../api/types'
import { deviceOf, makeDraft, setVlanDefinitions, setupStores, vlanDef } from './deviceFormTestkit'
import { useDeviceStackVlans } from '../useDeviceStackVlans'

const row = (vlan_id: string, patch: Partial<DeviceVlanDraftRow> = {}): DeviceVlanDraftRow => ({ vlan_id, ip_address: '', prefix_length: '', is_management: false, description: '', ...patch })

function state(items: Array<{ vlan_id: string; ip_address?: string | null; prefix_length?: number | null; is_management?: boolean; members?: unknown[] }>): DeviceStackVlans {
  return {
    stack_name: 'Стек-1',
    member_count: 2,
    available: [],
    items: items.map((i) => ({ ip_address: null, prefix_length: null, is_management: false, members: [], ...i })),
  } as unknown as DeviceStackVlans
}

let stores: ReturnType<typeof setupStores>

function setup(device: Device | null) {
  const current = ref(device)
  const draft = makeDraft(device)
  return { draft, stack: useDeviceStackVlans(draft, () => current.value) }
}

beforeEach(() => {
  stores = setupStores()
  setVlanDefinitions(stores.vlans, [vlanDef('v10', 10), vlanDef('v20', 20), vlanDef('v30', 30)])
})

describe('deviceStackId и блокировка строк', () => {
  it('deviceStackId — стек редактируемого устройства; у нового устройства и вне стека — null', () => {
    expect(setup(deviceOf({ stack_id: 'st-1' })).stack.deviceStackId.value).toBe('st-1')
    expect(setup(deviceOf({ stack_id: null })).stack.deviceStackId.value).toBeNull()
    expect(setup(null).stack.deviceStackId.value).toBeNull()
  })

  it('пока состояние стека не получено, заблокированных VLAN нет', () => {
    expect(setup(deviceOf()).stack.lockedStackVlans.value).toEqual({})
  })

  it('после update:state блокируются VLAN с общей настройкой, причина называет стек', () => {
    const { stack } = setup(deviceOf({ stack_id: 'st-1' }))
    stack.onStackVlanState(state([{ vlan_id: 'v10' }, { vlan_id: 'v20' }]))
    expect(Object.keys(stack.lockedStackVlans.value)).toEqual(['v10', 'v20'])
    expect(stack.lockedStackVlans.value.v10).toContain('Стек-1')
  })

  it('снятие настройки (пустой список) разблокирует строки', () => {
    const { stack } = setup(deviceOf({ stack_id: 'st-1' }))
    stack.onStackVlanState(state([{ vlan_id: 'v10' }]))
    stack.onStackVlanState(state([]))
    expect(stack.lockedStackVlans.value).toEqual({})
  })
})

describe('onStackVlanApplied', () => {
  it('значения общей настройки переносятся в черновик VLAN устройства, строки идут по номеру VLAN, список устройств перечитывается', async () => {
    const { draft, stack } = setup(deviceOf({ id: 'dev-1', stack_id: 'st-1' }))
    draft.deviceVlans.value = [row('v30', { description: 'моя правка' }), row('v10', { ip_address: '1.1.1.1', prefix_length: '8' })]

    await stack.onStackVlanApplied(state([{ vlan_id: 'v10', ip_address: '10.0.0.5', prefix_length: 24, is_management: true }, { vlan_id: 'v20', ip_address: '10.0.1.5', prefix_length: 24 }]))

    expect(draft.deviceVlans.value.map((r) => r.vlan_id)).toEqual(['v10', 'v20', 'v30'])
    expect(draft.deviceVlans.value[0]).toMatchObject({ ip_address: '10.0.0.5', prefix_length: '24', is_management: true })
    expect(draft.deviceVlans.value[1]).toMatchObject({ ip_address: '10.0.1.5', prefix_length: '24' })
    expect(draft.deviceVlans.value[2].description).toBe('моя правка')
    expect(stores.spies.devicesReload).toHaveBeenCalledTimes(1)
  })

  it('у формы создания (нет устройства) черновик не трогается, но список устройств всё равно перечитывается', async () => {
    const { draft, stack } = setup(null)
    draft.deviceVlans.value = [row('v10')]
    const before = draft.deviceVlans.value
    await stack.onStackVlanApplied(state([{ vlan_id: 'v10', ip_address: '10.0.0.5', prefix_length: 24 }]))
    expect(draft.deviceVlans.value).toBe(before)
    expect(stores.spies.devicesReload).toHaveBeenCalledTimes(1)
  })
})

describe('onStackVlanRemoved', () => {
  it('«убрать и у устройств» удаляет строку VLAN из черновика', async () => {
    const { draft, stack } = setup(deviceOf())
    draft.deviceVlans.value = [row('v10'), row('v20')]
    await stack.onStackVlanRemoved({ vlanId: 'v10', fromDevices: true })
    expect(draft.deviceVlans.value.map((r) => r.vlan_id)).toEqual(['v20'])
    expect(stores.spies.devicesReload).toHaveBeenCalledTimes(1)
  })

  it('без «убрать у устройств» значения остаются (поля снова редактируются)', async () => {
    const { draft, stack } = setup(deviceOf())
    draft.deviceVlans.value = [row('v10'), row('v20')]
    const before = draft.deviceVlans.value
    await stack.onStackVlanRemoved({ vlanId: 'v10', fromDevices: false })
    expect(draft.deviceVlans.value).toBe(before)
    expect(stores.spies.devicesReload).toHaveBeenCalledTimes(1)
  })
})
