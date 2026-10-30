import { describe, expect, it } from 'vitest'
import type { DeviceVlanDraftRow } from '../../api/types'
import { validateDeviceDraft, type DeviceDraftToValidate } from '../deviceFormValidation'
import { emptyGroup } from '../interfaceGroups'
import { makeRow, makeVlan } from './interfaceRowFixture'

function vlanRow(patch: Partial<DeviceVlanDraftRow> = {}): DeviceVlanDraftRow {
  return { vlan_id: 'v10', ip_address: '', prefix_length: '', is_management: false, description: '', ...patch }
}

function draft(patch: Partial<DeviceDraftToValidate> = {}): DeviceDraftToValidate {
  return {
    form: { device_type_id: 't-sw', serial_number: 'SN-1' },
    interfaces: [],
    interfaceGroups: [],
    deviceVlans: [],
    vlanDefinitions: [makeVlan('v10', 10), makeVlan('v20', 20)],
    protocolPortCatalog: [],
    portVlanIds: new Set(['v10', 'v20']),
    initialConnections: new Map(),
    ...patch,
  }
}

describe('validateDeviceDraft', () => {
  it('корректная форма — проблем нет', () => {
    expect(
      validateDeviceDraft(draft({ interfaces: [makeRow({ name: 'Gi0/1' })], deviceVlans: [vlanRow({ ip_address: '10.0.0.1', prefix_length: '24' })] })),
    ).toBeNull()
  })

  it('без типа устройства — первая проверка, остальное не смотрится', () => {
    const issue = validateDeviceDraft(draft({ form: { device_type_id: '', serial_number: '' } }))
    expect(issue).toEqual({ message: 'Укажите тип устройства.' })
  })

  it('серийный номер из пробелов — ошибка', () => {
    expect(validateDeviceDraft(draft({ form: { device_type_id: 't-sw', serial_number: '   ' } }))).toEqual({ message: 'Укажите серийный номер.' })
  })

  it('порт без имени — ошибка портов, блок VLAN устройства не раскрывается', () => {
    const issue = validateDeviceDraft(draft({ interfaces: [makeRow({ name: ' ' })] }))
    expect(issue).toEqual({ message: 'У каждого интерфейса должно быть имя.' })
  })

  it('ошибка портов важнее ошибок блока VLAN устройства', () => {
    const issue = validateDeviceDraft(draft({ interfaces: [makeRow({ name: '' })], deviceVlans: [vlanRow({ ip_address: 'нет' })] }))
    expect(issue?.message).toBe('У каждого интерфейса должно быть имя.')
  })

  it('ошибка группы портов (без названия) возвращается как ошибка формы', () => {
    const issue = validateDeviceDraft(draft({ interfaceGroups: [{ ...emptyGroup(''), key: 'g1' }] }))
    expect(issue?.message).toMatch(/групп/i)
    expect(issue?.expandVlanEditor).toBeUndefined()
  })

  it('повтор VLAN устройства — сообщение и просьба раскрыть блок', () => {
    const issue = validateDeviceDraft(draft({ deviceVlans: [vlanRow({ vlan_id: 'v10' }), vlanRow({ vlan_id: 'v10' })] }))
    expect(issue?.expandVlanEditor).toBe(true)
    expect(issue?.message).toContain('10')
  })

  it('некорректный IP строки VLAN устройства: сообщение с адресом и раскрытие блока', () => {
    const issue = validateDeviceDraft(draft({ deviceVlans: [vlanRow({ ip_address: '300.1.1.1', prefix_length: '24' })] }))
    expect(issue).toEqual({ message: 'Некорректный IP-адрес «300.1.1.1» в блоке "VLAN устройства".', expandVlanEditor: true })
  })

  it('некорректный префикс строки VLAN устройства: допустимо 0-32', () => {
    const issue = validateDeviceDraft(draft({ deviceVlans: [vlanRow({ ip_address: '10.0.0.1', prefix_length: '33' })] }))
    expect(issue).toEqual({ message: 'Некорректный префикс «33» в блоке "VLAN устройства" — допустимо 0-32.', expandVlanEditor: true })
  })

  it('пустые IP и префикс строки VLAN устройства допустимы', () => {
    expect(validateDeviceDraft(draft({ deviceVlans: [vlanRow()] }))).toBeNull()
  })

  it('подинтерфейс на VLAN, недоступный устройству, не проходит проверку (допустимые VLAN берутся из portVlanIds)', () => {
    const sub = { key: 's1', name: 'Gi0/1.99', vlan_id: 'v99', is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [] }
    const row = makeRow({ name: 'Gi0/1', vlan_mode: 'trunk', vlan_ids: ['v10'], subinterfaces: [sub] })
    expect(validateDeviceDraft(draft({ interfaces: [row] }))?.message).toContain('не назначен устройству')
    expect(validateDeviceDraft(draft({ interfaces: [row], portVlanIds: new Set(['v10', 'v99']) }))?.message).not.toContain('не назначен устройству')
  })

  it('подключение порта без соседа — ошибка подключений (изменённое относительно baseline)', () => {
    const connection = { peer_device_id: '', peer_interface_id: '', peer_row_key: '', connection_type_id: '', description: '' }
    const issue = validateDeviceDraft(draft({ interfaces: [makeRow({ name: 'Gi0/1', connection })] }))
    expect(issue?.message).toContain('выберите устройство и порт')
    expect(issue?.expandVlanEditor).toBeUndefined()
  })
})
