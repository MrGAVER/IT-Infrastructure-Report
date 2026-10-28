import { describe, expect, it } from 'vitest'
import type { DeployedSoftware, Device, DeviceModel, DeviceVLAN, DeviceVlanDraftRow } from '../../api/types'
import {
  buildTypeModelOptions,
  copyInterfaceRows,
  deviceFormFromSource,
  deviceFormPayload,
  deviceVlanKey,
  emptyDeviceForm,
  groupModelsByManufacturer,
  modelOptionLabel,
  toDeviceVlanDraftRow,
  toSoftwareDraftRow,
  typeModelPatch,
  typeModelValue,
  TYPE_WITHOUT_MODEL_GROUP,
} from '../deviceForm'
import { makeRow } from './interfaceRowFixture'

function model(id: string, name: string, manufacturerId: string, typeId = 't-sw'): DeviceModel {
  return { id, name, model: name, manufacturer_id: manufacturerId, device_type_id: typeId } as DeviceModel
}

const source = {
  id: 'dev-1',
  device_type_id: 't-sw',
  manufacturer_id: 'm-cisco',
  model_id: 'mod-1',
  serial_number: 'SN-1',
  system_name: 'sw-01',
  operating_system_id: null,
  embedded_os_id: 'eos-1',
  siem_enabled: true,
  building_id: 'b-1',
  room_id: 'r-1',
  rack_id: null,
  rack_position: '12U',
  description: null,
  oac_certificate_number: 'OAC-1',
  oac_certificate_registry_date: '2026-01-31',
  diagram_icon_id: null,
} as unknown as Device

describe('emptyDeviceForm', () => {
  it('все поля пусты, siem_enabled выключен; каждый вызов — новый объект', () => {
    const a = emptyDeviceForm()
    expect(Object.values(a).filter((v) => v !== '' && v !== false)).toEqual([])
    expect(a.siem_enabled).toBe(false)
    a.serial_number = 'x'
    expect(emptyDeviceForm().serial_number).toBe('')
  })
})

describe('deviceFormFromSource', () => {
  it('без источника — пустая форма', () => {
    expect(deviceFormFromSource(null, false)).toEqual(emptyDeviceForm())
  })

  it('поля берутся из устройства: null → пустая строка, boolean остаётся boolean', () => {
    const form = deviceFormFromSource(source, false)
    expect(form).toMatchObject({
      device_type_id: 't-sw',
      manufacturer_id: 'm-cisco',
      model_id: 'mod-1',
      serial_number: 'SN-1',
      system_name: 'sw-01',
      operating_system_id: '',
      embedded_os_id: 'eos-1',
      siem_enabled: true,
      building_id: 'b-1',
      room_id: 'r-1',
      rack_id: '',
      rack_position: '12U',
      description: '',
      oac_certificate_number: 'OAC-1',
      oac_certificate_registry_date: '2026-01-31',
      diagram_icon_id: '',
    })
  })

  it('поля, которых нет у формы (id, stack_id…), в неё не попадают', () => {
    expect(Object.keys(deviceFormFromSource(source, false)).sort()).toEqual(Object.keys(emptyDeviceForm()).sort())
  })

  it('копия сбрасывает серийный номер (он уникален), остальное переносит', () => {
    const form = deviceFormFromSource(source, true)
    expect(form.serial_number).toBe('')
    expect(form).toMatchObject({ system_name: 'sw-01', model_id: 'mod-1', siem_enabled: true })
  })

  it('siem_enabled у устройства без этого поля — false, а не undefined', () => {
    expect(deviceFormFromSource({ ...source, siem_enabled: undefined } as unknown as Device, false).siem_enabled).toBe(false)
  })
})

describe('deviceFormPayload', () => {
  it('пустые строки уходят как null, остальное — как есть, false не превращается в null', () => {
    const payload = deviceFormPayload({ ...emptyDeviceForm(), serial_number: 'SN-1', siem_enabled: false })
    expect(payload).toMatchObject({ serial_number: 'SN-1', system_name: null, room_id: null, siem_enabled: false })
  })

  it('extra дописывается поверх и может переопределить поле', () => {
    const payload = deviceFormPayload({ ...emptyDeviceForm(), serial_number: 'SN-1' }, { confirm_system_name_duplicate: true, serial_number: 'SN-2' })
    expect(payload).toMatchObject({ confirm_system_name_duplicate: true, serial_number: 'SN-2' })
  })
})

describe('строки черновиков', () => {
  it('toSoftwareDraftRow: пустая версия — пустая строка', () => {
    expect(toSoftwareDraftRow({ id: 'd1', software_asset_id: 'sa-1', version: null } as DeployedSoftware)).toEqual({ id: 'd1', software_asset_id: 'sa-1', version: '' })
    expect(toSoftwareDraftRow({ id: 'd1', software_asset_id: 'sa-1', version: '2.4' } as DeployedSoftware).version).toBe('2.4')
  })

  it('toDeviceVlanDraftRow: IP и описание — строки, префикс — строка (0 не теряется), null → пусто', () => {
    const full = { id: 'v1', vlan_id: 'vl-1', ip_address: '10.0.0.1', prefix_length: 0, is_management: true, description: 'mgmt' } as DeviceVLAN
    expect(toDeviceVlanDraftRow(full)).toEqual({ id: 'v1', vlan_id: 'vl-1', ip_address: '10.0.0.1', prefix_length: '0', is_management: true, description: 'mgmt' })
    const empty = { id: 'v2', vlan_id: 'vl-2', ip_address: null, prefix_length: null, is_management: false, description: null } as DeviceVLAN
    expect(toDeviceVlanDraftRow(empty)).toMatchObject({ ip_address: '', prefix_length: '', description: '' })
  })

  it('deviceVlanKey не зависит от порядка строк и не считает пустые', () => {
    const rows = (...ids: string[]): DeviceVlanDraftRow[] => ids.map((vlan_id) => ({ vlan_id, ip_address: '', prefix_length: '', is_management: false, description: '' }))
    expect(deviceVlanKey(rows('b', 'a', ''))).toBe('a|b')
    expect(deviceVlanKey(rows('a', 'b'))).toBe(deviceVlanKey(rows('b', 'a')))
    expect(deviceVlanKey([])).toBe('')
  })
})

describe('copyInterfaceRows', () => {
  it('у копии нет id порта, IP, открытых портов и подинтерфейсов, а подключения не наследуются', () => {
    const donor = makeRow({
      id: 'if-1',
      name: 'Gi0/1',
      ips: [{ id: 'ip-1', ip_address: '10.0.0.1', prefix_length: '24', purpose: '' }],
      open_ports: [{ id: 'op-1', protocol_catalog_id: 'c22', transport_protocol: 'TCP', description: '' }],
      subinterfaces: [{ id: 's-1', key: 's1', name: 'Gi0/1.10', vlan_id: 'v10', is_management: false, is_data_transfer: false, description: '', ips: [{ id: 'sip-1', ip_address: '10.1.0.1', prefix_length: '24', purpose: '' }], open_ports: [] }],
      connection: { peer_device_id: 'dev-2', peer_interface_id: 'p1', connection_type_id: '', description: '', peer_device_name: 'sw-02', peer_interface_name: 'Gi0/9' },
    })
    const [copy] = copyInterfaceRows([donor])

    expect(copy.id).toBeUndefined()
    expect(copy.ips[0].id).toBeUndefined()
    expect(copy.open_ports[0].id).toBeUndefined()
    expect(copy.subinterfaces![0].id).toBeUndefined()
    expect(copy.subinterfaces![0].ips[0].id).toBeUndefined()
    expect(copy.connection).toBeNull()
    expect(copy).toMatchObject({ name: 'Gi0/1', ips: [{ ip_address: '10.0.0.1' }] })
    // донор не тронут
    expect(donor.id).toBe('if-1')
    expect(donor.ips[0].id).toBe('ip-1')
    expect(donor.connection).not.toBeNull()
  })
})

describe('поле «Тип / производитель / модель»', () => {
  const models = [model('m3', 'WS-C2960', 'cisco'), model('m1', 'Zeta', 'acme'), model('m2', 'Alpha', 'acme'), model('m4', 'NoVendor', '')]
  // Латиница: порядок кириллицы и латиницы в localeCompare('ru') зависит от ICU, в тесте он не проверяется.
  const name = (id: string | null) => ({ cisco: 'Cisco', acme: 'Acme' })[id ?? ''] ?? 'Unknown'

  it('groupModelsByManufacturer: группы по названию производителя, модели внутри — по названию', () => {
    const groups = groupModelsByManufacturer(models, name)
    expect(groups.map((g) => g.manufacturerName)).toEqual(['Acme', 'Cisco', 'Unknown'])
    expect(groups[0].models.map((m) => m.model)).toEqual(['Alpha', 'Zeta'])
    expect(groups.find((g) => g.manufacturerId === '')!.models.map((m) => m.id)).toEqual(['m4'])
  })

  it('groupModelsByManufacturer: модель без производителя (null) попадает в группу без производителя', () => {
    const groups = groupModelsByManufacturer([{ ...model('m9', 'X', ''), manufacturer_id: null } as unknown as DeviceModel], name)
    expect(groups).toEqual([{ manufacturerId: '', manufacturerName: 'Unknown', models: [expect.objectContaining({ id: 'm9' })] }])
  })

  it('modelOptionLabel: с производителем — «Производитель Модель», без — только модель', () => {
    expect(modelOptionLabel({ manufacturerId: 'cisco', manufacturerName: 'Cisco' }, models[0])).toBe('Cisco WS-C2960')
    expect(modelOptionLabel({ manufacturerId: '', manufacturerName: 'Unknown' }, models[3])).toBe('NoVendor')
  })

  it('buildTypeModelOptions: сначала модели по группам, затем «голые» типы; значения закодированы', () => {
    const options = buildTypeModelOptions(groupModelsByManufacturer(models, name), [{ id: 't-srv', name: 'Сервер' }], (typeId) => `тип ${typeId}`)

    expect(options.map((o) => o.value)).toEqual(['model:m2', 'model:m1', 'model:m3', 'model:m4', 'type:t-srv'])
    expect(options[0]).toEqual({ value: 'model:m2', label: 'Acme Alpha', group: 'Acme', searchText: 'тип t-sw' })
    expect(options[4]).toEqual({ value: 'type:t-srv', label: 'Сервер', group: TYPE_WITHOUT_MODEL_GROUP })
  })

  it('typeModelValue: модель важнее типа, без обоих — пустая строка', () => {
    expect(typeModelValue({ model_id: 'm1', device_type_id: 't1' })).toBe('model:m1')
    expect(typeModelValue({ model_id: '', device_type_id: 't1' })).toBe('type:t1')
    expect(typeModelValue({ model_id: '', device_type_id: '' })).toBe('')
  })

  it('typeModelPatch: выбор модели переносит в форму её тип и производителя', () => {
    expect(typeModelPatch('model:m3', models, 'old-type')).toEqual({ model_id: 'm3', device_type_id: 't-sw', manufacturer_id: 'cisco' })
  })

  it('typeModelPatch: модель, которой нет в справочнике, оставляет текущий тип и сбрасывает производителя', () => {
    expect(typeModelPatch('model:gone', models, 'old-type')).toEqual({ model_id: 'gone', device_type_id: 'old-type', manufacturer_id: '' })
  })

  it('typeModelPatch: выбор «голого» типа сбрасывает модель и производителя; пустой или undefined — все три поля', () => {
    expect(typeModelPatch('type:t-srv', models, 'old')).toEqual({ model_id: '', device_type_id: 't-srv', manufacturer_id: '' })
    expect(typeModelPatch('', models, 'old')).toEqual({ model_id: '', device_type_id: '', manufacturer_id: '' })
    expect(typeModelPatch(undefined, models, 'old')).toEqual({ model_id: '', device_type_id: '', manufacturer_id: '' })
  })
})
