import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceTableRow from '../DeviceTableRow.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { declaration, readStyles, ruleBody } from '../../__tests__/cssSource'
import type { Device } from '../../api/types'

// UI-06 и UI-14 (ревью merge/review-2158-executors): строка таблицы определялась самой длинной ячейкой («Здание · помещение»),
// а серийные номера переносились посреди значения («SN-00011-/XXXX»).

function device(overrides: Partial<Device> = {}): Device {
  return {
    id: 'd1',
    device_type_id: 'dt-1',
    manufacturer_id: null,
    model_id: null,
    serial_number: 'SN-00011-XXXX',
    system_name: 'sw-1',
    operating_system_id: null,
    embedded_os_id: null,
    siem_enabled: true,
    building_id: 'b-1',
    room_id: 'r-1',
    rack_id: null,
    rack_position: null,
    description: null,
    diagram_icon_id: null,
    oac_certificate_number: null,
    oac_certificate_registry_date: null,
    stack_id: null,
    stack_name: null,
    stack_position: null,
    management_interface: '',
    management_ips: '',
    interface_count: 0,
    embedded_os_name: '',
    embedded_os_version: '',
    vlan_summary: '',
    ...overrides,
  } as Device
}

const LONG_BUILDING = 'Главный центр обработки данных федерального значения имени академика Сергея Павловича Королёва (корпус №3, строение 7Б)'
const LONG_ROOM = 'Помещение с очень длинным названием для проверки переноса текста в таблице'

beforeEach(() => {
  setActivePinia(createPinia())
  const catalogs = useCatalogsStore()
  catalogs.items['device-types'] = [{ id: 'dt-1', name: 'Коммутатор' }]
  catalogs.items['buildings'] = [{ id: 'b-1', name: LONG_BUILDING }]
  catalogs.items['rooms'] = [{ id: 'r-1', name: LONG_ROOM }]
  catalogs.loaded = true
})

function mountRow(d: Device) {
  // <tr> нельзя монтировать вне таблицы — оборачиваем, как это делает DevicesView.
  return mount({ components: { DeviceTableRow }, props: ['d'], template: '<table><tbody><DeviceTableRow :device="d" /></tbody></table>' }, { props: { d } })
}

describe('DeviceTableRow.vue — серийный номер (UI-14)', () => {
  it('значение лежит в одной ячейке serial-cell, а полный номер доступен в title', () => {
    const wrapper = mountRow(device({ serial_number: 'SN-00011-XXXXXXX' }))

    const clip = wrapper.find('td.serial-cell .clip')
    expect(clip.text()).toBe('SN-00011-XXXXXXX')
    expect(clip.attributes('title')).toBe('SN-00011-XXXXXXX')
  })

  it('стили: ячейка не переносит строку, очень длинный номер обрезается многоточием по ширине 28ch', () => {
    const styles = readStyles('src/components/DeviceTableRow.vue')

    expect(declaration(ruleBody(styles, '.serial-cell'), 'white-space')).toBe('nowrap')
    expect(declaration(ruleBody(styles, '.clip'), 'text-overflow')).toBe('ellipsis')
    expect(declaration(ruleBody(styles, '.clip'), 'white-space')).toBe('nowrap')
    expect(declaration(ruleBody(styles, '.serial-cell .clip'), 'max-width')).toBe('28ch')
  })
})

describe('DeviceTableRow.vue — длинные значения не раздувают строку (UI-06)', () => {
  it('«Здание · помещение» — одна однострочная ячейка с полным текстом в title', () => {
    const wrapper = mountRow(device())

    const place = wrapper.find('.clip-place')
    expect(place.text()).toBe(`${LONG_BUILDING} · ${LONG_ROOM}`)
    expect(place.attributes('title')).toBe(`${LONG_BUILDING} · ${LONG_ROOM}`)
  })

  it('без здания и помещения показывается прочерк, как и до правки', () => {
    const wrapper = mountRow(device({ building_id: null, room_id: null }))

    expect(wrapper.find('.clip-place').text()).toBe('—')
  })

  it('помещение без здания показывается без «—» перед ним; пустое место и модель — прочерк без подсказки', () => {
    const roomOnly = mountRow(device({ building_id: null, room_id: 'r-1' }))
    expect(roomOnly.find('.clip-place').text()).toBe(LONG_ROOM)

    const empty = mountRow(device({ building_id: null, room_id: null, manufacturer_id: null, model_id: null }))
    expect(empty.find('.clip-place').attributes('title')).toBeUndefined()
    expect(empty.find('.clip-model').text()).toBe('—')
    expect(empty.find('.clip-model').attributes('title')).toBeUndefined()
  })

  it('имя и описание получают title с полным текстом; без описания блока описания нет', () => {
    const long = 'очень длинное описание '.repeat(10).trim()
    const withDescription = mountRow(device({ description: long, system_name: 'sw-core-moscow-datacenter-building-3-floor-2-rack-12-unit-40-0' }))

    expect(withDescription.find('.devmodel').attributes('title')).toBe(long)
    expect(withDescription.find('.devname').attributes('title')).toBe('sw-core-moscow-datacenter-building-3-floor-2-rack-12-unit-40-0')
    expect(
      mountRow(device({ description: null }))
        .find('.devmodel')
        .exists(),
    ).toBe(false)
  })

  it('стили: описание обрезается двумя строками, имя переносится по любому символу и не шире 300px', () => {
    const styles = readStyles('src/components/DeviceTableRow.vue')

    expect(declaration(ruleBody(styles, '.devmodel'), '-webkit-line-clamp')).toBe('2')
    expect(declaration(ruleBody(styles, '.devmodel'), 'overflow')).toBe('hidden')
    expect(declaration(ruleBody(styles, '.devname'), 'overflow-wrap')).toBe('anywhere')
    expect(declaration(ruleBody(styles, '.devname'), 'max-width')).toBe('300px')
    expect(declaration(ruleBody(styles, '.clip-place'), 'max-width')).toBe('240px')
  })
})
