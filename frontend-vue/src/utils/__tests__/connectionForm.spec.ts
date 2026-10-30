import { describe, expect, it } from 'vitest'
import { connection, device, iface } from '../../composables/__tests__/connectionFormTestkit'
import {
  connectionDeviceLabel,
  connectionFormFromSource,
  connectionPayload,
  countDeviceInterfaces,
  emptyConnectionForm,
  freeInterfacesForDevice,
  validateConnectionForm,
} from '../connectionForm'

const interfaces = [iface('if-a', 'dev-1'), iface('if-b', 'dev-2'), iface('if-c', 'dev-2')]

describe('emptyConnectionForm', () => {
  it('пустая форма: ничего не выбрано, подключение активно', () => {
    expect(emptyConnectionForm()).toEqual({
      sourceDeviceId: '',
      source_interface_id: '',
      destinationDeviceId: '',
      destination_interface_id: '',
      connection_type_id: '',
      is_active: true,
      description: '',
    })
  })

  it('каждый вызов возвращает новый объект', () => {
    expect(emptyConnectionForm()).not.toBe(emptyConnectionForm())
  })
})

describe('connectionFormFromSource', () => {
  it('редактирование: порты, тип, активность и описание из подключения; устройства — по каталогу портов', () => {
    const form = connectionFormFromSource(connection({ is_active: false, description: 'магистраль' }), null, interfaces)
    expect(form).toEqual({
      sourceDeviceId: 'dev-1',
      source_interface_id: 'if-a',
      destinationDeviceId: 'dev-2',
      destination_interface_id: 'if-b',
      connection_type_id: 'ct-1',
      is_active: false,
      description: 'магистраль',
    })
  })

  it('пустое описание подключения (null) становится пустой строкой', () => {
    expect(connectionFormFromSource(connection({ description: null }), null, interfaces).description).toBe('')
  })

  it('редактирование важнее подсказки схемы', () => {
    const form = connectionFormFromSource(connection(), { sourceInterfaceId: 'if-c', destinationInterfaceId: 'if-a' }, interfaces)
    expect(form.source_interface_id).toBe('if-a')
    expect(form.destination_interface_id).toBe('if-b')
  })

  it('создание с подсказкой схемы: подставляет только порты и их устройства', () => {
    const form = connectionFormFromSource(null, { sourceInterfaceId: 'if-c', destinationInterfaceId: 'if-a' }, interfaces)
    expect(form).toEqual({
      ...emptyConnectionForm(),
      sourceDeviceId: 'dev-2',
      source_interface_id: 'if-c',
      destinationDeviceId: 'dev-1',
      destination_interface_id: 'if-a',
    })
  })

  it('без подключения и подсказки — пустая форма', () => {
    expect(connectionFormFromSource(null, null, interfaces)).toEqual(emptyConnectionForm())
    expect(connectionFormFromSource(null, undefined, interfaces)).toEqual(emptyConnectionForm())
  })

  it('порта нет в каталоге: идентификатор порта сохраняется, устройство пустое', () => {
    const form = connectionFormFromSource(connection({ source_interface_id: 'if-gone' }), null, interfaces)
    expect(form.source_interface_id).toBe('if-gone')
    expect(form.sourceDeviceId).toBe('')
  })
})

describe('connectionPayload', () => {
  const filled = {
    ...emptyConnectionForm(),
    sourceDeviceId: 'dev-1',
    source_interface_id: 'if-a',
    destinationDeviceId: 'dev-2',
    destination_interface_id: 'if-b',
    connection_type_id: 'ct-1',
  }

  it('в запрос уходят порты, тип, активность и описание — без служебных полей устройств', () => {
    expect(connectionPayload({ ...filled, description: 'x' })).toEqual({
      source_interface_id: 'if-a',
      destination_interface_id: 'if-b',
      connection_type_id: 'ct-1',
      is_active: true,
      description: 'x',
    })
  })

  it('пустое описание уходит как null', () => {
    expect(connectionPayload(filled).description).toBeNull()
  })
})

describe('validateConnectionForm', () => {
  const ok = { source_interface_id: 'if-a', destination_interface_id: 'if-b', connection_type_id: 'ct-1' }

  it('корректная форма — null', () => {
    expect(validateConnectionForm(ok)).toBeNull()
  })

  it.each([
    [{ ...ok, source_interface_id: '' }, 'Выберите исходное устройство и его порт.'],
    [{ ...ok, destination_interface_id: '' }, 'Выберите конечное устройство и его порт.'],
    [{ ...ok, destination_interface_id: 'if-a' }, 'Исходный и конечный порт не могут совпадать.'],
    [{ ...ok, connection_type_id: '' }, 'Выберите тип физической линии связи.'],
  ])('первая ошибка: %#', (form, message) => {
    expect(validateConnectionForm(form)).toBe(message)
  })

  it('порядок проверок: сначала исходный порт, затем конечный, совпадение, тип', () => {
    expect(validateConnectionForm({ source_interface_id: '', destination_interface_id: '', connection_type_id: '' })).toBe(
      'Выберите исходное устройство и его порт.',
    )
    expect(validateConnectionForm({ source_interface_id: 'if-a', destination_interface_id: '', connection_type_id: '' })).toBe(
      'Выберите конечное устройство и его порт.',
    )
    expect(validateConnectionForm({ source_interface_id: 'if-a', destination_interface_id: 'if-a', connection_type_id: '' })).toBe(
      'Исходный и конечный порт не могут совпадать.',
    )
  })
})

describe('connectionDeviceLabel', () => {
  it('системное имя, а без него серийный номер', () => {
    expect(connectionDeviceLabel(device('d', 'srv-01', 'SN-9'))).toBe('srv-01')
    expect(connectionDeviceLabel(device('d', '', 'SN-9'))).toBe('SN-9')
    expect(connectionDeviceLabel(device('d', null, 'SN-9'))).toBe('SN-9')
  })
})

describe('freeInterfacesForDevice', () => {
  it('устройство не выбрано — пустой список', () => {
    expect(freeInterfacesForDevice(interfaces, new Set(), '', '')).toEqual([])
  })

  it('только порты выбранного устройства, в исходном порядке', () => {
    expect(freeInterfacesForDevice(interfaces, new Set(), 'dev-2', '').map((i) => i.id)).toEqual(['if-b', 'if-c'])
  })

  it('занятые активным подключением порты исключены', () => {
    expect(freeInterfacesForDevice(interfaces, new Set(['if-b']), 'dev-2', '').map((i) => i.id)).toEqual(['if-c'])
  })

  it('выбранный сейчас порт остаётся, даже если он занят (редактирование собственного подключения)', () => {
    expect(freeInterfacesForDevice(interfaces, new Set(['if-b', 'if-c']), 'dev-2', 'if-b').map((i) => i.id)).toEqual(['if-b'])
  })
})

describe('countDeviceInterfaces', () => {
  it('считает порты устройства без фильтра по занятости', () => {
    expect(countDeviceInterfaces(interfaces, 'dev-2')).toBe(2)
    expect(countDeviceInterfaces(interfaces, 'dev-9')).toBe(0)
  })

  it('устройство не выбрано — 0', () => {
    expect(countDeviceInterfaces(interfaces, '')).toBe(0)
  })
})
