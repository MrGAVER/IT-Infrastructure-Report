import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import type { DeviceNestedData } from '../../api/deviceFormData'
import type { DeviceInterfaceConnection } from '../../api/deviceConnectivity'
import type { Device } from '../../api/types'
import { makeRow } from '../../utils/__tests__/interfaceRowFixture'
import { deviceOf, setVlanDefinitions, setupStores, vlanDef } from './deviceFormTestkit'
import { useDeviceDraft } from '../useDeviceDraft'
import { useDeviceLoader } from '../useDeviceLoader'
import { useToast } from '../useToast'

const loadDeviceNestedData = vi.fn()
const fetchDeviceInterfaceConnections = vi.fn()
const loadDeviceTypeVlanIds = vi.fn()
vi.mock('../../api/deviceFormData', () => ({ loadDeviceNestedData: (...args: unknown[]) => loadDeviceNestedData(...args) }))
vi.mock('../../api/deviceConnectivity', () => ({ fetchDeviceInterfaceConnections: (...args: unknown[]) => fetchDeviceInterfaceConnections(...args) }))
vi.mock('../../api/portVlans', () => ({ loadDeviceTypeVlanIds: (...args: unknown[]) => loadDeviceTypeVlanIds(...args) }))

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))
const connection = { interface_id: 'if-1', peer_device_name: 'sw-02' } as DeviceInterfaceConnection

function nested(patch: Partial<DeviceNestedData> = {}): DeviceNestedData {
  return {
    softwareAssets: [{ id: 'ds-1', software_asset_id: 'sa-1', version: '' }],
    interfaces: [makeRow({ id: 'if-1', name: 'Gi0/1', is_management: true, connection: { peer_device_id: 'dev-2', peer_interface_id: 'p-1', connection_type_id: 'ct-1', description: '' } })],
    interfaceGroups: [],
    vlanRows: [
      { id: 'dv-30', vlan_id: 'v30', ip_address: '', prefix_length: '', is_management: false, description: '' },
      { id: 'dv-10', vlan_id: 'v10', ip_address: '', prefix_length: '', is_management: false, description: '' },
    ],
    domainIds: ['dom-1'],
    typeVlanIds: new Set(['v10', 'v30']),
    connections: [connection],
    ...patch,
  }
}

let stores: ReturnType<typeof setupStores>

function setup(initial: { device?: Device | null; copyFrom?: Device | null } = {}) {
  const device = ref<Device | null>(initial.device ?? null)
  const copyFrom = ref<Device | null | undefined>(initial.copyFrom)
  // как в форме: черновик и загрузчик читают одно и то же редактируемое устройство
  const draft = useDeviceDraft(() => device.value)
  const loader = useDeviceLoader(draft, { device: () => device.value, copyFrom: () => copyFrom.value })
  return { device, copyFrom, draft, loader }
}

beforeEach(() => {
  vi.clearAllMocks()
  stores = setupStores()
  setVlanDefinitions(stores.vlans, [vlanDef('v10', 10), vlanDef('v30', 30)])
  loadDeviceNestedData.mockResolvedValue(nested())
  fetchDeviceInterfaceConnections.mockResolvedValue([connection])
  loadDeviceTypeVlanIds.mockResolvedValue(new Set(['v99']))
  useToast().toasts.splice(0)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('создание нового устройства', () => {
  it('грузит только справочник доменов; вложенные данные не запрашиваются, форма пуста', async () => {
    const { draft } = setup()
    await settle()
    expect(stores.spies.domainsEnsureLoaded).toHaveBeenCalledTimes(1)
    expect(loadDeviceNestedData).not.toHaveBeenCalled()
    expect(draft.form.serial_number).toBe('')
    expect(draft.loadingNested.value).toBe(false)
  })
})

describe('редактирование устройства', () => {
  const source = () => deviceOf({ id: 'dev-1', device_type_id: 't-sw', serial_number: 'SN-1', system_name: 'sw-01' } as Partial<Device>)

  it('форма заполняется из устройства, вложенные данные запрашиваются с isCopy = false и справочником VLAN', async () => {
    const { draft } = setup({ device: source() })
    expect(draft.form).toMatchObject({ device_type_id: 't-sw', serial_number: 'SN-1', system_name: 'sw-01' })
    await settle()
    expect(loadDeviceNestedData).toHaveBeenCalledTimes(1)
    const [passed, isCopy, ensure] = loadDeviceNestedData.mock.calls[0]
    expect(passed.id).toBe('dev-1')
    expect(isCopy).toBe(false)
    await ensure()
    expect(stores.spies.vlansEnsureLoaded).toHaveBeenCalledTimes(1)
  })

  it('индикатор загрузки включается сразу и гаснет после ответа', async () => {
    const { draft } = setup({ device: source() })
    expect(draft.loadingNested.value).toBe(true)
    await settle()
    expect(draft.loadingNested.value).toBe(false)
  })

  it('данные раскладываются по черновику; строки VLAN устройства — по номеру VLAN; снимки отражают загруженное', async () => {
    const { draft } = setup({ device: source() })
    await settle()

    expect(draft.softwareAssets.value).toHaveLength(1)
    expect(draft.interfaces.value[0].id).toBe('if-1')
    expect(draft.deviceVlans.value.map((r) => r.vlan_id)).toEqual(['v10', 'v30'])
    expect(draft.snapshot.deviceVlanKey).toBe('v10|v30')
    expect([...draft.snapshot.portConfigs.keys()]).toEqual(['if-1'])
    expect(draft.snapshot.portConfigs.get('if-1')).toMatchObject({ is_management: true })
    expect(draft.initialConnections.value.get('if-1')).toMatchObject({ peer_device_id: 'dev-2' })
    expect(draft.savedConnections.value).toEqual([connection])
    expect([...draft.deviceTypeVlanIds.value]).toEqual(['v10', 'v30'])
  })

  it('домены попадают в подтверждённые, а не в отложенные', async () => {
    const { draft } = setup({ device: source() })
    await settle()
    expect([...draft.memberDomainIds.value]).toEqual(['dom-1'])
    expect(draft.pendingDomainMemberships.value.size).toBe(0)
  })

  it('смена устройства сбрасывает черновик и грузит данные нового', async () => {
    const { draft, device } = setup({ device: source() })
    await settle()
    draft.errorMessage.value = null
    loadDeviceNestedData.mockResolvedValue(nested({ softwareAssets: [], interfaces: [], domainIds: [] }))

    device.value = deviceOf({ id: 'dev-2', device_type_id: 't-srv', serial_number: 'SN-2' } as Partial<Device>)
    await nextTick()
    await settle()

    expect(draft.form).toMatchObject({ device_type_id: 't-srv', serial_number: 'SN-2', system_name: '' })
    expect(loadDeviceNestedData).toHaveBeenCalledTimes(2)
    expect(loadDeviceNestedData.mock.calls[1][0].id).toBe('dev-2')
    expect(draft.interfaces.value).toEqual([])
    expect(draft.memberDomainIds.value.size).toBe(0)
  })

  it('переход к созданию (устройство снято): данные прежнего устройства не остаются в черновике', async () => {
    const { draft, device } = setup({ device: source() })
    await settle()
    expect(draft.interfaces.value).toHaveLength(1)
    expect(draft.softwareAssets.value).toHaveLength(1)

    device.value = null
    await nextTick()
    await settle()

    expect(draft.form.serial_number).toBe('')
    expect(draft.interfaces.value).toEqual([])
    expect(draft.softwareAssets.value).toEqual([])
    expect(draft.deviceVlans.value).toEqual([])
    expect(draft.savedConnections.value).toEqual([])
    expect(draft.memberDomainIds.value.size).toBe(0)
  })

  it('сбой загрузки показывается в форме, индикатор гаснет, данные не заполняются наполовину', async () => {
    loadDeviceNestedData.mockRejectedValue(new Error('сервер недоступен'))
    const { draft } = setup({ device: source() })
    await settle()
    expect(draft.errorMessage.value).toBe('сервер недоступен')
    expect(draft.loadingNested.value).toBe(false)
    expect(draft.interfaces.value).toEqual([])
  })

  it('не-Error в отказе заменяется понятным сообщением по умолчанию', async () => {
    loadDeviceNestedData.mockRejectedValue('boom')
    const { draft } = setup({ device: source() })
    await settle()
    expect(draft.errorMessage.value).toBe('Не удалось загрузить открытые порты, ПО, интерфейсы и VLAN устройства')
  })
})

describe('копирование', () => {
  const donor = () => deviceOf({ id: 'dev-donor', device_type_id: 't-sw', serial_number: 'SN-DONOR', system_name: 'sw-donor' } as Partial<Device>)

  it('форма берёт данные донора без серийного номера, данные запрашиваются с isCopy = true', async () => {
    const { draft } = setup({ copyFrom: donor() })
    await settle()
    expect(draft.form).toMatchObject({ system_name: 'sw-donor', serial_number: '' })
    expect(loadDeviceNestedData.mock.calls[0][1]).toBe(true)
  })

  it('домены донора становятся отложенным включением: членства у нового устройства ещё нет', async () => {
    const { draft } = setup({ copyFrom: donor() })
    await settle()
    expect([...draft.pendingDomainMemberships.value]).toEqual(['dom-1'])
    expect(draft.memberDomainIds.value.size).toBe(0)
  })

  it('это по-прежнему создание: существующего устройства у черновика нет', async () => {
    const { draft } = setup({ copyFrom: donor() })
    await settle()
    expect(draft.existingDeviceId.value).toBeNull()
  })

  it('одновременная передача device и copyFrom: предупреждение в консоль, побеждает device (редактирование)', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const { draft } = setup({ device: deviceOf({ id: 'dev-1', serial_number: 'SN-1' } as Partial<Device>), copyFrom: donor() })
    await settle()
    expect(warn).toHaveBeenCalledTimes(1)
    expect(draft.form.serial_number).toBe('SN-1')
    expect(loadDeviceNestedData.mock.calls[0][0].id).toBe('dev-1')
    expect(loadDeviceNestedData.mock.calls[0][1]).toBe(false)
  })
})

describe('смена типа устройства после загрузки', () => {
  const source = () => deviceOf({ id: 'dev-1', device_type_id: 't-sw' } as Partial<Device>)

  it('допустимые VLAN перечитываются под новый тип', async () => {
    const { draft } = setup({ device: source() })
    await settle()
    expect(loadDeviceTypeVlanIds).not.toHaveBeenCalled()

    draft.form.device_type_id = 't-srv'
    await nextTick()
    await settle()

    expect(loadDeviceTypeVlanIds).toHaveBeenCalledWith('t-srv')
    expect([...draft.deviceTypeVlanIds.value]).toEqual(['v99'])
  })

  it('во время начальной загрузки тип не перечитывается отдельным запросом (данные приходят атомарно)', async () => {
    let finish: (v: DeviceNestedData) => void = () => undefined
    loadDeviceNestedData.mockReturnValue(new Promise<DeviceNestedData>((resolve) => (finish = resolve)))
    const { draft } = setup({ device: source() })
    draft.form.device_type_id = 't-other'
    await nextTick()
    await settle()
    expect(loadDeviceTypeVlanIds).not.toHaveBeenCalled()
    finish(nested())
    await settle()
  })

  it('сбой перечитывания: прежний список VLAN остаётся, ошибка показана в форме, отказ промиса не «утекает»', async () => {
    const { draft } = setup({ device: source() })
    await settle()
    draft.deviceTypeVlanIds.value = new Set(['v10'])
    loadDeviceTypeVlanIds.mockRejectedValue(new Error('типы недоступны'))

    draft.form.device_type_id = 't-srv'
    await nextTick()
    await settle()

    expect(draft.errorMessage.value).toBe('типы недоступны')
    expect([...draft.deviceTypeVlanIds.value]).toEqual(['v10'])
  })

  it('новое устройство: смена типа тоже подтягивает допустимые VLAN типа', async () => {
    const { draft } = setup()
    await settle()
    draft.form.device_type_id = 't-srv'
    await nextTick()
    await settle()
    expect(loadDeviceTypeVlanIds).toHaveBeenCalledWith('t-srv')
  })
})

describe('reloadNeighborConfigs', () => {
  it('у устройства, которого ещё нет в БД, ничего не запрашивает', async () => {
    const { loader } = setup()
    await settle()
    await loader.reloadNeighborConfigs()
    expect(fetchDeviceInterfaceConnections).not.toHaveBeenCalled()
  })

  it('обновляет сведения о соседях с сервера', async () => {
    const { draft, loader } = setup({ device: deviceOf({ id: 'dev-1' }) })
    await settle()
    const fresh = { interface_id: 'if-1', peer_device_name: 'sw-NEW' } as DeviceInterfaceConnection
    fetchDeviceInterfaceConnections.mockResolvedValue([fresh])
    await loader.reloadNeighborConfigs()
    expect(fetchDeviceInterfaceConnections).toHaveBeenLastCalledWith('dev-1')
    expect(draft.savedConnections.value).toEqual([fresh])
  })

  it('ошибка не глотается: показывается уведомлением, старые сведения остаются', async () => {
    const { draft, loader } = setup({ device: deviceOf({ id: 'dev-1' }) })
    await settle()
    fetchDeviceInterfaceConnections.mockRejectedValue(new Error('нет связи'))
    await loader.reloadNeighborConfigs()
    expect(useToast().toasts.map((t) => [t.type, t.message])).toEqual([['error', 'нет связи']])
    expect(draft.savedConnections.value).toEqual([connection])
  })
})
