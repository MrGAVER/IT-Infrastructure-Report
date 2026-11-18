import { describe, it, expect } from 'vitest'
import { deviceModelLabel, devicePlaceLabel } from '../deviceLabels'
import type { DeviceLabelCatalogs } from '../deviceLabels'

/** Заглушка справочников: label по тем же правилам, что у стора (пустой id и неизвестная запись — fallback). */
function fakeCatalogs(items: Record<string, Record<string, Record<string, unknown>>>): DeviceLabelCatalogs {
  const indexOf = ((key: string) => new Map(Object.entries(items[key] ?? {}))) as DeviceLabelCatalogs['indexOf']
  const label = ((key: string, id: string | null | undefined, fallback = '—') => {
    const item = id ? items[key]?.[id] : undefined
    if (!item) return fallback
    return key === 'device-models' ? String(item.model) : String(item.name)
  }) as DeviceLabelCatalogs['label']
  return { indexOf, label }
}

const catalogs = fakeCatalogs({
  manufacturers: { 'mf-1': { name: 'Cisco' } },
  'device-models': { 'dm-1': { model: 'C9300' } },
  buildings: { 'b-1': { name: 'Главный корпус' } },
  rooms: { 'r-1': { name: 'Серверная' } },
})

describe('deviceModelLabel', () => {
  it('«Производитель · модель»', () => {
    expect(deviceModelLabel(catalogs, { manufacturer_id: 'mf-1', model_id: 'dm-1' })).toBe('Cisco · C9300')
  })
  it('задано только одно из двух — только оно, без разделителя', () => {
    expect(deviceModelLabel(catalogs, { manufacturer_id: 'mf-1', model_id: null })).toBe('Cisco')
    expect(deviceModelLabel(catalogs, { manufacturer_id: null, model_id: 'dm-1' })).toBe('C9300')
  })
  it('ничего не задано или записи нет в справочнике — пустая строка, а не «—»', () => {
    expect(deviceModelLabel(catalogs, { manufacturer_id: null, model_id: null })).toBe('')
    expect(deviceModelLabel(catalogs, { manufacturer_id: 'нет-такого', model_id: 'нет-такой' })).toBe('')
  })
})

describe('devicePlaceLabel', () => {
  it('«Здание · помещение»', () => {
    expect(devicePlaceLabel(catalogs, { building_id: 'b-1', room_id: 'r-1' })).toBe('Главный корпус · Серверная')
  })
  it('только здание или только помещение — без висящего разделителя и без «—»', () => {
    expect(devicePlaceLabel(catalogs, { building_id: 'b-1', room_id: null })).toBe('Главный корпус')
    expect(devicePlaceLabel(catalogs, { building_id: null, room_id: 'r-1' })).toBe('Серверная')
  })
  it('здание, которого нет в справочнике, пропускается: помещение остаётся', () => {
    expect(devicePlaceLabel(catalogs, { building_id: 'удалено', room_id: 'r-1' })).toBe('Серверная')
  })
  it('ничего не задано — пустая строка', () => {
    expect(devicePlaceLabel(catalogs, { building_id: null, room_id: null })).toBe('')
  })
})
