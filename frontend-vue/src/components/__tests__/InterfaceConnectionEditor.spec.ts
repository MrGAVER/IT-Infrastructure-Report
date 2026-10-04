import { describe, it, expect, beforeEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InterfaceConnectionEditor from '../InterfaceConnectionEditor.vue'
import type { InterfaceConnectionDraft } from '../../api/types'
import { useCatalogsStore } from '../../stores/catalogs'
import { useConnectionsStore } from '../../stores/connections'
import { useDevicesStore } from '../../stores/devices'

const config = { is_management: false, is_data_transfer: true, vlan_mode: 'trunk' as const }

function draft(overrides: Partial<InterfaceConnectionDraft> = {}): InterfaceConnectionDraft {
  return { peer_device_id: '', peer_interface_id: '', connection_type_id: '', description: '', ...overrides }
}

function port(id: string, deviceId: string, name: string, extra: Record<string, unknown> = {}) {
  return { id, physical_device_id: deviceId, name, is_management: false, is_data_transfer: true, vlan_mode: 'trunk', ...extra }
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  useDevicesStore().all = [
    { id: 'dev-self', system_name: 'srv-self', serial_number: 'S0' },
    { id: 'dev-b', system_name: 'sw-b', serial_number: 'S2' },
    { id: 'dev-a', system_name: '', serial_number: 'A-serial' },
  ] as never
  useCatalogsStore().items['interfaces'] = [
    port('b-1', 'dev-b', 'Gi0/1'),
    port('b-2', 'dev-b', 'Gi0/2'),
    port('b-3', 'dev-b', 'Gi0/3'),
    port('a-1', 'dev-a', 'eth0'),
  ] as never
  useCatalogsStore().items['connection-types'] = [{ id: 'ct-1', name: 'Витая пара' }] as never
  useConnectionsStore().all = []
})

function mountEditor(modelValue: InterfaceConnectionDraft | null, extra: Record<string, unknown> = {}) {
  return mount(InterfaceConnectionEditor, { props: { modelValue, deviceId: 'dev-self', config, ...extra } })
}

// SearchableSelect — поле с поиском: опции появляются по фокусу (см. pickVlan в DeviceFormModal.spec.ts).
async function optionLabels(wrapper: VueWrapper, rootSelector: string): Promise<string[]> {
  const select = wrapper.find(`${rootSelector} .searchable-select`)
  await select.find('input').trigger('focus')
  return select.findAll('.ss-option').map((o) => o.text())
}

describe('InterfaceConnectionEditor.vue', () => {
  it('порт не подключён: показывает «Порт не подключён», а «Подключить» отдаёт пустой черновик', async () => {
    const wrapper = mountEditor(null)
    expect(wrapper.text()).toContain('Порт не подключён')
    expect(wrapper.find('.connection-grid').exists()).toBe(false)

    await wrapper.find('.connection-connect-btn').trigger('click')

    expect(wrapper.emitted('update:modelValue')![0][0]).toEqual({ peer_device_id: '', peer_interface_id: '', connection_type_id: '', description: '' })
  })

  it('«Отключить» отдаёт null', async () => {
    const wrapper = mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-1', connection_type_id: 'ct-1' }))
    await wrapper.find('.connection-disconnect-btn').trigger('click')
    expect(wrapper.emitted('update:modelValue')![0][0]).toBeNull()
  })

  it('в списке устройств нет самого редактируемого устройства; подпись — системное имя или серийный номер', async () => {
    const wrapper = mountEditor(draft())
    expect(await optionLabels(wrapper, '.connection-peer-device')).toEqual(['A-serial', 'sw-b'])
  })

  it('порт соседа недоступен, пока не выбрано устройство; затем показываются только его порты', async () => {
    const empty = mountEditor(draft())
    expect(empty.find('.connection-peer-port input').attributes('disabled')).toBeDefined()

    const wrapper = mountEditor(draft({ peer_device_id: 'dev-b' }))
    expect(await optionLabels(wrapper, '.connection-peer-port')).toEqual(['Gi0/1', 'Gi0/2', 'Gi0/3'])
  })

  it('порты, занятые активным подключением, и порты, выбранные в соседних строках, исключены; свой выбранный порт остаётся', async () => {
    useConnectionsStore().all = [
      { id: 'c-1', source_interface_id: 'x-1', destination_interface_id: 'b-1', is_active: true },
      { id: 'c-2', source_interface_id: 'x-2', destination_interface_id: 'b-3', is_active: false }, // неактивное порт не занимает
    ] as never
    const wrapper = mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-2' }), { takenPeerIds: new Set(['b-3']) })

    expect(await optionLabels(wrapper, '.connection-peer-port')).toEqual(['Gi0/2'])
  })

  it('порт соседа, который уже выбран в этой строке подключением, остаётся доступным, даже если он занят этим же подключением', async () => {
    useConnectionsStore().all = [{ id: 'c-1', source_interface_id: 'self-1', destination_interface_id: 'b-1', is_active: true }] as never
    const wrapper = mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-1' }))
    expect(await optionLabels(wrapper, '.connection-peer-port')).toContain('Gi0/1')
  })

  it('смена устройства-соседа сбрасывает выбранный порт', async () => {
    const wrapper = mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-1', connection_type_id: 'ct-1' }))
    const select = wrapper.find('.connection-peer-device .searchable-select')
    await select.find('input').trigger('focus')
    await select.findAll('.ss-option').find((o) => o.text() === 'A-serial')!.trigger('mousedown')

    expect(wrapper.emitted('update:modelValue')![0][0]).toEqual({ peer_device_id: 'dev-a', peer_interface_id: '', connection_type_id: 'ct-1', description: '' })
  })

  it('выбор порта, типа линии и ввод описания обновляют только своё поле черновика', async () => {
    const wrapper = mountEditor(draft({ peer_device_id: 'dev-b' }))
    const portSelect = wrapper.find('.connection-peer-port .searchable-select')
    await portSelect.find('input').trigger('focus')
    await portSelect.findAll('.ss-option').find((o) => o.text() === 'Gi0/2')!.trigger('mousedown')
    await wrapper.find('.connection-description input').setValue('патч-корд №5')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toMatchObject({ peer_device_id: 'dev-b', peer_interface_id: 'b-2' })
    expect(emitted[1][0]).toMatchObject({ description: 'патч-корд №5' })
  })

  it('у выбранного устройства нет свободных портов — показывается подсказка', () => {
    useCatalogsStore().items['interfaces'] = [] as never
    const wrapper = mountEditor(draft({ peer_device_id: 'dev-b' }))
    expect(wrapper.find('.connection-hint').text()).toContain('нет свободных')
  })

  it('расхождение конфигурации с портом соседа показывается сразу, совпадающая — нет', () => {
    useCatalogsStore().items['interfaces'] = [port('b-1', 'dev-b', 'Gi0/1', { is_management: true, vlan_mode: 'access' })] as never
    const differ = mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-1' }))
    expect(differ.find('.connection-diffs').text()).toContain('«Управление»: нет / у соседа да')
    expect(differ.find('.connection-diffs').text()).toContain('режим порта: trunk / у соседа access')

    useCatalogsStore().items['interfaces'] = [port('b-1', 'dev-b', 'Gi0/1')] as never
    const same = mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-1' }))
    expect(same.find('.connection-diffs').exists()).toBe(false)
  })
})
