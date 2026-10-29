import { beforeEach, describe, expect, it } from 'vitest'
import { ref } from 'vue'
import type { DeviceInterfaceConnection } from '../../api/deviceConnectivity'
import { emptyDeviceForm } from '../../utils/deviceForm'
import { emptyGroup } from '../../utils/interfaceGroups'
import { makeRow } from '../../utils/__tests__/interfaceRowFixture'
import { deviceOf, setupStores } from './deviceFormTestkit'
import { useDeviceDraft } from '../useDeviceDraft'

beforeEach(() => {
  setupStores()
})

describe('useDeviceDraft: режим формы', () => {
  it('без устройства — создание: existingDeviceId null, isEdit false', () => {
    const draft = useDeviceDraft(() => null)
    expect(draft.existingDeviceId.value).toBeNull()
    expect(draft.isEdit.value).toBe(false)
  })

  it('с устройством — редактирование', () => {
    const draft = useDeviceDraft(() => deviceOf({ id: 'dev-7' }))
    expect(draft.existingDeviceId.value).toBe('dev-7')
    expect(draft.isEdit.value).toBe(true)
  })

  it('созданное этой формой устройство превращает повторное сохранение в обновление', () => {
    const draft = useDeviceDraft(() => null)
    draft.createdDevice.value = deviceOf({ id: 'dev-new' })
    expect(draft.existingDeviceId.value).toBe('dev-new')
    expect(draft.isEdit.value).toBe(true)
  })

  it('при обоих источниках приоритет у редактируемого устройства; реагирует на смену устройства', () => {
    const device = ref(deviceOf({ id: 'dev-1' }))
    const draft = useDeviceDraft(() => device.value)
    draft.createdDevice.value = deviceOf({ id: 'dev-new' })
    expect(draft.existingDeviceId.value).toBe('dev-1')
    device.value = deviceOf({ id: 'dev-2' })
    expect(draft.existingDeviceId.value).toBe('dev-2')
  })
})

describe('useDeviceDraft: начальное состояние', () => {
  it('форма пуста, списки пусты, снимки пусты', () => {
    const draft = useDeviceDraft(() => null)
    expect({ ...draft.form }).toEqual(emptyDeviceForm())
    expect(draft.interfaces.value).toEqual([])
    expect(draft.interfaceGroups.value).toEqual([])
    expect(draft.softwareAssets.value).toEqual([])
    expect(draft.deviceVlans.value).toEqual([])
    expect(draft.memberDomainIds.value.size).toBe(0)
    expect(draft.pendingDomainMemberships.value.size).toBe(0)
    expect(draft.pendingSourceDomainIds.value.size).toBe(0)
    expect(draft.deviceTypeVlanIds.value.size).toBe(0)
    expect(draft.snapshot.portConfigs.size).toBe(0)
    expect(draft.snapshot.deviceVlanKey).toBe('')
    expect(draft.initialConnections.value.size).toBe(0)
    expect(draft.savedConnections.value).toEqual([])
    expect(draft.errorMessage.value).toBeNull()
    expect(draft.loadingNested.value).toBe(false)
    expect(draft.joinedDomainIds.size).toBe(0)
  })

  it('два черновика не делят состояние', () => {
    const a = useDeviceDraft(() => null)
    const b = useDeviceDraft(() => null)
    a.form.serial_number = 'SN-A'
    a.joinedDomainIds.add('dom-1')
    expect(b.form.serial_number).toBe('')
    expect(b.joinedDomainIds.size).toBe(0)
  })
})

describe('useDeviceDraft: reset', () => {
  it('возвращает форму и вложенные данные в пустое состояние, но не трогает группы портов, ошибку и созданное устройство', () => {
    const draft = useDeviceDraft(() => null)
    draft.form.serial_number = 'SN-1'
    draft.softwareAssets.value = [{ software_asset_id: 'sa-1', version: '' }]
    draft.interfaces.value = [makeRow({ id: 'if-1' })]
    draft.deviceVlans.value = [{ vlan_id: 'v10', ip_address: '', prefix_length: '', is_management: false, description: '' }]
    draft.memberDomainIds.value = new Set(['dom-1'])
    draft.pendingDomainMemberships.value = new Set(['dom-2'])
    draft.pendingSourceDomainIds.value = new Set(['dom-3'])
    draft.deviceTypeVlanIds.value = new Set(['v10'])
    draft.snapshot.portConfigs = new Map([['if-1', { is_management: false, is_data_transfer: false, vlan_mode: 'access', all_vlans: false }]])
    draft.initialConnections.value = new Map([['if-1', null]])
    draft.savedConnections.value = [{ interface_id: 'if-1' } as DeviceInterfaceConnection]
    const group = emptyGroup('Группа')
    draft.interfaceGroups.value = [group]
    draft.errorMessage.value = 'ошибка'
    draft.createdDevice.value = deviceOf({ id: 'dev-new' })

    draft.reset()

    expect({ ...draft.form }).toEqual(emptyDeviceForm())
    expect(draft.softwareAssets.value).toEqual([])
    expect(draft.interfaces.value).toEqual([])
    expect(draft.deviceVlans.value).toEqual([])
    expect(draft.memberDomainIds.value.size).toBe(0)
    expect(draft.pendingDomainMemberships.value.size).toBe(0)
    expect(draft.pendingSourceDomainIds.value.size).toBe(0)
    expect(draft.deviceTypeVlanIds.value.size).toBe(0)
    expect(draft.snapshot.portConfigs.size).toBe(0)
    expect(draft.initialConnections.value.size).toBe(0)
    expect(draft.savedConnections.value).toEqual([])
    // эти поля reset сознательно не трогает
    expect(draft.interfaceGroups.value).toEqual([group])
    expect(draft.errorMessage.value).toBe('ошибка')
    expect(draft.createdDevice.value?.id).toBe('dev-new')
  })

  it('форма остаётся тем же reactive-объектом (на неё подписаны watch и дочерние компоненты)', () => {
    const draft = useDeviceDraft(() => null)
    const form = draft.form
    form.serial_number = 'SN-1'
    draft.reset()
    expect(draft.form).toBe(form)
    expect(form.serial_number).toBe('')
  })
})

describe('useDeviceDraft: interfaceConflicts', () => {
  const neighbor = (patch: Partial<DeviceInterfaceConnection> = {}): DeviceInterfaceConnection => ({
    interface_id: 'if-1',
    connection_id: 'c-1',
    connection_type_id: 'ct-1',
    description: null,
    peer_interface_id: 'p-1',
    peer_interface_name: 'Gi0/9',
    peer_device_id: 'dev-2',
    peer_device_name: 'sw-02',
    peer_is_management: false,
    peer_is_data_transfer: false,
    peer_vlan_mode: 'access',
    peer_all_vlans: false,
    ...patch,
  })

  it('без соседей конфликтов нет', () => {
    const draft = useDeviceDraft(() => null)
    draft.interfaces.value = [makeRow({ id: 'if-1' })]
    expect(draft.interfaceConflicts.value).toEqual({})
  })

  it('считается по текущему черновику портов и сведениям о соседях и пересчитывается при правке порта', () => {
    const draft = useDeviceDraft(() => null)
    draft.interfaces.value = [makeRow({ id: 'if-1', vlan_mode: 'access' })]
    draft.savedConnections.value = [neighbor({ peer_vlan_mode: 'trunk' })]
    expect(draft.interfaceConflicts.value['if-1']).toMatchObject({ vlanModeDiffer: true, flagsDiffer: false, otherDeviceName: 'sw-02' })

    draft.interfaces.value = [makeRow({ id: 'if-1', vlan_mode: 'trunk' })]
    expect(draft.interfaceConflicts.value).toEqual({})
  })
})
