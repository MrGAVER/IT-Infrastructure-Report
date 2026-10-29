import { beforeEach, describe, expect, it } from 'vitest'
import { nextTick, reactive } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import type { CatalogItem } from '../../api/types'
import { useCatalogsStore } from '../../stores/catalogs'
import { emptyDeviceForm } from '../../utils/deviceForm'
import { useDeviceFormFields } from '../useDeviceFormFields'

type Items = Record<string, Record<string, unknown>[]>

function seed(items: Items) {
  const catalogs = useCatalogsStore()
  catalogs.items = { ...catalogs.items, ...(items as unknown as Record<string, CatalogItem[]>) } as typeof catalogs.items
}

function setup() {
  const form = reactive(emptyDeviceForm())
  return { form, fields: useDeviceFormFields(form) }
}

beforeEach(() => {
  setActivePinia(createPinia())
  seed({
    buildings: [{ id: 'b1', name: 'Корпус 1' }, { id: 'b2', name: 'Корпус 2' }],
    rooms: [{ id: 'r1', name: 'Серверная', building_id: 'b1' }, { id: 'r2', name: 'Склад', building_id: 'b1' }, { id: 'r3', name: 'ЦОД', building_id: 'b2' }],
    racks: [{ id: 'k1', name: 'Стойка 1', room_id: 'r1' }, { id: 'k2', name: 'Стойка 2', room_id: 'r3' }],
    'device-types': [{ id: 't-sw', name: 'Коммутатор' }, { id: 't-srv', name: 'Сервер' }],
    manufacturers: [{ id: 'm-cisco', name: 'Cisco' }],
    'device-models': [
      { id: 'mod-1', model: 'WS-C2960', name: '', manufacturer_id: 'm-cisco', device_type_id: 't-sw' },
      { id: 'mod-2', model: 'NoVendor', name: '', manufacturer_id: null, device_type_id: 't-srv' },
    ],
    'operating-systems': [{ id: 'os-1', name: 'Windows Server', version: '2022' }],
    'embedded-os': [{ id: 'eos-1', name: 'IOS', version: '' }],
  })
})

describe('опции справочников', () => {
  it('здания, ОС и встроенная ОС: подпись — название и версия', () => {
    const { fields } = setup()
    expect(fields.buildingOptions.value).toEqual([{ value: 'b1', label: 'Корпус 1' }, { value: 'b2', label: 'Корпус 2' }])
    expect(fields.operatingSystemOptions.value).toEqual([{ value: 'os-1', label: 'Windows Server 2022' }])
    expect(fields.embeddedOsOptions.value).toEqual([{ value: 'eos-1', label: 'IOS' }])
  })

  it('помещения: без здания — все, с выбранным зданием — только его', () => {
    const { form, fields } = setup()
    expect(fields.roomOptions.value.map((o) => o.value)).toEqual(['r1', 'r2', 'r3'])
    form.building_id = 'b1'
    expect(fields.roomOptions.value.map((o) => o.value)).toEqual(['r1', 'r2'])
  })

  it('стойки: без помещения — все, с выбранным помещением — только его', () => {
    const { form, fields } = setup()
    expect(fields.rackOptions.value.map((o) => o.value)).toEqual(['k1', 'k2'])
    form.room_id = 'r3'
    expect(fields.rackOptions.value.map((o) => o.value)).toEqual(['k2'])
  })

  it('справочник ещё не загружен — пустые списки, без ошибок', () => {
    setActivePinia(createPinia())
    const { fields } = setup()
    expect(fields.buildingOptions.value).toEqual([])
    expect(fields.roomOptions.value).toEqual([])
    expect(fields.rackOptions.value).toEqual([])
    expect(fields.typeModelOptions.value).toEqual([])
  })
})

describe('каскад здание → помещение → стойка', () => {
  it('смена здания сбрасывает помещение, не относящееся к нему; подходящее остаётся', async () => {
    const { form } = setup()
    form.building_id = 'b1'
    form.room_id = 'r1'
    await nextTick()
    expect(form.room_id).toBe('r1')

    form.building_id = 'b2'
    await nextTick()
    expect(form.room_id).toBe('')
  })

  it('здание сменилось и помещение сброшено: без помещения видны все стойки, поэтому выбранная стойка остаётся', async () => {
    const { form } = setup()
    form.building_id = 'b1'
    form.room_id = 'r1'
    form.rack_id = 'k1'
    await nextTick()
    expect(form.rack_id).toBe('k1')

    form.building_id = 'b2'
    await nextTick()
    await nextTick()
    expect(form.room_id).toBe('')
    expect(form.rack_id).toBe('k1')
  })

  it('смена помещения сбрасывает стойку чужого помещения', async () => {
    const { form } = setup()
    form.room_id = 'r1'
    form.rack_id = 'k1'
    await nextTick()
    form.room_id = 'r3'
    await nextTick()
    expect(form.rack_id).toBe('')
  })

  it('очистка здания помещение не сбрасывает: без здания видны все помещения', async () => {
    const { form } = setup()
    form.building_id = 'b1'
    form.room_id = 'r1'
    await nextTick()
    form.building_id = ''
    await nextTick()
    expect(form.room_id).toBe('r1')
  })

  it('одновременная установка здания, помещения и стойки (загрузка формы) ничего не сбрасывает', async () => {
    const { form } = setup()
    Object.assign(form, { building_id: 'b1', room_id: 'r1', rack_id: 'k1' })
    await nextTick()
    expect(form).toMatchObject({ building_id: 'b1', room_id: 'r1', rack_id: 'k1' })
  })
})

describe('значения по умолчанию для окон быстрого добавления', () => {
  it('помещение получает выбранное здание, стойка — выбранное помещение и сужение списка помещений по зданию', () => {
    const { form, fields } = setup()
    expect(fields.roomQuickAddValues.value).toBeUndefined()
    expect(fields.rackQuickAddValues.value).toBeUndefined()
    expect(fields.rackQuickAddScope.value).toEqual({ room_id: { field: 'building_id', value: '' } })

    form.building_id = 'b1'
    form.room_id = 'r1'
    expect(fields.roomQuickAddValues.value).toEqual({ building_id: 'b1' })
    expect(fields.rackQuickAddValues.value).toEqual({ room_id: 'r1' })
    expect(fields.rackQuickAddScope.value).toEqual({ room_id: { field: 'building_id', value: 'b1' } })
  })
})

describe('поле «Тип / производитель / модель»', () => {
  it('модели сгруппированы по производителю (подпись из справочника), затем типы без модели', () => {
    const { fields } = setup()
    const options = fields.typeModelOptions.value
    expect(options.map((o) => o.value)).toEqual(expect.arrayContaining(['model:mod-1', 'model:mod-2', 'type:t-sw', 'type:t-srv']))
    expect(options.find((o) => o.value === 'model:mod-1')).toMatchObject({ label: 'Cisco WS-C2960', group: 'Cisco', searchText: 'Коммутатор' })
    expect(options.find((o) => o.value === 'model:mod-2')).toMatchObject({ label: 'NoVendor', group: 'Без производителя', searchText: 'Сервер' })
    expect(options.findIndex((o) => o.value === 'type:t-sw')).toBeGreaterThan(options.findIndex((o) => o.value === 'model:mod-2'))
  })

  it('значение берётся из формы: модель важнее типа', () => {
    const { form, fields } = setup()
    expect(fields.typeModelSelection.value).toBe('')
    form.device_type_id = 't-sw'
    expect(fields.typeModelSelection.value).toBe('type:t-sw')
    form.model_id = 'mod-1'
    expect(fields.typeModelSelection.value).toBe('model:mod-1')
  })

  it('выбор модели переносит в форму её тип и производителя', () => {
    const { form, fields } = setup()
    fields.typeModelSelection.value = 'model:mod-1'
    expect(form).toMatchObject({ model_id: 'mod-1', device_type_id: 't-sw', manufacturer_id: 'm-cisco' })
  })

  it('выбор «голого» типа сбрасывает модель и производителя; пустой выбор — всё', () => {
    const { form, fields } = setup()
    fields.typeModelSelection.value = 'model:mod-1'
    fields.typeModelSelection.value = 'type:t-srv'
    expect(form).toMatchObject({ model_id: '', device_type_id: 't-srv', manufacturer_id: '' })
    fields.typeModelSelection.value = undefined
    expect(form).toMatchObject({ model_id: '', device_type_id: '', manufacturer_id: '' })
  })
})

describe('синхронизация формы с записями, созданными быстрым добавлением', () => {
  it('новая модель подставляет себя, свой тип и производителя (нет производителя — пусто)', () => {
    const { form, fields } = setup()
    fields.onModelCreated({ id: 'mod-9', device_type_id: 't-srv', manufacturer_id: 'm-cisco' } as unknown as CatalogItem)
    expect(form).toMatchObject({ model_id: 'mod-9', device_type_id: 't-srv', manufacturer_id: 'm-cisco' })

    fields.onModelCreated({ id: 'mod-10', device_type_id: null, manufacturer_id: null } as unknown as CatalogItem)
    expect(form).toMatchObject({ model_id: 'mod-10', device_type_id: 't-srv', manufacturer_id: '' })
  })

  it('новое помещение выбирает и себя, и своё здание', async () => {
    const { form, fields } = setup()
    // как в QuickAddModal: запись попадает в справочник раньше, чем форма получает событие created
    seed({ rooms: [...(useCatalogsStore().items['rooms'] as unknown as Record<string, unknown>[]), { id: 'r9', name: 'Новое', building_id: 'b2' }] })
    fields.onRoomCreated({ id: 'r9', building_id: 'b2' } as unknown as CatalogItem)
    await nextTick()
    expect(form).toMatchObject({ building_id: 'b2', room_id: 'r9' })
  })

  it('новая стойка выбирает себя, своё помещение и здание этого помещения', () => {
    const { form, fields } = setup()
    fields.onRackCreated({ id: 'k9', room_id: 'r3' } as unknown as CatalogItem)
    expect(form).toMatchObject({ building_id: 'b2', room_id: 'r3', rack_id: 'k9' })
  })

  it('стойка в помещении, которого нет в справочнике: здание не трогается', () => {
    const { form, fields } = setup()
    form.building_id = 'b1'
    fields.onRackCreated({ id: 'k9', room_id: 'r-ghost' } as unknown as CatalogItem)
    expect(form).toMatchObject({ building_id: 'b1', room_id: 'r-ghost', rack_id: 'k9' })
  })
})
