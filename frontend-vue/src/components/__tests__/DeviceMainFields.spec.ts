import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { h, nextTick, reactive } from 'vue'
import type { CatalogItem } from '../../api/types'
import { useCatalogsStore } from '../../stores/catalogs'
import { emptyDeviceForm } from '../../utils/deviceForm'
import DeviceIconPicker from '../DeviceIconPicker.vue'
import DeviceMainFields from '../DeviceMainFields.vue'
import QuickAddButton from '../QuickAddButton.vue'

const SELECT = { typeModel: 0, os: 1, embeddedOs: 2, building: 3, room: 4, rack: 5 } as const

beforeEach(() => {
  setActivePinia(createPinia())
  useCatalogsStore().items = {
    buildings: [{ id: 'b1', name: 'Корпус 1' }, { id: 'b2', name: 'Корпус 2' }],
    rooms: [{ id: 'r1', name: 'Серверная', building_id: 'b1' }, { id: 'r2', name: 'Склад', building_id: 'b1' }, { id: 'r3', name: 'ЦОД', building_id: 'b2' }],
    racks: [{ id: 'k1', name: 'Стойка 1', room_id: 'r1' }, { id: 'k2', name: 'Стойка 2', room_id: 'r3' }],
    'device-types': [{ id: 't-sw', name: 'Коммутатор' }, { id: 't-srv', name: 'Сервер' }],
    manufacturers: [{ id: 'm-cisco', name: 'Cisco' }],
    'device-models': [{ id: 'mod-1', model: 'WS-C2960', name: '', manufacturer_id: 'm-cisco', device_type_id: 't-sw' }],
    'operating-systems': [{ id: 'os-1', name: 'Windows Server', version: '2022' }],
    'embedded-os': [{ id: 'eos-1', name: 'IOS', version: '15.2' }],
  } as unknown as ReturnType<typeof useCatalogsStore>['items']
})

function mountFields(patch: Partial<ReturnType<typeof emptyDeviceForm>> = {}) {
  const form = reactive({ ...emptyDeviceForm(), ...patch })
  // Фрагмент должен встать прямо в контейнер-сетку родителя, поэтому монтируем его внутрь обычного div
  const wrapper = mount({ render: () => h('div', { class: 'host' }, [h(DeviceMainFields, { modelValue: form })]) }, { global: { stubs: { QuickAddButton: true, DeviceIconPicker: true } } })
  return { form, wrapper }
}
type Wrapper = ReturnType<typeof mountFields>['wrapper']

const selects = (wrapper: Wrapper) => wrapper.findAll('.searchable-select')
// Список опций SearchableSelect рисуется только у открытого поля — открываем фокусом
async function optionTexts(wrapper: Wrapper, which: number) {
  await selects(wrapper)[which].find('input').trigger('focus')
  const texts = selects(wrapper)[which].findAll('.ss-option').map((o) => o.text())
  await selects(wrapper)[which].find('input').trigger('blur')
  return texts
}
async function choose(wrapper: Wrapper, which: number, label: string) {
  const select = selects(wrapper)[which]
  await select.find('input').trigger('focus')
  await select.findAll('.ss-option').find((o) => o.text() === label)!.trigger('mousedown')
  await nextTick()
}
const quickAdd = (wrapper: Wrapper, resource: string) => wrapper.findAllComponents(QuickAddButton).find((b) => b.props('resource') === resource)!
const inputOf = (wrapper: Wrapper, label: string) => wrapper.findAll('label').find((l) => l.find('span').text().startsWith(label))!.find('input, textarea')

describe('DeviceMainFields: разметка', () => {
  it('поля идут в порядке формы и встают прямо в контейнер родителя — без обёртки', () => {
    const { wrapper } = mountFields()
    const direct = Array.from((wrapper.element as HTMLElement).children)
    const labels = direct.filter((el) => el.tagName === 'LABEL').map((el) => el.querySelector('span')!.textContent)
    expect(labels).toEqual([
      'Тип / производитель / модель *',
      'Серийный номер *',
      'Системное имя',
      'Операционная система',
      'Встроенная ОС (для сетевого оборудования)',
      'Отправляет события в SIEM',
      'Здание',
      'Помещение',
      'Стойка',
      'Позиция в стойке',
      'Описание',
    ])
    expect(direct).toHaveLength(13)
    expect(Array.from(direct[0].classList)).toEqual(expect.arrayContaining(['field', 'field-wide']))
    expect(Array.from(direct[11].classList)).toEqual(expect.arrayContaining(['oac-cert-block', 'field-wide']))
    expect(Array.from(direct[12].classList)).toEqual(expect.arrayContaining(['field', 'field-wide']))
  })

  it('обязательные поля и ограничения длины сохранены', () => {
    const { wrapper } = mountFields()
    expect(inputOf(wrapper, 'Серийный номер').attributes()).toMatchObject({ required: '', maxlength: '255', type: 'text' })
    expect(inputOf(wrapper, 'Системное имя').attributes('maxlength')).toBe('255')
    expect(inputOf(wrapper, 'Позиция в стойке').attributes()).toMatchObject({ maxlength: '50', placeholder: 'напр. 12U' })
    expect(inputOf(wrapper, 'Описание').attributes('maxlength')).toBe('2000')
  })

  it('поля показывают значения формы', () => {
    const { wrapper } = mountFields({ serial_number: 'SN-1', system_name: 'sw-01', rack_position: '12U', description: 'ядро', siem_enabled: true, oac_certificate_number: 'ОАЦ-1', oac_certificate_registry_date: '2026-01-31' })
    expect((inputOf(wrapper, 'Серийный номер').element as HTMLInputElement).value).toBe('SN-1')
    expect((inputOf(wrapper, 'Системное имя').element as HTMLInputElement).value).toBe('sw-01')
    expect((inputOf(wrapper, 'Позиция в стойке').element as HTMLInputElement).value).toBe('12U')
    expect((inputOf(wrapper, 'Описание').element as HTMLTextAreaElement).value).toBe('ядро')
    expect((inputOf(wrapper, 'Отправляет события в SIEM').element as HTMLInputElement).checked).toBe(true)
    expect((inputOf(wrapper, 'Регистрационный номер').element as HTMLInputElement).value).toBe('ОАЦ-1')
    expect((inputOf(wrapper, 'Дата внесения').element as HTMLInputElement).value).toBe('2026-01-31')
  })
})

describe('DeviceMainFields: правка пишет прямо в объект формы родителя', () => {
  it('текстовые поля обрезают пробелы по краям', async () => {
    const { form, wrapper } = mountFields()
    await inputOf(wrapper, 'Серийный номер').setValue('  SN-777  ')
    await inputOf(wrapper, 'Системное имя').setValue(' sw-x ')
    await inputOf(wrapper, 'Позиция в стойке').setValue(' U5 ')
    await inputOf(wrapper, 'Описание').setValue('  текст  ')
    await inputOf(wrapper, 'Регистрационный номер').setValue(' ОАЦ-9 ')
    expect(form).toMatchObject({ serial_number: 'SN-777', system_name: 'sw-x', rack_position: 'U5', description: 'текст', oac_certificate_number: 'ОАЦ-9' })
  })

  it('SIEM и дата реестра', async () => {
    const { form, wrapper } = mountFields()
    await inputOf(wrapper, 'Отправляет события в SIEM').setValue(true)
    await inputOf(wrapper, 'Дата внесения').setValue('2026-03-04')
    expect(form.siem_enabled).toBe(true)
    expect(form.oac_certificate_registry_date).toBe('2026-03-04')
  })

  it('значение, изменённое снаружи (загрузка устройства), сразу видно в поле', async () => {
    const { form, wrapper } = mountFields()
    Object.assign(form, { serial_number: 'SN-LOADED', building_id: 'b1' })
    await nextTick()
    expect((inputOf(wrapper, 'Серийный номер').element as HTMLInputElement).value).toBe('SN-LOADED')
    expect((selects(wrapper)[SELECT.building].find('input').element as HTMLInputElement).value).toBe('Корпус 1')
  })
})

describe('DeviceMainFields: справочники и каскад', () => {
  it('списки здания, ОС и встроенной ОС берутся из справочников', async () => {
    const { wrapper } = mountFields()
    expect(await optionTexts(wrapper, SELECT.building)).toEqual(['Корпус 1', 'Корпус 2'])
    expect(await optionTexts(wrapper, SELECT.os)).toEqual(['Windows Server 2022'])
    expect(await optionTexts(wrapper, SELECT.embeddedOs)).toEqual(['IOS 15.2'])
  })

  it('помещение и стойка недоступны, пока не выбраны здание и помещение', async () => {
    const { form, wrapper } = mountFields()
    const disabled = (which: number) => (selects(wrapper)[which].find('input').element as HTMLInputElement).disabled
    expect(disabled(SELECT.room)).toBe(true)
    expect(disabled(SELECT.rack)).toBe(true)
    form.building_id = 'b1'
    await nextTick()
    expect(disabled(SELECT.room)).toBe(false)
    expect(disabled(SELECT.rack)).toBe(true)
    form.room_id = 'r1'
    await nextTick()
    expect(disabled(SELECT.rack)).toBe(false)
  })

  it('выбор здания сужает список помещений; смена здания сбрасывает чужое помещение и не трогает подходящее', async () => {
    const { form, wrapper } = mountFields({ building_id: 'b1', room_id: 'r1' })
    await nextTick()
    expect(await optionTexts(wrapper, SELECT.room)).toEqual(['Серверная', 'Склад'])
    await choose(wrapper, SELECT.building, 'Корпус 2')
    expect(form.building_id).toBe('b2')
    expect(form.room_id).toBe('')
    expect(await optionTexts(wrapper, SELECT.room)).toEqual(['ЦОД'])
  })

  it('стойка выбирается из стоек выбранного помещения и пишется в rack_id, а не в другие поля', async () => {
    const { form, wrapper } = mountFields({ building_id: 'b1', room_id: 'r1' })
    await nextTick()
    expect(await optionTexts(wrapper, SELECT.rack)).toEqual(['Стойка 1'])
    await choose(wrapper, SELECT.rack, 'Стойка 1')
    expect(form).toMatchObject({ building_id: 'b1', room_id: 'r1', rack_id: 'k1' })
  })

  it('выбор модели переносит в форму тип и производителя', async () => {
    const { form, wrapper } = mountFields()
    await choose(wrapper, SELECT.typeModel, 'Cisco WS-C2960')
    expect(form).toMatchObject({ model_id: 'mod-1', device_type_id: 't-sw', manufacturer_id: 'm-cisco' })
  })
})

describe('DeviceMainFields: быстрое добавление («+»)', () => {
  it('у каждого справочника своя кнопка с названием ресурса', () => {
    const { wrapper } = mountFields()
    const buttons = wrapper.findAllComponents(QuickAddButton).map((b) => [b.props('resource'), b.props('title')])
    expect(buttons).toEqual([
      ['device-models', 'Модель устройства'],
      ['operating-systems', 'Операционная система'],
      ['embedded-os', 'Встроенная ОС'],
      ['buildings', 'Здание'],
      ['rooms', 'Помещение'],
      ['racks', 'Стойка'],
    ])
  })

  it('созданные ОС, встроенная ОС и здание сразу выбираются', async () => {
    const { form, wrapper } = mountFields()
    quickAdd(wrapper, 'operating-systems').vm.$emit('created', { id: 'os-9' })
    quickAdd(wrapper, 'embedded-os').vm.$emit('created', { id: 'eos-9' })
    quickAdd(wrapper, 'buildings').vm.$emit('created', { id: 'b9' })
    expect(form).toMatchObject({ operating_system_id: 'os-9', embedded_os_id: 'eos-9', building_id: 'b9' })
  })

  it('созданная модель подставляет себя, тип и производителя', () => {
    const { form, wrapper } = mountFields()
    quickAdd(wrapper, 'device-models').vm.$emit('created', { id: 'mod-9', device_type_id: 't-srv', manufacturer_id: 'm-cisco' })
    expect(form).toMatchObject({ model_id: 'mod-9', device_type_id: 't-srv', manufacturer_id: 'm-cisco' })
  })

  it('созданное помещение выбирает и своё здание; созданная стойка — своё помещение и здание', async () => {
    const { form, wrapper } = mountFields()
    useCatalogsStore().items['rooms'] = [...(useCatalogsStore().items['rooms'] as unknown as Record<string, unknown>[]), { id: 'r9', name: 'Новое', building_id: 'b2' }] as unknown as CatalogItem[]
    quickAdd(wrapper, 'rooms').vm.$emit('created', { id: 'r9', building_id: 'b2' })
    await nextTick()
    expect(form).toMatchObject({ building_id: 'b2', room_id: 'r9' })

    quickAdd(wrapper, 'racks').vm.$emit('created', { id: 'k2', room_id: 'r3' })
    expect(form).toMatchObject({ building_id: 'b2', room_id: 'r3', rack_id: 'k2' })
  })

  it('окно помещения получает выбранное здание, окно стойки — помещение и сужение списка помещений по зданию', async () => {
    const { form, wrapper } = mountFields()
    expect(quickAdd(wrapper, 'rooms').props('initialValues')).toBeUndefined()
    expect(quickAdd(wrapper, 'racks').props('initialValues')).toBeUndefined()

    Object.assign(form, { building_id: 'b1', room_id: 'r1' })
    await nextTick()
    expect(quickAdd(wrapper, 'rooms').props('initialValues')).toEqual({ building_id: 'b1' })
    expect(quickAdd(wrapper, 'racks').props('initialValues')).toEqual({ room_id: 'r1' })
    expect(quickAdd(wrapper, 'racks').props('fkScope')).toEqual({ room_id: { field: 'building_id', value: 'b1' } })
  })
})

describe('DeviceMainFields: иконка диаграммы', () => {
  it('пустая иконка передаётся как null, выбор и сброс пишутся в форму (сброс — пустой строкой)', async () => {
    const { form, wrapper } = mountFields()
    const picker = wrapper.findComponent(DeviceIconPicker)
    expect(picker.props('modelValue')).toBeNull()

    picker.vm.$emit('update:modelValue', 'icon-1')
    expect(form.diagram_icon_id).toBe('icon-1')
    await nextTick()
    expect(wrapper.findComponent(DeviceIconPicker).props('modelValue')).toBe('icon-1')

    picker.vm.$emit('update:modelValue', null)
    expect(form.diagram_icon_id).toBe('')
  })
})

