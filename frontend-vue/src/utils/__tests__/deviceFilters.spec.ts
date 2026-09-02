import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { filterHostDevices } from '../deviceFilters'
import { useCatalogsStore } from '../../stores/catalogs'
import type { Device } from '../../api/types'

function makeDevice(id: string, deviceTypeId: string): Device {
  return { id, device_type_id: deviceTypeId } as Device
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('filterHostDevices', () => {
  it('оставляет только устройства с типом, похожим на сервер или СХД', () => {
    const catalogs = useCatalogsStore()
    catalogs.items['device-types'] = [
      { id: 'dt-server', name: 'Сервер' },
      { id: 'dt-storage', name: 'Система хранения данных' },
      { id: 'dt-switch', name: 'Коммутатор' },
    ]
    const devices = [makeDevice('d1', 'dt-server'), makeDevice('d2', 'dt-storage'), makeDevice('d3', 'dt-switch')]

    const result = filterHostDevices(devices, catalogs)

    expect(result.map((d) => d.id)).toEqual(['d1', 'd2'])
  })

  it('распознаёт английское "storage" в названии типа', () => {
    const catalogs = useCatalogsStore()
    catalogs.items['device-types'] = [{ id: 'dt-nas', name: 'NAS Storage Array' }]
    const devices = [makeDevice('d1', 'dt-nas')]

    expect(filterHostDevices(devices, catalogs).map((d) => d.id)).toEqual(['d1'])
  })

  it('возвращает пустой список, если подходящих устройств нет', () => {
    const catalogs = useCatalogsStore()
    catalogs.items['device-types'] = [{ id: 'dt-switch', name: 'Коммутатор' }]
    const devices = [makeDevice('d1', 'dt-switch')]

    expect(filterHostDevices(devices, catalogs)).toEqual([])
  })
})
