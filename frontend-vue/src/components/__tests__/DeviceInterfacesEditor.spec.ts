import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceInterfacesEditor from '../DeviceInterfacesEditor.vue'
import InterfaceConnectionEditor from '../InterfaceConnectionEditor.vue'
import InterfaceSubinterfacesEditor from '../InterfaceSubinterfacesEditor.vue'
import ScrollableTableWrap from '../ScrollableTableWrap.vue'
import SearchableSelect from '../SearchableSelect.vue'
import type { CatalogItem, InterfaceDraftRow, InterfaceGroupDraft, VLANDefinition } from '../../api/types'
import { useToast } from '../../composables/useToast'
import { emptyGroup } from '../../utils/interfaceGroups'
import { useCatalogsStore } from '../../stores/catalogs'
import { usePreferencesStore } from '../../stores/preferences'
import { groupChange, makePlan, portChange, vlanRef } from '../../utils/__tests__/cascadePlanFixture'
import type { SelfPortCandidate } from '../../utils/interfaceConnections'
import type { VlanModeCascadePlan } from '../../api/vlanModeCascade'

const typeOptions: CatalogItem[] = [{ id: 't-eth', name: 'Ethernet' }]
const speedOptions: CatalogItem[] = [{ id: 's-1g', name: '1 Гбит/с' }]
const vlanOptions: VLANDefinition[] = []

// QuickAddModal.vue телепортируется в document.body — см. QuickAddModal.spec.ts.
function teleportedContent(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function emptyRow(): InterfaceDraftRow {
  return {
    name: '',
    interface_type_id: '',
    mac_address: '',
    speed_id: '',
    is_management: false,
    is_data_transfer: false,
    description: '',
    vlan_ids: [],
    all_vlans: false,
    vlan_mode: 'access',
    ips: [],
    open_ports: [],
  }
}

// Раскрывает панель деталей (VLAN на порту / IP-адреса / описание) для строки с индексом i —
// с п.3.4 они убраны из компактной таблицы под toggle.
async function expandRow(wrapper: ReturnType<typeof mount>, i = 0) {
  await wrapper.findAll('.expand-toggle')[i].trigger('click')
}

// Выбор VLAN trunk-порта вынесен из карточки порта во всплывающее окно (PortVlanPickerModal): открывается кнопкой в
// строке с галочкой «Все VLAN». Чекбоксы отдельных VLAN — только внутри окна.
async function openVlanPicker(wrapper: ReturnType<typeof mount>, i = 0) {
  await wrapper.findAll('.iface-detail .vlan-picker-btn')[i].trigger('click')
}
const pickerVlanChecks = (wrapper: ReturnType<typeof mount>) => wrapper.findAll('.vlan-picker-modal .vlan-check:not(.vlan-check-all) input[type="checkbox"]')

// Access-порт: VLAN выбирается в SearchableSelect — фокус на поле и mousedown по опции, как у пользователя.
async function pickAccessVlan(wrapper: ReturnType<typeof mount>, labelPart: string, i = 0) {
  const select = wrapper.findAll('.iface-detail .vlan-block .searchable-select')[i]
  await select.find('input').trigger('focus')
  const option = select.findAll('.ss-option').find((o) => o.text().includes(labelPart))
  if (!option) throw new Error(`VLAN «${labelPart}» нет в списке выбора`)
  await option.trigger('mousedown')
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  // generate() теперь спрашивает подтверждение, если в таблице уже есть данные (п.3.3) —
  // jsdom не реализует window.confirm, поэтому по умолчанию мокаем "пользователь согласился";
  // тесты на отмену явно переопределяют это на vi.fn(() => false).
  vi.stubGlobal(
    'confirm',
    vi.fn(() => true),
  )
})

describe('DeviceInterfacesEditor.vue', () => {
  it('показывает подсказку, если интерфейсы не добавлены', () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })
    expect(wrapper.text()).toContain('Интерфейсы не добавлены')
  })

  it('добавляет пустую строку по клику на "+ Интерфейс" (пустой список)', async () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })
    await wrapper.find('.empty button.btn-secondary').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([emptyRow()])
  })

  // п.3.5: кнопка "+ Интерфейс" стоит в шапке списка/таблицы, а не среди полей генератора.
  // Фикс п.1.3.4: у генератора была ОДНА кнопка "Сгенерировать" + галочка "Заменить все порты"
  // вместо прежних двух кнопок ("Сгенерировать"/"Дополнить") — обе внутри .generator, это не
  // регресс п.3.5.
  it('п.3.5: "+ Интерфейс" находится в шапке списка, а не в блоке генератора', async () => {
    const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1' }]
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })

    const generatorButtons = wrapper.findAll('.generator button.btn-secondary').map((b) => b.text())
    expect(generatorButtons).toEqual(['Сгенерировать'])
    expect(wrapper.find('.iface-list-head button.btn-secondary').exists()).toBe(true) // "+ Интерфейс" — отдельно, в шапке

    await wrapper.find('.iface-list-head button.btn-secondary').trigger('click')
    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toHaveLength(2)
  })

  it('генерирует интерфейсы по шаблону имени', async () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })

    const inputs = wrapper.findAll('.generator input')
    await inputs[0].setValue('3') // Количество
    await inputs[2].setValue('eth{n}') // Шаблон имени (inputs[1] теперь "Начать нумерацию с", фикс п.1.3.3)
    await wrapper.find('.generator select').setValue('t-eth') // Тип по умолчанию
    await wrapper.find('.generator button.btn-secondary').trigger('click') // Сгенерировать

    const emitted = wrapper.emitted('update:modelValue')!
    const rows = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
    expect(rows.map((r) => r.name)).toEqual(['eth1', 'eth2', 'eth3'])
    expect(rows.every((r) => r.interface_type_id === 't-eth')).toBe(true)
    expect(confirm).not.toHaveBeenCalled() // список был пуст — спрашивать не о чем
  })

  it('в режиме "Заменить все порты" генерация сохраняет id и IP уже существующего интерфейса по индексу', async () => {
    const existing: InterfaceDraftRow[] = [
      {
        id: 'if-1',
        name: 'old-name',
        interface_type_id: '',
        mac_address: '',
        speed_id: '',
        is_management: true,
        is_data_transfer: false,
        description: '',
        vlan_ids: ['vlan-1'],
        vlan_mode: 'trunk',
        ips: [{ id: 'ip-1', ip_address: '10.0.0.1', prefix_length: '24', purpose: '' }],
        open_ports: [],
      },
    ]
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: existing, typeOptions, speedOptions, vlanOptions } })

    await wrapper.find('.replace-all-check input').setValue(true)
    await wrapper.find('.generator button.btn-secondary').trigger('click') // Сгенерировать с количеством по умолчанию (1)

    expect(confirm).toHaveBeenCalled() // "Заменить все порты" включена и список непуст — подтверждение обязательно
    const emitted = wrapper.emitted('update:modelValue')!
    const rows = emitted[0][0] as InterfaceDraftRow[]
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ id: 'if-1', name: 'eth1', is_management: true, vlan_ids: ['vlan-1'], ips: existing[0].ips })
  })

  describe('фикс п.1.3.3: нумерация с произвольного начального номера ("Начать нумерацию с")', () => {
    it('пустое поле — прежнее поведение (замена начинает с 1)', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })
      await wrapper.find('.generator input[type="number"]').setValue('3') // Количество
      await wrapper.find('.generator button.btn-secondary').trigger('click')

      const rows = wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[]
      expect(rows.map((r) => r.name)).toEqual(['eth1', 'eth2', 'eth3'])
    })

    it('в режиме "Заменить все порты" явный номер задаёт первый номер диапазона — "Количество: 20" + "Начать с: 5" даёт порты 5-24', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })
      await wrapper.find('.replace-all-check input').setValue(true)
      await wrapper.find('.generator input[type="number"]').setValue('20') // Количество
      await wrapper.findAll('.generator input')[1].setValue('5') // Начать нумерацию с
      await wrapper.find('.generator input[type="text"]').setValue('GigabitEthernet0/{n}') // Шаблон имени
      await wrapper.find('.generator button.btn-secondary').trigger('click')

      const rows = wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[]
      expect(rows).toHaveLength(20)
      expect(rows[0].name).toBe('GigabitEthernet0/5')
      expect(rows[19].name).toBe('GigabitEthernet0/24')
    })

    it('в режиме "Дополнить" (без галочки) явный номер переопределяет продолжение от текущего количества строк', async () => {
      const rows: InterfaceDraftRow[] = [
        { ...emptyRow(), name: 'eth1' },
        { ...emptyRow(), name: 'eth2' },
      ]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })
      // Без "Начать с" новые строки продолжили бы с eth3 — с явным значением начинают с eth10.
      await wrapper.find('.generator input[type="number"]').setValue('2') // Количество
      await wrapper.findAll('.generator input')[1].setValue('10') // Начать нумерацию с
      await wrapper.find('.generator button.btn-secondary').trigger('click')

      const result = wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[]
      expect(result.map((r) => r.name)).toEqual(['eth1', 'eth2', 'eth10', 'eth11'])
    })

    it('нечисловой ввод в поле "Начать нумерацию с" не ломает генерацию (браузер сам не пускает нечисло в number-input, но проверка в resolveStartNumber() — на случай программной установки значения)', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })
      await wrapper.find('.generator input[type="number"]').setValue('2') // Количество
      const startInput = wrapper.findAll('.generator input')[1].element as HTMLInputElement
      startInput.value = 'abc'
      await startInput.dispatchEvent(new Event('input'))
      await wrapper.find('.generator button.btn-secondary').trigger('click')

      const rows = wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[]
      expect(rows.map((r) => r.name)).toEqual(['eth1', 'eth2'])
    })
  })

  describe('фикс п.1.3.4: галочка "Заменить все порты" и предупреждение перед заменой', () => {
    it('без галочки (по умолчанию) кнопка добавляет новые интерфейсы, не спрашивая подтверждения — даже если список уже не пуст', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth0' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })
      expect((wrapper.find('.replace-all-check input').element as HTMLInputElement).checked).toBe(false)

      await wrapper.find('.generator input[type="number"]').setValue('1')
      await wrapper.find('.generator button.btn-secondary').trigger('click')

      expect(confirm).not.toHaveBeenCalled()
      const result = wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[]
      expect(result).toHaveLength(2)
      expect(result[0]).toMatchObject({ name: 'eth0' }) // не тронуто
    })

    it('с галочкой — предупреждение показывается при ЛЮБОМ непустом списке, даже если строки пустые', async () => {
      const rows: InterfaceDraftRow[] = [emptyRow(), emptyRow()]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })
      await wrapper.find('.replace-all-check input').setValue(true)
      await wrapper.find('.generator button.btn-secondary').trigger('click')

      // Раньше подтверждение зависело от того, есть ли в строках "осмысленные" данные — теперь
      // галочка сама по себе явный, осознанный сигнал разрушительного действия, поэтому
      // предупреждение безусловно, даже для пустых строк (см. комментарий в generate()).
      expect(confirm).toHaveBeenCalledWith(expect.stringContaining('заменит все порты устройства (2 шт.)'))
    })

    it('аудит fix/usability-batch4 (находка №1): с галочкой и "Количество" = 0 на непустом списке — отдельное предупреждение про удаление без замены', async () => {
      const rows: InterfaceDraftRow[] = [
        { ...emptyRow(), name: 'eth0' },
        { ...emptyRow(), name: 'eth1' },
      ]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })
      await wrapper.find('.replace-all-check input').setValue(true)
      await wrapper.find('.generator input[type="number"]').setValue('0')
      await wrapper.find('.generator button.btn-secondary').trigger('click')

      // Раньше текст подтверждения был одинаков независимо от того, что "Количество" = 0 и
      // результатом будет ноль портов — пользователь мог принять это за обычную замену N на N.
      expect(confirm).toHaveBeenCalledWith(expect.stringContaining('будут удалены'))
      const result = wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[]
      expect(result).toHaveLength(0) // осознанный выбор "заменить на пусто" по-прежнему поддерживается
    })

    it('с галочкой на пустом списке — предупреждения нет (нечего терять)', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })
      await wrapper.find('.replace-all-check input').setValue(true)
      await wrapper.find('.generator input[type="number"]').setValue('1')
      await wrapper.find('.generator button.btn-secondary').trigger('click')

      expect(confirm).not.toHaveBeenCalled()
      expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    })

    it('отмена подтверждения — данные не перезаписываются, событие не эмитится, галочка остаётся включённой', async () => {
      vi.stubGlobal(
        'confirm',
        vi.fn(() => false),
      )
      const existing: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'GigabitEthernet0/1', mac_address: 'aa:bb:cc:dd:ee:ff' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: existing, typeOptions, speedOptions, vlanOptions } })
      await wrapper.find('.replace-all-check input').setValue(true)

      await wrapper.find('.generator button.btn-secondary').trigger('click')

      expect(confirm).toHaveBeenCalled()
      expect(wrapper.emitted('update:modelValue')).toBeFalsy()
      // Не сбрасываем галочку при отмене — пользователь, скорее всего, ещё хочет повторить попытку.
      expect((wrapper.find('.replace-all-check input').element as HTMLInputElement).checked).toBe(true)
    })

    it('после успешной замены галочка сбрасывается — не остаётся взведённой "на будущее"', async () => {
      const existing: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth0' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: existing, typeOptions, speedOptions, vlanOptions } })
      await wrapper.find('.replace-all-check input').setValue(true)
      await wrapper.find('.generator button.btn-secondary').trigger('click')

      expect(wrapper.emitted('update:modelValue')).toBeTruthy()
      expect((wrapper.find('.replace-all-check input').element as HTMLInputElement).checked).toBe(false)
    })

    it('пустые "Тип по умолчанию"/"Скорость по умолчанию" не затирают уже выставленные вручную значения строк', async () => {
      const existing: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth0', interface_type_id: 't-eth', speed_id: 's-1g' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: existing, typeOptions, speedOptions, vlanOptions } })
      await wrapper.find('.replace-all-check input').setValue(true)

      // genTypeId/genSpeedId остаются "— не выбрано —" — только меняем имя через шаблон.
      await wrapper.find('.generator button.btn-secondary').trigger('click')

      const rows = wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[]
      expect(rows[0].interface_type_id).toBe('t-eth') // сохранилось, а не затёрлось пустым
      expect(rows[0].speed_id).toBe('s-1g')
    })
  })

  it('добавляет и удаляет IP-адрес интерфейса', async () => {
    const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1' }]
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })

    await expandRow(wrapper)
    await wrapper.find('.ip-head button').trigger('click')
    let emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as InterfaceDraftRow[])[0].ips).toEqual([{ ip_address: '', prefix_length: '', purpose: '' }])

    const withIp: InterfaceDraftRow[] = [{ ...rows[0], ips: [{ id: 'ip-1', ip_address: '10.0.0.5', prefix_length: '', purpose: '' }] }]
    await wrapper.setProps({ modelValue: withIp })
    await wrapper.find('.ip-row .icon-btn.danger').trigger('click')
    emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[emitted.length - 1][0] as InterfaceDraftRow[])[0].ips).toEqual([])
  })

  it('удаляет интерфейс по клику на кнопку удаления строки', async () => {
    const rows: InterfaceDraftRow[] = [
      { ...emptyRow(), id: 'if-1', name: 'eth1' },
      { ...emptyRow(), id: 'if-2', name: 'eth2' },
    ]
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })

    await wrapper.find('.iface-table .col-actions .icon-btn.danger').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([rows[1]])
  })

  it('быстрое добавление типа интерфейса подставляет его в тип по умолчанию генератора', async () => {
    // Проверяем не .value самого <select> (в изолированном юнит-тесте у него нет пары <option>
    // для новой записи — typeOptions статичный проп, а не реактивная привязка к стору, как в
    // реальном приложении, см. OpenPortListEditor.spec.ts), а реальный эффект — что
    // сгенерированные интерфейсы получают именно новый тип.
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/interface-types')) {
          return jsonResponse({ id: 't-new', name: 'InfiniBand' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    await wrapper.find('.generator .lookup-row button').trigger('click') // "+" рядом с "Тип по умолчанию"
    await teleportedContent().find('input[type="text"]').setValue('InfiniBand')
    await teleportedContent().find('form').trigger('submit')
    await flushPromises()

    await wrapper.find('.generator input[type="number"]').setValue('1') // genCount по умолчанию — 0 для пустого modelValue
    await wrapper.find('.generator button.btn-secondary').trigger('click') // Сгенерировать
    const emitted = wrapper.emitted('update:modelValue')!
    const rows = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
    expect(rows[0].interface_type_id).toBe('t-new')
  })

  describe('п.3.4: компактная таблица интерфейсов', () => {
    it('список из нескольких интерфейсов рендерится строками таблицы, а не карточками', () => {
      const rows: InterfaceDraftRow[] = [
        { ...emptyRow(), name: 'eth0' },
        { ...emptyRow(), name: 'eth1' },
      ]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })

      expect(wrapper.find('table.iface-table').exists()).toBe(true)
      expect(wrapper.findAll('.iface-table tbody tr.iface-row')).toHaveLength(2)
      const headers = wrapper.findAll('.iface-table th').map((h) => h.text())
      expect(headers).toEqual(['', '#', 'Порядок', 'Имя', 'Тип', 'MAC', 'Скорость', 'Упр.', 'Данные', 'VLAN / IP', ''])
    })

    it('VLAN и IP-адреса скрыты по умолчанию и открываются по клику на toggle', async () => {
      const rows: InterfaceDraftRow[] = [
        { ...emptyRow(), name: 'eth0', vlan_mode: 'trunk', ips: [{ id: 'ip-1', ip_address: '10.0.0.1', prefix_length: '24', purpose: '' }] },
      ]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })

      expect(wrapper.find('.iface-detail-row').exists()).toBe(false)
      expect(wrapper.find('.expand-toggle').text()).toContain('0 VLAN')
      expect(wrapper.find('.expand-toggle').text()).toContain('1 IP')

      await expandRow(wrapper)
      expect(wrapper.find('.iface-detail-row').exists()).toBe(true)
      expect(wrapper.find('.ip-row input').element.getAttribute('value')).toBe('10.0.0.1')
    })

    it('редактирование имени/типа/MAC/скорости работает прямо в ячейках таблицы', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth0' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })

      const row = wrapper.find('.iface-table tbody tr.iface-row')
      await row.find('input.cell-input').setValue('GigabitEthernet0/1')

      const emitted = wrapper.emitted('update:modelValue')!
      expect((emitted[0][0] as InterfaceDraftRow[])[0].name).toBe('GigabitEthernet0/1')
    })

    it('п.1.4.3.1: новая строка, добавленная кнопкой "+", остаётся свёрнутой', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [emptyRow()], typeOptions, speedOptions, vlanOptions } })
      await wrapper.find('.iface-list-head button.btn-secondary').trigger('click')
      await wrapper.setProps({ modelValue: wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[] })

      expect(wrapper.findAll('.iface-detail-row')).toHaveLength(0) // ни старая, ни новая строка не развёрнуты
    })
  })

  describe('VLAN на порту', () => {
    const vOptions: VLANDefinition[] = [
      { id: 'v-mgmt', vlan_id: 10, name: 'Управление', description: '', domain_id: null, domain_name: '', devices: [] },
      { id: 'v-guest', vlan_id: 20, name: 'Гостевой', description: '', domain_id: 'dom-1', domain_name: 'Филиал-1', devices: [] },
    ]

    it('без допустимых VLAN показывает подсказку вместо чекбоксов', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: [] } })
      await expandRow(wrapper)
      expect(wrapper.text()).toContain('Для типа устройства VLAN не назначены')
      expect(wrapper.find('.vlan-check').exists()).toBe(false)
    })

    it('в окне выбора VLAN trunk-порта — чекбокс на каждый допустимый VLAN с подписью "номер — имя [домен]"', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)
      expect(wrapper.find('.vlan-picker-modal').exists()).toBe(false) // пока окно не открыто, список VLAN карточку порта не растягивает
      expect(wrapper.findAll('.iface-detail .vlan-check:not(.vlan-check-all)')).toHaveLength(0)

      await openVlanPicker(wrapper)
      const labels = wrapper.findAll('.vlan-picker-modal .vlan-check:not(.vlan-check-all)').map((l) => l.text())
      expect(labels).toEqual(['10 — Управление', '20 — Гостевой [Филиал-1]'])
    })

    it('галочка «Все VLAN» остаётся в карточке порта рядом с кнопкой, открывающей окно выбора', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)

      const row = wrapper.find('.iface-detail .trunk-row')
      expect(row.find('.vlan-check-all input').exists()).toBe(true)
      expect(row.find('.vlan-picker-btn').exists()).toBe(true)
      expect(row.find('.vlan-summary').text()).toBe('Выбрано VLAN: 0 из 2')
    })

    it('окно выбора ищет VLAN по номеру, имени и домену; «Готово» и подложка его закрывают', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)
      await openVlanPicker(wrapper)

      await wrapper.find('.vlan-picker-modal input[aria-label="Поиск VLAN"]').setValue('филиал')
      expect(wrapper.findAll('.vlan-picker-modal .vlan-check:not(.vlan-check-all)').map((l) => l.text())).toEqual(['20 — Гостевой [Филиал-1]'])
      await wrapper.find('.vlan-picker-modal input[aria-label="Поиск VLAN"]').setValue('нет такого')
      expect(wrapper.find('.vlan-picker-modal').text()).toContain('Ничего не найдено')

      await wrapper.find('.vlan-picker-modal .btn-primary').trigger('click') // «Готово»
      expect(wrapper.find('.vlan-picker-modal').exists()).toBe(false)
    })

    it('порт, чьи VLAN задаёт группа, показывает окно только для просмотра', async () => {
      const group: InterfaceGroupDraft = { ...emptyGroup('Uplink'), key: 'g1', vlan_mode: 'trunk', vlan_ids: ['v-mgmt'] }
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk', vlan_ids: ['v-mgmt'], group_key: 'g1' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, groups: [group], typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)
      expect(wrapper.find('.iface-detail .vlan-picker-btn').text()).toBe('Показать VLAN…')

      await openVlanPicker(wrapper)
      for (const input of wrapper.findAll('.vlan-picker-modal input[type="checkbox"]')) expect(input.attributes('disabled')).toBeDefined()
      expect(wrapper.find('.vlan-picker-modal').text()).toContain('задан группой «Uplink»')
    })

    it('уже назначенный VLAN отображается отмеченным чекбоксом', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk', vlan_ids: ['v-guest'] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)
      await openVlanPicker(wrapper)
      const checkboxes = pickerVlanChecks(wrapper)
      expect((checkboxes[0].element as HTMLInputElement).checked).toBe(false) // v-mgmt
      expect((checkboxes[1].element as HTMLInputElement).checked).toBe(true) // v-guest
    })

    it('установка чекбокса добавляет id VLAN в vlan_ids, снятие — убирает', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk', vlan_ids: ['v-mgmt'] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)
      await openVlanPicker(wrapper)

      const checkboxes = pickerVlanChecks(wrapper)
      await checkboxes[1].setValue(true) // отмечаем v-guest в дополнение к уже стоящему v-mgmt
      let emitted = wrapper.emitted('update:modelValue')!
      expect((emitted[0][0] as InterfaceDraftRow[])[0].vlan_ids).toEqual(['v-mgmt', 'v-guest'])

      await wrapper.setProps({ modelValue: emitted[0][0] as InterfaceDraftRow[] })
      await pickerVlanChecks(wrapper)[0].setValue(false) // снимаем v-mgmt
      emitted = wrapper.emitted('update:modelValue')!
      expect((emitted[emitted.length - 1][0] as InterfaceDraftRow[])[0].vlan_ids).toEqual(['v-guest'])
    })

    it('чекбокс "Все VLAN" отмечает/снимает все опции разом', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)

      await wrapper.find('.vlan-check-all input').setValue(true)
      let emitted = wrapper.emitted('update:modelValue')!
      expect((emitted[0][0] as InterfaceDraftRow[])[0].vlan_ids).toEqual(['v-mgmt', 'v-guest'])

      await wrapper.setProps({ modelValue: emitted[0][0] as InterfaceDraftRow[] })
      expect((wrapper.find('.vlan-check-all input').element as HTMLInputElement).checked).toBe(true)

      await wrapper.find('.vlan-check-all input').setValue(false)
      emitted = wrapper.emitted('update:modelValue')!
      expect((emitted[emitted.length - 1][0] as InterfaceDraftRow[])[0].vlan_ids).toEqual([])
    })

    describe('«Все VLAN» — сохраняемый признак порта (all_vlans), а не вывод из числа выбранных VLAN', () => {
      const mountTrunk = (patch: Partial<InterfaceDraftRow> = {}) =>
        mount(DeviceInterfacesEditor, {
          props: { modelValue: [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk', ...patch }], typeOptions, speedOptions, vlanOptions: vOptions },
        })
      const lastRow = (wrapper: ReturnType<typeof mountTrunk>) => {
        const emitted = wrapper.emitted('update:modelValue')!
        return (emitted[emitted.length - 1][0] as InterfaceDraftRow[])[0]
      }
      const allChecked = (wrapper: ReturnType<typeof mountTrunk>) => (wrapper.find('.iface-detail .vlan-check-all input').element as HTMLInputElement).checked

      it('галочка «Все VLAN» ставит признак и отмечает все VLAN, её снятие — убирает и признак, и набор', async () => {
        const wrapper = mountTrunk()
        await expandRow(wrapper)

        await wrapper.find('.iface-detail .vlan-check-all input').setValue(true)
        expect(lastRow(wrapper)).toMatchObject({ all_vlans: true, vlan_ids: ['v-mgmt', 'v-guest'] })

        await wrapper.setProps({ modelValue: [lastRow(wrapper)] })
        await wrapper.find('.iface-detail .vlan-check-all input').setValue(false)
        expect(lastRow(wrapper)).toMatchObject({ all_vlans: false, vlan_ids: [] })
      })

      it('порт с сохранённым признаком показывается с галочкой, а те же VLAN, выбранные вручную, — без неё', async () => {
        const flagged = mountTrunk({ all_vlans: true, vlan_ids: ['v-mgmt', 'v-guest'] })
        await expandRow(flagged)
        expect(allChecked(flagged)).toBe(true)

        const manual = mountTrunk({ all_vlans: false, vlan_ids: ['v-mgmt', 'v-guest'] })
        await expandRow(manual)
        expect(allChecked(manual)).toBe(false)
      })

      it('полный набор, отмеченный по одному, признаком не становится', async () => {
        const wrapper = mountTrunk({ vlan_ids: ['v-mgmt'] })
        await expandRow(wrapper)
        await openVlanPicker(wrapper)

        await pickerVlanChecks(wrapper)[1].setValue(true)

        expect(lastRow(wrapper)).toMatchObject({ vlan_ids: ['v-mgmt', 'v-guest'], all_vlans: false })
      })

      it('снятие любого VLAN у порта с признаком снимает признак', async () => {
        const wrapper = mountTrunk({ all_vlans: true, vlan_ids: ['v-mgmt', 'v-guest'] })
        await expandRow(wrapper)
        await openVlanPicker(wrapper)

        await pickerVlanChecks(wrapper)[1].setValue(false)

        expect(lastRow(wrapper)).toMatchObject({ vlan_ids: ['v-mgmt'], all_vlans: false })
      })
    })
  })

  describe('п.1.4 (батч4): открытые порты интерфейса и копирование на другой интерфейс', () => {
    it('блок "Открытые порты" рендерится внутри развёрнутой строки интерфейса', async () => {
      const rows: InterfaceDraftRow[] = [
        { ...emptyRow(), name: 'eth0', open_ports: [{ id: 'op-1', protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }] },
      ]
      const wrapper = mount(DeviceInterfacesEditor, {
        props: {
          modelValue: rows,
          typeOptions,
          speedOptions,
          vlanOptions,
          protocolPortCatalog: [{ id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null }],
        },
      })
      await expandRow(wrapper)
      expect(wrapper.find('.ports-block').exists()).toBe(true)
      // Правка "убрать текстовые поля Порт/Протокол": подпись выбранной записи справочника
      // теперь рендерится SearchableSelect'ом, отдельных input'ов для порта/протокола больше нет.
      expect((wrapper.find('.ports-block .searchable-select input').element as HTMLInputElement).value).toBe('22 / SSH')
    })

    it('открытые порты порта сворачиваются по общему порогу из «Настроек»', async () => {
      const catalog = Array.from({ length: 4 }, (_, i) => ({ id: `cat-${i}`, port: 8000 + i, protocol_type: `P${i}`, description: null }))
      const openPorts = [0, 1, 2].map((i) => ({ id: `op-${i}`, protocol_catalog_id: `cat-${i}`, transport_protocol: 'TCP', description: '' }))
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth0', open_ports: openPorts }]
      const props = { modelValue: rows, typeOptions, speedOptions, vlanOptions, protocolPortCatalog: catalog }

      const wide = mount(DeviceInterfacesEditor, { props })
      await expandRow(wide)
      expect(wide.find('.ports-block [data-testid="ports-collapsed"]').exists()).toBe(false) // порог по умолчанию 10, портов 3

      usePreferencesStore().user = { device_vlan_collapse_rows: 2 }
      const narrow = mount(DeviceInterfacesEditor, { props })
      await expandRow(narrow)
      expect(narrow.find('.ports-block [data-testid="ports-collapsed"]').exists()).toBe(true)
    })

    describe('номера открытых портов интерфейса: порядок и повторы', () => {
      const wideCatalog = [
        { id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null },
        { id: 'cat-http', port: 80, protocol_type: 'HTTP', description: null },
        { id: 'cat-http-alt', port: 80, protocol_type: 'HTTP-Proxy', description: null },
        { id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null },
      ]
      const port = (protocol_catalog_id: string) => ({ protocol_catalog_id, transport_protocol: 'TCP', description: '' })

      it('повторяющийся номер подсвечивается и объясняется под списком портов интерфейса', async () => {
        const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth0', open_ports: [port('cat-http'), port('cat-ssh'), port('cat-http-alt')] }]
        const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, protocolPortCatalog: wideCatalog } })
        await expandRow(wrapper)

        const flagged = wrapper.findAll('.ports-block .nested-row').map((r) => r.classes().includes('row-duplicate'))
        expect(flagged).toEqual([true, false, true])
        expect(wrapper.find('.ports-block .dup-error').text()).toContain('Порт 80')
      })

      it('на СВЁРНУТОЙ строке с повтором номера показан индикатор с номерами; без повтора его нет', async () => {
        const rows: InterfaceDraftRow[] = [
          { ...emptyRow(), name: 'eth0', open_ports: [port('cat-http'), port('cat-ssh'), port('cat-http-alt')] },
          { ...emptyRow(), name: 'eth1', open_ports: [port('cat-http'), port('cat-ssh')] },
        ]
        const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, protocolPortCatalog: wideCatalog } })

        // Ни одна строка не развёрнута — индикатор должен быть виден без раскрытия.
        const icons = wrapper.findAll('.expand-toggle').map((t) => t.find('.ports-dup-icon'))
        expect(icons[0].exists()).toBe(true)
        expect(icons[0].attributes('title')).toBe('Повторяются номера открытых портов: 80')
        expect(icons[0].attributes('aria-label')).toBe('Повторяются номера открытых портов: 80')
        expect(icons[1].exists()).toBe(false)
      })

      it('индикатор исчезает, когда повтор устранён (список меняет родитель через v-model)', async () => {
        const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth0', open_ports: [port('cat-http'), port('cat-http-alt')] }]
        const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, protocolPortCatalog: wideCatalog } })
        expect(wrapper.find('.expand-toggle .ports-dup-icon').exists()).toBe(true)

        await wrapper.setProps({ modelValue: [{ ...rows[0], open_ports: [port('cat-http'), port('cat-ssh')] }] })

        expect(wrapper.find('.expand-toggle .ports-dup-icon').exists()).toBe(false)
      })

      it('выбор порта в новой строке не переставляет строку — её удобно дозаполнять на месте', async () => {
        const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth0', open_ports: [port('cat-https'), port('')] }]
        const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, protocolPortCatalog: wideCatalog } })
        await expandRow(wrapper)

        await wrapper.findAll('.ports-block .col-catalog .searchable-select input')[1].trigger('focus')
        await wrapper
          .findAll('.ports-block .col-catalog .ss-option')
          .find((o) => o.text() === '22 / SSH')!
          .trigger('mousedown')

        const emitted = wrapper.emitted('update:modelValue')!
        const result = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
        expect(result[0].open_ports.map((p) => p.protocol_catalog_id)).toEqual(['cat-https', 'cat-ssh'])
      })

      it('добавление следующего порта упорядочивает список по возрастанию номера, новая строка — в конец', async () => {
        const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth0', open_ports: [port('cat-https'), port('cat-ssh')] }]
        const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, protocolPortCatalog: wideCatalog } })
        await expandRow(wrapper)

        await wrapper.find('.ports-block button.add-btn').trigger('click')

        const emitted = wrapper.emitted('update:modelValue')!
        const result = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
        expect(result[0].open_ports.map((p) => p.protocol_catalog_id)).toEqual(['cat-ssh', 'cat-https', ''])
      })
    })

    it('добавление порта на одном интерфейсе не затрагивает open_ports другого', async () => {
      const rows: InterfaceDraftRow[] = [
        { ...emptyRow(), name: 'eth0' },
        { ...emptyRow(), name: 'eth1' },
      ]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })
      await expandRow(wrapper, 0)
      await wrapper.find('.ports-block button.add-btn').trigger('click')

      const result = wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[]
      expect(result[0].open_ports).toHaveLength(1)
      expect(result[1].open_ports).toEqual([])
    })

    it('с единственным интерфейсом кнопку "Копировать на порт…" показывать не для чего — блок выбора получателя не рендерится', async () => {
      const rows: InterfaceDraftRow[] = [
        { ...emptyRow(), name: 'eth0', open_ports: [{ id: 'op-1', protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }] },
      ]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })
      await expandRow(wrapper)
      expect(wrapper.find('.copy-ports-row').exists()).toBe(false)
    })

    it('копирует набор открытых портов на выбранный интерфейс со сброшенными id (это КОПИЯ, а не перенос)', async () => {
      const rows: InterfaceDraftRow[] = [
        { ...emptyRow(), name: 'eth0', open_ports: [{ id: 'op-1', protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }] },
        { ...emptyRow(), name: 'eth1' },
      ]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })
      await expandRow(wrapper, 0)

      await wrapper.find('.copy-target-select').setValue('1') // индекс eth1 в modelValue
      await wrapper.find('.copy-ports-row button').trigger('click')

      const result = wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[]
      expect(result[1].open_ports).toEqual([{ id: undefined, protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }])
      expect(result[0].open_ports).toHaveLength(1) // у источника порты остаются как есть — это копирование, не перемещение
    })

    it('копия открытых портов упорядочена по номеру порта, даже если у источника порядок был иной', async () => {
      const catalog = [
        { id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null },
        { id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null },
      ]
      const port = (protocol_catalog_id: string, id: string) => ({ id, protocol_catalog_id, transport_protocol: 'TCP', description: '' })
      const rows: InterfaceDraftRow[] = [
        { ...emptyRow(), name: 'eth0', open_ports: [port('cat-https', 'op-1'), port('cat-ssh', 'op-2')] },
        { ...emptyRow(), name: 'eth1' },
      ]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, protocolPortCatalog: catalog } })
      await expandRow(wrapper, 0)

      await wrapper.find('.copy-target-select').setValue('1')
      await wrapper.find('.copy-ports-row button').trigger('click')

      const result = wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[]
      expect(result[1].open_ports.map((p) => p.protocol_catalog_id)).toEqual(['cat-ssh', 'cat-https'])
      expect(result[0].open_ports.map((p) => p.protocol_catalog_id)).toEqual(['cat-https', 'cat-ssh']) // источник не тронут
    })

    it('если у получателя уже есть порты — требует подтверждения и не заменяет их при отказе', async () => {
      vi.stubGlobal(
        'confirm',
        vi.fn(() => false),
      )
      const rows: InterfaceDraftRow[] = [
        { ...emptyRow(), name: 'eth0', open_ports: [{ id: 'op-1', protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }] },
        { ...emptyRow(), name: 'eth1', open_ports: [{ id: 'op-2', protocol_catalog_id: 'cat-https', transport_protocol: 'TCP', description: '' }] },
      ]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })
      await expandRow(wrapper, 0)

      await wrapper.find('.copy-target-select').setValue('1')
      await wrapper.find('.copy-ports-row button').trigger('click')

      expect(confirm).toHaveBeenCalled()
      expect(wrapper.emitted('update:modelValue')).toBeFalsy() // отказ — ничего не эмитим, порты eth1 не тронуты
    })
  })

  describe('п.1.4.3.2: режим порта access/trunk', () => {
    const vOptions: VLANDefinition[] = [
      { id: 'v-mgmt', vlan_id: 10, name: 'Управление', description: '', domain_id: null, domain_name: '', devices: [] },
      { id: 'v-guest', vlan_id: 20, name: 'Гостевой', description: '', domain_id: null, domain_name: '', devices: [] },
    ]

    it('новая строка через "+ Интерфейс" создаётся в режиме access — п.1.3.1', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions: vOptions } })
      await wrapper.find('.empty button').trigger('click')

      const newRow = (wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[])[0]
      expect(newRow.vlan_mode).toBe('access')

      await wrapper.setProps({ modelValue: [newRow] })
      await expandRow(wrapper)
      const radios = wrapper.findAll('.vlan-mode-row input[type="radio"]')
      expect((radios[0].element as HTMLInputElement).checked).toBe(false) // Trunk
      expect((radios[1].element as HTMLInputElement).checked).toBe(true) // Access
      expect(wrapper.find('.iface-detail .vlan-checks').exists()).toBe(false)
    })

    it('строка с vlan_mode trunk отображается с отмеченным Trunk и чекбоксами VLAN', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)

      const radios = wrapper.findAll('.vlan-mode-row input[type="radio"]')
      expect((radios[0].element as HTMLInputElement).checked).toBe(true) // Trunk
      expect((radios[1].element as HTMLInputElement).checked).toBe(false) // Access
      expect(wrapper.find('.iface-detail .trunk-row').exists()).toBe(true)
    })

    it('переключение на Access показывает одиночный SearchableSelect вместо кнопки выбора VLAN', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk', vlan_ids: ['v-mgmt'] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)

      const radios = wrapper.findAll('.vlan-mode-row input[type="radio"]')
      await radios[1].setValue(true) // Access

      const emitted = wrapper.emitted('update:modelValue')!
      const result = (emitted[0][0] as InterfaceDraftRow[])[0]
      expect(result.vlan_mode).toBe('access')
      expect(result.vlan_ids).toEqual(['v-mgmt']) // единственный уже стоявший VLAN сохранён

      await wrapper.setProps({ modelValue: emitted[0][0] as InterfaceDraftRow[] })
      expect(wrapper.find('.iface-detail .trunk-row').exists()).toBe(false)
      expect((wrapper.find('.iface-detail .vlan-block .searchable-select input').element as HTMLInputElement).value).toBe('10 — Управление')
    })

    it('переключение с trunk (несколько VLAN) на access оставляет только первый VLAN', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk', vlan_ids: ['v-mgmt', 'v-guest'] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)

      await wrapper.findAll('.vlan-mode-row input[type="radio"]')[1].setValue(true) // Access
      const result = (wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[])[0]
      expect(result.vlan_ids).toEqual(['v-mgmt'])
    })

    it('фикс п.2.1.1: переключение на Trunk сразу отмечает "Все VLAN"', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'access', vlan_ids: ['v-mgmt'] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)

      await wrapper.findAll('.vlan-mode-row input[type="radio"]')[0].setValue(true) // Trunk

      const result = (wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[])[0]
      expect(result.vlan_mode).toBe('trunk')
      expect(result.vlan_ids).toEqual(['v-mgmt', 'v-guest']) // все опции — а не пусто и не только то, что было в access

      await wrapper.setProps({ modelValue: [result] })
      expect(wrapper.find('.vlan-check-all input').element).toHaveProperty('checked', true) // "Все VLAN" отмечен
    })

    it('в режиме access выбор VLAN в SearchableSelect задаёт единственный элемент vlan_ids', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'access', vlan_ids: [] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)

      await pickAccessVlan(wrapper, 'Гостевой')
      const result = (wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[])[0]
      expect(result.vlan_ids).toEqual(['v-guest'])
    })

    it('в режиме access список VLAN фильтруется вводом текста, а очистка поля снимает VLAN', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'access', vlan_ids: ['v-mgmt'] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)

      const select = wrapper.find('.iface-detail .vlan-block .searchable-select')
      await select.find('input').trigger('focus')
      await select.find('input').setValue('гост')
      expect(select.findAll('.ss-option').map((o) => o.text())).toEqual(['20 — Гостевой'])

      await select.find('.ss-clear').trigger('mousedown')
      expect((wrapper.emitted('update:modelValue')!.at(-1)![0] as InterfaceDraftRow[])[0].vlan_ids).toEqual([])
    })

    it('свёрнутая строка таблицы показывает режим порта в сводке ("Trunk · N VLAN" / "Access: …")', () => {
      const rows: InterfaceDraftRow[] = [
        { ...emptyRow(), name: 'eth1', vlan_mode: 'trunk', vlan_ids: ['v-mgmt', 'v-guest'] },
        { ...emptyRow(), name: 'eth2', vlan_mode: 'access', vlan_ids: ['v-mgmt'] },
      ]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      const summaries = wrapper.findAll('.expand-toggle span').map((s) => s.text())
      expect(summaries[0]).toContain('Trunk · 2 VLAN')
      expect(summaries[1]).toContain('Access: 10 — Управление')
    })

    it('сводка порта с признаком «Все VLAN» так и называет его', () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk', all_vlans: true, vlan_ids: ['v-mgmt', 'v-guest'] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      expect(wrapper.find('.expand-toggle span').text()).toContain('Trunk · все VLAN (2)')
    })

    it('«Все VLAN» как признак: переключение на Trunk ставит его сразу, переключение на Access — снимает', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'access', vlan_ids: ['v-mgmt'] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)

      await wrapper.findAll('.vlan-mode-row input[type="radio"]')[0].setValue(true) // Trunk
      const trunk = (wrapper.emitted('update:modelValue')!.at(-1)![0] as InterfaceDraftRow[])[0]
      expect(trunk).toMatchObject({ vlan_mode: 'trunk', all_vlans: true })

      await wrapper.setProps({ modelValue: [trunk] })
      await wrapper.findAll('.vlan-mode-row input[type="radio"]')[1].setValue(true) // Access
      const access = (wrapper.emitted('update:modelValue')!.at(-1)![0] as InterfaceDraftRow[])[0]
      expect(access).toMatchObject({ vlan_mode: 'access', all_vlans: false, vlan_ids: ['v-mgmt'] })
    })

    it('у устройства без VLAN переключение на Trunk признак «Все VLAN» не ставит — «всех» пока нет', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'access' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: [] } })
      await expandRow(wrapper)

      await wrapper.findAll('.vlan-mode-row input[type="radio"]')[0].setValue(true) // Trunk

      expect((wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[])[0]).toMatchObject({ vlan_mode: 'trunk', all_vlans: false, vlan_ids: [] })
    })
  })

  describe('фикс п.1.3.4 (было п.1.4.1): без галочки "Заменить все порты" кнопка добавляет, не заменяя', () => {
    it('добавляет новые интерфейсы, не трогая уже существующие', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), id: 'if-1', name: 'CustomName', mac_address: 'aa:bb:cc:dd:ee:ff' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })

      const inputs = wrapper.findAll('.generator input')
      await inputs[0].setValue('2') // Количество
      await inputs[2].setValue('eth{n}') // Шаблон имени (inputs[1] теперь "Начать нумерацию с", фикс п.1.3.3)
      await wrapper.find('.generator button.btn-secondary').trigger('click') // галочка "Заменить все порты" не тронута — выключена

      expect(confirm).not.toHaveBeenCalled() // добавление не разрушительно — подтверждение не нужно
      const result = wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[]
      expect(result).toHaveLength(3)
      expect(result[0]).toMatchObject({ id: 'if-1', name: 'CustomName', mac_address: 'aa:bb:cc:dd:ee:ff' }) // не тронуто
      // Нумерация новых продолжается от количества уже существующих (было 1), а не с 1.
      expect(result[1].name).toBe('eth2')
      expect(result[2].name).toBe('eth3')
    })

    it('с нулевым количеством ничего не делает', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })
      await wrapper.find('.generator input[type="number"]').setValue('0')
      await wrapper.find('.generator button.btn-secondary').trigger('click')
      expect(wrapper.emitted('update:modelValue')).toBeFalsy()
    })
  })

  describe('п.1.4.2: справка по шаблону имени', () => {
    it('кнопка "?" рядом с "Шаблон имени" по клику показывает пояснение', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })
      expect(wrapper.text()).not.toContain('порядковый номер порта')

      await wrapper.find('.help-tip-btn').trigger('click')
      expect(wrapper.text()).toContain('порядковый номер порта')
    })
  })

  describe('Массовое редактирование выбранных строк', () => {
    const vOptions: VLANDefinition[] = [
      { id: 'v-mgmt', vlan_id: 10, name: 'Управление', description: '', domain_id: null, domain_name: '', devices: [] },
      { id: 'v-guest', vlan_id: 20, name: 'Гостевой', description: '', domain_id: null, domain_name: '', devices: [] },
    ]

    function threeRows(): InterfaceDraftRow[] {
      return [
        { ...emptyRow(), name: 'eth0' },
        { ...emptyRow(), name: 'eth1' },
        { ...emptyRow(), name: 'eth2', vlan_ids: ['v-mgmt'] },
      ]
    }

    it('без интерфейсов панель не показывается', () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })
      expect(wrapper.find('.bulk-edit-row').exists()).toBe(false)
    })

    it('пункт 4 правки "создание физического устройства": массовое редактирование — первая строка ТОЙ ЖЕ таблицы "Список интерфейсов", а не отдельная панель', () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: threeRows(), typeOptions, speedOptions, vlanOptions: vOptions } })
      const panel = wrapper.find('.iface-panel')
      expect(panel.exists()).toBe(true)
      expect(panel.find('.iface-list-head').exists()).toBe(true)
      const table = panel.find('[role="region"] table.iface-table')
      expect(table.exists()).toBe(true)
      // F-05: таблица из 10 колонок листается вбок внутри обёртки с подсказкой, а не раздувает форму устройства.
      expect(panel.getComponent(ScrollableTableWrap).attributes('aria-label')).toBe('Список интерфейсов')
      expect(table.find('.bulk-edit-row').exists()).toBe(true)
      // "Первая строка" — буквально: сразу после thead, перед реальными строками интерфейсов.
      expect(table.find('tbody tr').classes()).toContain('bulk-edit-row')
    })

    it('без отмеченных строк по клику "Применить" показывает ошибку и ничего не эмитит', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: threeRows(), typeOptions, speedOptions, vlanOptions: vOptions } })
      await wrapper.find('.bulk-edit-row button').trigger('click')
      expect(wrapper.emitted('update:modelValue')).toBeFalsy()
    })

    it('"Выбрать все" (шапка таблицы, общая для массового редактирования и самого списка) отмечает чекбоксы "Выбрать" на всех строках', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: threeRows(), typeOptions, speedOptions, vlanOptions: vOptions } })
      await wrapper.find('input[aria-label="Выбрать все интерфейсы"]').setValue(true)
      const rowChecks = wrapper.findAll('.iface-table tbody tr:not(.bulk-edit-row) .col-select input')
      expect(rowChecks.every((c) => (c.element as HTMLInputElement).checked)).toBe(true)
    })

    it('применяет тип/скорость только к отмеченным строкам, остальные поля строк не трогает', async () => {
      const rows = threeRows()
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })

      const rowChecks = wrapper.findAll('.iface-table tbody tr:not(.bulk-edit-row) .col-select input')
      await rowChecks[0].setValue(true) // отмечаем только eth0
      await wrapper.find('select[aria-label="Тип интерфейса — массовое редактирование"]').setValue('t-eth')
      await wrapper.find('.bulk-edit-row td.col-actions button').trigger('click')

      const emitted = wrapper.emitted('update:modelValue')!
      const result = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
      expect(result[0].interface_type_id).toBe('t-eth') // отмеченная — изменена
      expect(result[1].interface_type_id).toBe('') // не отмеченная — без изменений
      expect(result[2].vlan_ids).toEqual(['v-mgmt']) // не отмеченная — VLAN не тронут
    })

    it('пункт 3 правки "физическое устройство: массовое редактирование": список VLAN — во всплывающем окне по кнопке, а не инлайновым списком в ячейке', () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: threeRows(), typeOptions, speedOptions, vlanOptions: vOptions } })

      expect(wrapper.find('.bulk-edit-row .vlan-checks').exists()).toBe(false) // список не в ячейке
      expect(wrapper.find('.bulk-edit-row .vlan-picker-btn').exists()).toBe(true)
      expect(wrapper.find('.vlan-picker-modal').exists()).toBe(false) // окно ещё не открыто
    })

    it('VLAN из панели (выбранный во всплывающем окне) добавляется к уже стоящим на порту (объединение, не замена)', async () => {
      const rows = threeRows()
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })

      const rowChecks = wrapper.findAll('.iface-table tbody tr:not(.bulk-edit-row) .col-select input')
      await rowChecks[2].setValue(true) // отмечаем eth2 (уже с v-mgmt)
      await wrapper.find('.vlan-picker-btn').trigger('click')
      await wrapper.find('.vlan-picker-modal .vlan-check:not(.vlan-check-all) input').setValue(true) // добавляем v-mgmt ещё раз через панель
      await wrapper.find('.vlan-picker-modal .conflict-modal-actions button').trigger('click') // "Готово" — закрывает окно
      await wrapper.find('.bulk-edit-row td.col-actions button').trigger('click')

      const emitted = wrapper.emitted('update:modelValue')!
      const result = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
      expect(result[2].vlan_ids).toEqual(['v-mgmt']) // без дублей
    })

    it('пункт 4: галочка "Все VLAN" в массовом редактировании (во всплывающем окне) появляется только при выбранном режиме Trunk и отмечает весь vlanOptions разом', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: threeRows(), typeOptions, speedOptions, vlanOptions: vOptions } })

      await wrapper.find('.vlan-picker-btn').trigger('click')
      expect(wrapper.find('.vlan-picker-modal .vlan-check-all').exists()).toBe(false) // режим ещё не выбран
      await wrapper.find('.vlan-picker-modal .conflict-modal-actions button').trigger('click') // закрываем, чтобы сменить режим в ячейке снаружи

      await wrapper.find('select[aria-label="Режим порта — массовое редактирование"]').setValue('trunk')
      await wrapper.find('.vlan-picker-btn').trigger('click')
      expect(wrapper.find('.vlan-picker-modal .vlan-check-all').exists()).toBe(true)

      await wrapper.find('.vlan-picker-modal .vlan-check-all input').setValue(true)
      await wrapper.find('.vlan-picker-modal .conflict-modal-actions button').trigger('click')
      await wrapper.findAll('.iface-table tbody tr:not(.bulk-edit-row) .col-select input')[1].setValue(true) // отмечаем eth1
      await wrapper.find('.bulk-edit-row td.col-actions button').trigger('click')

      const emitted = wrapper.emitted('update:modelValue')!
      const result = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
      expect(result[1].vlan_mode).toBe('trunk')
      expect(new Set(result[1].vlan_ids)).toEqual(new Set(vOptions.map((v) => v.id)))
    })

    it('пункт 4: «Все VLAN» панели ставит отмеченным trunk-портам признак all_vlans, а полный набор, отмеченный по одному, — нет', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: threeRows(), typeOptions, speedOptions, vlanOptions: vOptions } })
      const apply = async (pickVlans: () => Promise<void>) => {
        await wrapper.find('select[aria-label="Режим порта — массовое редактирование"]').setValue('trunk')
        await wrapper.find('.vlan-picker-btn').trigger('click')
        await pickVlans()
        await wrapper.find('.vlan-picker-modal .conflict-modal-actions button').trigger('click')
        await wrapper.findAll('.iface-table tbody tr:not(.bulk-edit-row) .col-select input')[1].setValue(true)
        await wrapper.find('.bulk-edit-row td.col-actions button').trigger('click')
        const emitted = wrapper.emitted('update:modelValue')!
        return (emitted[emitted.length - 1][0] as InterfaceDraftRow[])[1]
      }

      const manual = await apply(async () => {
        for (const input of wrapper.findAll('.vlan-picker-modal .vlan-check:not(.vlan-check-all) input')) await input.setValue(true)
      })
      expect(manual).toMatchObject({ vlan_mode: 'trunk', all_vlans: false })
      expect(new Set(manual.vlan_ids)).toEqual(new Set(vOptions.map((v) => v.id)))

      await wrapper.setProps({ modelValue: threeRows() })
      const flagged = await apply(async () => {
        await wrapper.find('.vlan-picker-modal .vlan-check-all input').setValue(true)
      })
      expect(flagged).toMatchObject({ vlan_mode: 'trunk', all_vlans: true })
      expect(new Set(flagged.vlan_ids)).toEqual(new Set(vOptions.map((v) => v.id)))
    })

    it('после применения панель сбрасывается — выбор, поля и выбранные VLAN возвращаются к значениям по умолчанию', async () => {
      const rows = threeRows()
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })

      await wrapper.findAll('.iface-table tbody tr:not(.bulk-edit-row) .col-select input')[0].setValue(true)
      await wrapper.find('select[aria-label="Тип интерфейса — массовое редактирование"]').setValue('t-eth')
      await wrapper.find('.vlan-picker-btn').trigger('click')
      await wrapper.find('.vlan-picker-modal .vlan-check input').setValue(true)
      await wrapper.find('.vlan-picker-modal .conflict-modal-actions button').trigger('click')
      await wrapper.find('.bulk-edit-row td.col-actions button').trigger('click')
      await wrapper.setProps({ modelValue: wrapper.emitted('update:modelValue')!.at(-1)![0] as InterfaceDraftRow[] })

      expect((wrapper.find('select[aria-label="Тип интерфейса — массовое редактирование"]').element as HTMLSelectElement).value).toBe('')
      expect((wrapper.findAll('.iface-table tbody tr:not(.bulk-edit-row) .col-select input')[0].element as HTMLInputElement).checked).toBe(false)
      expect(wrapper.find('.vlan-picker-btn').text()).toBe('— выбрать VLAN —')
    })
  })

  describe('п.3: подсказка при наведении на обрезанный текст в ячейках таблицы', () => {
    it('длинное имя интерфейса и сводка VLAN/IP используют v-truncate-tooltip', async () => {
      vi.useFakeTimers()
      try {
        const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'GigabitEthernet0/0/0/1.100500', vlan_mode: 'trunk', vlan_ids: ['v-1'] }]
        const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })

        const nameInput = wrapper.find('tr:not(.bulk-edit-row) .cell-input')
        Object.defineProperty(nameInput.element, 'scrollWidth', { value: 300, configurable: true })
        Object.defineProperty(nameInput.element, 'clientWidth', { value: 100, configurable: true })
        await nameInput.trigger('mouseenter')
        vi.advanceTimersByTime(1000)
        expect(document.querySelector('.truncate-tooltip-popup')?.textContent).toBe('GigabitEthernet0/0/0/1.100500')
        await nameInput.trigger('mouseleave')

        const summary = wrapper.find('.expand-toggle span')
        Object.defineProperty(summary.element, 'scrollWidth', { value: 300, configurable: true })
        Object.defineProperty(summary.element, 'clientWidth', { value: 100, configurable: true })
        await summary.trigger('mouseenter')
        vi.advanceTimersByTime(1000)
        expect(document.querySelector('.truncate-tooltip-popup')?.textContent).toBe('Trunk · 1 VLAN · 0 IP')
      } finally {
        vi.useRealTimers()
      }
    })
  })

  describe('пункты 1-2 правки "физическое устройство: расхождение с соседним портом"', () => {
    const flagsConflict = {
      otherInterfaceId: 'if-2',
      otherDeviceName: 'sw-02',
      otherInterfaceName: 'Gi0/2',
      flagsDiffer: true,
      vlanModeDiffer: false,
      allVlansDiffer: false,
      other: { is_management: true, is_data_transfer: false, vlan_mode: 'access' as const, all_vlans: false },
    }
    const vlanModeConflict = {
      otherInterfaceId: 'if-3',
      otherDeviceName: 'sw-03',
      otherInterfaceName: 'Gi0/3',
      flagsDiffer: false,
      vlanModeDiffer: true,
      allVlansDiffer: false,
      // Сосед в trunk с «Все VLAN» — как порт формы после смены режима на trunk (форма сразу ставит ему «Все VLAN»): сверять нечего.
      other: { is_management: false, is_data_transfer: false, vlan_mode: 'trunk' as const, all_vlans: true },
    }

    it('пункт 1: строка с расхождением флагов подсвечена, показывает кликабельную иконку в ячейках Упр./Данные', () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), id: 'if-1', name: 'Gi0/1' }]
      const wrapper = mount(DeviceInterfacesEditor, {
        props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, conflicts: { 'if-1': flagsConflict } },
      })

      const cells = wrapper.findAll('tr:not(.bulk-edit-row) td.col-check')
      expect(cells[0].classes()).toContain('has-conflict')
      expect(cells[1].classes()).toContain('has-conflict')
      expect(cells[0].find('.conflict-icon-btn').exists()).toBe(true)
    })

    it('без conflicts (по умолчанию) — ни подсветки, ни иконки, ни у флагов, ни у режима порта', () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), id: 'if-1', name: 'Gi0/1' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })

      const cell = wrapper.find('tr:not(.bulk-edit-row) td.col-check')
      expect(cell.classes()).not.toContain('has-conflict')
      expect(cell.find('.conflict-icon-btn').exists()).toBe(false)
      expect(wrapper.find('.expand-toggle .conflict-icon').exists()).toBe(false)
    })

    it('черновая строка без id (новая/скопированная) не подсвечивается, даже если id случайно совпал бы с ключом карты', () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'Gi0/1' }] // без id
      const wrapper = mount(DeviceInterfacesEditor, {
        props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, conflicts: { undefined: flagsConflict } as never },
      })

      expect(wrapper.find('tr:not(.bulk-edit-row) td.col-check').classes()).not.toContain('has-conflict')
    })

    it('пункт 2: расхождение режима порта показывает иконку и на свёрнутой строке, и рядом с "Режим порта" в развёрнутой детали — но не подсвечивает ячейки флагов', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), id: 'if-1', name: 'Gi0/1' }]
      const wrapper = mount(DeviceInterfacesEditor, {
        props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, conflicts: { 'if-1': vlanModeConflict } },
      })

      expect(wrapper.find('tr:not(.bulk-edit-row) td.col-check').classes()).not.toContain('has-conflict')
      expect(wrapper.find('.expand-toggle .conflict-icon').exists()).toBe(true)

      await wrapper.find('.expand-toggle').trigger('click')
      expect(wrapper.find('.vlan-mode-row .conflict-icon-btn').exists()).toBe(true)
    })

    it('клик по иконке расхождения флагов открывает окно сравнения с текущими и соседними значениями', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), id: 'if-1', name: 'Gi0/1', is_management: false, is_data_transfer: true }]
      const wrapper = mount(DeviceInterfacesEditor, {
        props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, conflicts: { 'if-1': flagsConflict } },
      })

      await wrapper.find('.conflict-icon-btn').trigger('click')

      expect(wrapper.find('.conflict-modal').exists()).toBe(true)
      expect(wrapper.text()).toContain('Gi0/2')
      expect(wrapper.text()).toContain('sw-02')
      const rowsText = wrapper.findAll('.conflict-compare tbody tr').map((r) => r.text())
      expect(rowsText[0]).toContain('Управление')
      expect(rowsText[0]).toContain('Нет') // текущее — false
      expect(rowsText[0]).toContain('Да') // соседнее — true
    })

    it('"Применить конфигурацию соседа" переносит значения соседа в черновик строки локально, без запроса к API', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), id: 'if-1', name: 'Gi0/1', is_management: false, is_data_transfer: true }]
      const wrapper = mount(DeviceInterfacesEditor, {
        props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, conflicts: { 'if-1': flagsConflict } },
      })
      const fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)

      await wrapper.find('.conflict-icon-btn').trigger('click')
      await wrapper.find('.conflict-modal-actions .btn-secondary').trigger('click')

      expect(fetchMock).not.toHaveBeenCalled()
      const emitted = wrapper.emitted('update:modelValue')!
      const result = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
      expect(result[0].is_management).toBe(true) // взято у соседа
      expect(result[0].is_data_transfer).toBe(false) // взято у соседа
      expect(wrapper.find('.conflict-modal').exists()).toBe(false) // окно закрылось
      expect(wrapper.emitted('neighbors-changed')).toBeFalsy() // соседи не менялись — перечитывать нечего
    })

    it('"Применить текущую конфигурацию" отправляет PUT на интерфейс соседа и закрывает окно', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), id: 'if-1', name: 'Gi0/1', is_management: false, is_data_transfer: true }]
      const wrapper = mount(DeviceInterfacesEditor, {
        props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, conflicts: { 'if-1': flagsConflict } },
      })
      const calls: Array<{ url: string; method: string; body?: unknown }> = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          calls.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body as string) : undefined })
          return jsonResponse({ id: 'if-2', is_management: false, is_data_transfer: true })
        }),
      )

      await wrapper.find('.conflict-icon-btn').trigger('click')
      await wrapper.find('.conflict-modal-actions .btn-primary').trigger('click')
      await flushPromises()

      const call = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/resources/interfaces/if-2'))
      expect(call?.body).toEqual({ is_management: false, is_data_transfer: true })
      expect(wrapper.find('.conflict-modal').exists()).toBe(false)
      // Черновик ЭТОЙ строки не менялся — обновился сосед, а не текущий порт.
      expect(wrapper.emitted('update:modelValue')).toBeFalsy()
      // Родитель считает расхождения по данным соседей с сервера — ему сообщают, что их надо перечитать.
      expect(wrapper.emitted('neighbors-changed')).toHaveLength(1)
    })

    // --- Каскадная смена режима порта (вариант C): «Применить текущую конфигурацию» по режиму порта ---
    describe('режим порта: каскад по группам и связанным портам', () => {
      const CASCADE_URL = '/vlan-mode-cascade'

      function cascadeResult(plan: VlanModeCascadePlan, applied = { ports: 1, groups: 0, devices: 1 }) {
        return { plan, applied, interfaces: [{ id: 'if-3', name: 'Gi0/3', vlan_mode: plan.target_mode }] }
      }

      // Роутер fetch: POST .../vlan-mode-cascade/preview -> предпросмотр, POST .../vlan-mode-cascade -> применение; запросы запоминаются.
      function stubCascadeApi(handlers: { preview: () => Response | Promise<Response>; apply?: () => Response | Promise<Response> }) {
        const calls: Array<{ url: string; method: string; body?: Record<string, unknown> }> = []
        vi.stubGlobal(
          'fetch',
          vi.fn(async (url: string, init?: RequestInit) => {
            const method = init?.method ?? 'GET'
            calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
            if (url.includes(CASCADE_URL)) return url.endsWith('/preview') ? handlers.preview() : (handlers.apply ?? (() => jsonResponse({}, 500)))()
            return jsonResponse({})
          }),
        )
        return calls
      }

      function mountConflict(extra: Record<string, unknown> = {}, rows?: InterfaceDraftRow[], groups: InterfaceGroupDraft[] = []) {
        const draftRows: InterfaceDraftRow[] = rows ?? [{ ...emptyRow(), id: 'if-1', name: 'Gi0/1', vlan_mode: 'access' }]
        return mount(DeviceInterfacesEditor, {
          props: {
            modelValue: draftRows,
            groups,
            typeOptions,
            speedOptions,
            vlanOptions,
            conflicts: { 'if-1': vlanModeConflict },
            deviceId: 'dev-1',
            ...extra,
          },
        })
      }

      async function clickApplyCurrent(wrapper: ReturnType<typeof mount>) {
        await wrapper.find('.expand-toggle').trigger('click')
        await wrapper.find('.vlan-mode-row .conflict-icon-btn').trigger('click')
        await wrapper.find('.conflict-modal-actions .btn-primary').trigger('click')
        await flushPromises()
      }

      function lastEmit<T>(wrapper: ReturnType<typeof mount>, event: string): T {
        const emitted = wrapper.emitted(event)!
        return emitted[emitted.length - 1][0] as T
      }

      beforeEach(() => useToast().toasts.splice(0))

      it('в окне расхождения режима порта есть предупреждение, что смена может затронуть группу и связанные порты', async () => {
        const wrapper = mountConflict()
        await wrapper.find('.expand-toggle').trigger('click')
        await wrapper.find('.vlan-mode-row .conflict-icon-btn').trigger('click')

        expect(wrapper.find('.conflict-modal-hint').text()).toContain('режим сменится у всей группы и у связанных портов')
      })

      it('простой случай (один порт без групп): предпросмотр с целевым режимом и устройством формы, затем сразу применение без окна', async () => {
        const plan = makePlan({ start_interface_id: 'if-3' })
        const calls = stubCascadeApi({ preview: () => jsonResponse(plan), apply: () => jsonResponse(cascadeResult(plan)) })
        const catalogs = useCatalogsStore()
        catalogs.items['interfaces'] = [{ id: 'if-3', name: 'Gi0/3', vlan_mode: 'trunk' }]
        const wrapper = mountConflict()

        await clickApplyCurrent(wrapper)

        // предпросмотр получает целевой режим и СОСТОЯНИЕ ФОРМЫ (режимы портов и групп в черновике), а не только id устройства
        expect(calls[0].method).toBe('POST')
        expect(calls[0].url).toContain('/interfaces/if-3/vlan-mode-cascade/preview')
        expect(calls[0].body).toEqual({
          mode: 'access',
          edited: { device_id: 'dev-1', ports: { 'if-1': { name: 'Gi0/1', mode: 'access', group: null, vlan_ids: [] } }, groups: {} },
        })
        // применение — тот же снимок формы + hash показанного плана
        expect(calls[1]).toMatchObject({
          method: 'POST',
          body: {
            mode: 'access',
            edited: { device_id: 'dev-1', ports: { 'if-1': { name: 'Gi0/1', mode: 'access', group: null, vlan_ids: [] } }, groups: {} },
            plan_hash: 'hash-1',
            confirm: true,
          },
        })
        expect(wrapper.find('.cascade-modal').exists()).toBe(false)
        expect(wrapper.find('.conflict-modal').exists()).toBe(false)
        expect((catalogs.items['interfaces'][0] as unknown as { vlan_mode: string }).vlan_mode).toBe('access') // кэш соседа обновлён — значок расхождения исчезнет
        expect(wrapper.emitted('update:modelValue')).toBeFalsy() // черновик не менялся
        expect(wrapper.emitted('neighbors-changed')).toHaveLength(1) // порты соседей изменены на сервере — родитель перечитает их
      })

      it('сложный случай: открывается окно с последствиями, пока пользователь не подтвердил — применения (POST) нет', async () => {
        const plan = makePlan({
          groups: [groupChange()],
          totals: { ...makePlan().totals, ports: 2, groups: 1 },
          warnings: [{ code: 'groups', severity: 'warning', text: 'Режим задаётся группами.' }],
        })
        const calls = stubCascadeApi({ preview: () => jsonResponse(plan), apply: () => jsonResponse(cascadeResult(plan)) })
        const wrapper = mountConflict()

        await clickApplyCurrent(wrapper)

        expect(wrapper.find('.cascade-modal').exists()).toBe(true)
        expect(wrapper.find('.cascade-warning').text()).toContain('Режим задаётся группами.')
        expect(wrapper.find('.cascade-desc').text()).toContain('«Gi0/3» (sw-03)')
        expect(calls.filter((c) => !c.url.endsWith('/preview'))).toHaveLength(0)
        expect(wrapper.find('.conflict-modal').exists()).toBe(true) // окно расхождения остаётся под ним
        expect(wrapper.emitted('neighbors-changed')).toBeFalsy() // пока ничего не записано — перечитывать нечего
      })

      it('снимаемые VLAN (даже при одном порте) тоже требуют окна подтверждения', async () => {
        const plan = makePlan({
          ports: [portChange({ vlans_before: [vlanRef(10), vlanRef(20)], vlans_after: [vlanRef(10)], dropped_vlans: [vlanRef(20)] })],
          totals: { ...makePlan().totals, dropped_vlans: 1 },
        })
        stubCascadeApi({ preview: () => jsonResponse(plan) })
        const wrapper = mountConflict()

        await clickApplyCurrent(wrapper)

        expect(wrapper.find('.cascade-modal').exists()).toBe(true)
        expect(wrapper.find('.cascade-item-vlans').text()).toContain('будут сняты: 20')
      })

      it('подтверждение: сервер применяет план, изменения устройства формы вносятся в черновик, кэш соседей обновляется, окна закрываются', async () => {
        // Редактируемое устройство: группа g1 (trunk, VLAN 10 и 20) с портом if-3 и одиночный порт if-4.
        const rows: InterfaceDraftRow[] = [
          { ...emptyRow(), id: 'if-1', name: 'Gi0/1', vlan_mode: 'access' },
          { ...emptyRow(), id: 'if-3', name: 'Gi0/3', vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], group_key: 'g1' },
          { ...emptyRow(), id: 'if-4', name: 'Gi0/4', vlan_mode: 'trunk', vlan_ids: ['v20'] },
        ]
        const groups = [
          { id: 'g1', key: 'g1', name: 'Серверные', vlan_mode: 'trunk' as const, vlan_ids: ['v10', 'v20'], ips: [], manage_open_ports: false, open_ports: [] },
        ]
        const plan = makePlan({
          edited_device_id: 'dev-1',
          groups: [
            groupChange({
              id: 'g1',
              name: 'Серверные',
              device_id: 'dev-1',
              device_name: 'esxi-01',
              deferred: true,
              vlans_after: [vlanRef(10)],
              dropped_vlans: [vlanRef(20)],
              ports: [{ id: 'if-3', name: 'Gi0/3' }],
            }),
            groupChange(),
          ],
          ports: [portChange({ id: 'if-4', name: 'Gi0/4', device_id: 'dev-1', device_name: 'esxi-01', deferred: true })],
          devices: [
            { id: 'dev-1', name: 'esxi-01', deferred: true, port_count: 2, group_count: 1 },
            { id: 'dev-2', name: 'sw-02', deferred: false, port_count: 2, group_count: 1 },
          ],
          totals: { ports: 4, devices: 2, groups: 2, deferred_ports: 2, immediate_ports: 2, immediate_devices: 1, dropped_vlans: 1 },
          hash: 'hash-7',
        })
        const calls = stubCascadeApi({ preview: () => jsonResponse(plan), apply: () => jsonResponse(cascadeResult(plan, { ports: 2, groups: 1, devices: 1 })) })
        const catalogs = useCatalogsStore()
        catalogs.items['interfaces'] = [{ id: 'if-3', name: 'Gi0/3', vlan_mode: 'trunk' }]
        const wrapper = mountConflict({}, rows, groups)

        await clickApplyCurrent(wrapper)
        await wrapper.find('.cascade-ack input').setValue(true)
        await wrapper.find('.cascade-actions .btn-primary').trigger('click')
        await flushPromises()

        const post = calls.find((c) => c.method === 'POST' && !c.url.endsWith('/preview'))!
        expect(post.body).toEqual({
          mode: 'access',
          edited: {
            device_id: 'dev-1',
            ports: {
              'if-1': { name: 'Gi0/1', mode: 'access', group: null, vlan_ids: [] },
              'if-3': { name: 'Gi0/3', mode: 'trunk', group: 'g1', vlan_ids: ['v10', 'v20'] },
              'if-4': { name: 'Gi0/4', mode: 'trunk', group: null, vlan_ids: ['v20'] },
            },
            groups: { g1: { name: 'Серверные', mode: 'trunk', vlan_ids: ['v10', 'v20'] } },
          },
          plan_hash: 'hash-7',
          confirm: true,
        })
        const newRows = lastEmit<InterfaceDraftRow[]>(wrapper, 'update:modelValue')
        const newGroups = lastEmit<InterfaceGroupDraft[]>(wrapper, 'update:groups')
        expect(newGroups[0]).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'] })
        expect(newRows.map((r) => [r.name, r.vlan_mode, r.vlan_ids])).toEqual([
          ['Gi0/1', 'access', []],
          ['Gi0/3', 'access', ['v10']], // член группы получил значения группы
          ['Gi0/4', 'access', ['v20']], // одиночный порт: у него был один VLAN — остаётся
        ])
        expect((catalogs.items['interfaces'][0] as unknown as { vlan_mode: string }).vlan_mode).toBe('access')
        expect(wrapper.find('.cascade-modal').exists()).toBe(false)
        expect(wrapper.find('.conflict-modal').exists()).toBe(false)
        const toast = useToast().toasts.at(-1)!
        expect(toast.type).toBe('success')
        expect(toast.message).toContain('в этой форме изменено портов: 2 — сохраните форму')
      })

      // --- «Применить конфигурацию соседа»: режим соседа берёт себе этот порт, в т.ч. порт из группы ---
      async function clickApplyNeighbor(wrapper: ReturnType<typeof mount>) {
        await wrapper.find('.expand-toggle').trigger('click')
        await wrapper.find('.vlan-mode-row .conflict-icon-btn').trigger('click')
        await wrapper.find('.conflict-modal-actions .btn-secondary').trigger('click')
        await flushPromises()
      }

      // Порт формы if-1 (access) и его сосед if-3 (trunk): режим соседа должен получить if-1.
      const ownPortPlan = () =>
        makePlan({
          target_mode: 'trunk',
          start_interface_id: 'if-1',
          edited_device_id: 'dev-1',
          ports: [portChange({ id: 'if-1', name: 'Gi0/1', device_id: 'dev-1', device_name: 'esxi-01', deferred: true, from_mode: 'access', to_mode: 'trunk' })],
          devices: [{ id: 'dev-1', name: 'esxi-01', deferred: true, port_count: 1, group_count: 0 }],
          totals: { ports: 1, devices: 1, groups: 0, deferred_ports: 1, immediate_ports: 0, immediate_devices: 0, dropped_vlans: 0 },
        })

      it('взять режим соседа, затрагивается только эта строка: предпросмотр от СВОЕГО порта, правка черновика, запись на сервер не нужна', async () => {
        const calls = stubCascadeApi({ preview: () => jsonResponse(ownPortPlan()) })
        const wrapper = mountConflict()

        await clickApplyNeighbor(wrapper)

        expect(calls).toHaveLength(1)
        expect(calls[0].url).toContain('/interfaces/if-1/vlan-mode-cascade/preview')
        expect(calls[0].body).toMatchObject({ mode: 'trunk', edited: { device_id: 'dev-1' } })
        expect(lastEmit<InterfaceDraftRow[]>(wrapper, 'update:modelValue')[0].vlan_mode).toBe('trunk')
        expect(wrapper.find('.cascade-modal').exists()).toBe(false)
        expect(wrapper.find('.conflict-modal').exists()).toBe(false)
      })

      describe('порт состоит в группе, которая задаёт режим (раньше — отказ «измените в группе»)', () => {
        const groupRows = (): InterfaceDraftRow[] => [
          { ...emptyRow(), id: 'if-1', name: 'Gi0/1', vlan_mode: 'access', vlan_ids: ['v10'], group_key: 'g1' },
          { ...emptyRow(), id: 'if-2', name: 'Gi0/2', vlan_mode: 'access', vlan_ids: ['v10'], group_key: 'g1' },
        ]
        const groupDraft = (): InterfaceGroupDraft[] => [
          { id: 'g1', key: 'g1', name: 'Серверные', vlan_mode: 'access', vlan_ids: ['v10'], ips: [], manage_open_ports: false, open_ports: [] },
        ]
        const groupPlan = () =>
          makePlan({
            target_mode: 'trunk',
            start_interface_id: 'if-1',
            edited_device_id: 'dev-1',
            groups: [
              groupChange({
                id: 'g1',
                name: 'Серверные',
                device_id: 'dev-1',
                device_name: 'esxi-01',
                deferred: true,
                from_mode: 'access',
                to_mode: 'trunk',
                vlans_before: [vlanRef(10)],
                vlans_after: [vlanRef(10)],
                ports: [
                  { id: 'if-1', name: 'Gi0/1' },
                  { id: 'if-2', name: 'Gi0/2' },
                ],
              }),
            ],
            ports: [portChange({ id: 'if-9', name: 'Gi0/9', device_id: 'dev-9', device_name: 'sw-09', from_mode: 'access', to_mode: 'trunk' })],
            devices: [
              { id: 'dev-1', name: 'esxi-01', deferred: true, port_count: 2, group_count: 1 },
              { id: 'dev-9', name: 'sw-09', deferred: false, port_count: 1, group_count: 0 },
            ],
            totals: { ports: 3, devices: 2, groups: 1, deferred_ports: 2, immediate_ports: 1, immediate_devices: 1, dropped_vlans: 0 },
            hash: 'hash-g',
          })

        it('запускает каскад от своего порта: окно последствий с группой, отказа и ошибки нет', async () => {
          const calls = stubCascadeApi({ preview: () => jsonResponse(groupPlan()) })
          const wrapper = mountConflict({}, groupRows(), groupDraft())

          await clickApplyNeighbor(wrapper)

          expect(calls[0].url).toContain('/interfaces/if-1/vlan-mode-cascade/preview')
          // состав группы и режимы — из ЧЕРНОВИКА формы
          expect(calls[0].body).toMatchObject({
            mode: 'trunk',
            edited: {
              ports: { 'if-1': { mode: 'access', group: 'g1', vlan_ids: ['v10'] }, 'if-2': { mode: 'access', group: 'g1' } },
              groups: { g1: { name: 'Серверные', mode: 'access', vlan_ids: ['v10'] } },
            },
          })
          expect(wrapper.find('.cascade-modal').exists()).toBe(true)
          expect(wrapper.find('.cascade-item-title').text()).toContain('Группа «Серверные»')
          expect(wrapper.find('.cascade-desc').text()).toContain('«Gi0/1» (это устройство)')
          expect(useToast().toasts.filter((t) => t.type === 'error')).toHaveLength(0)
          expect(wrapper.emitted('update:modelValue')).toBeFalsy() // до подтверждения черновик не менялся
        })

        it('подтверждение: группа и все её порты получают режим соседа в черновике, остальные порты пишет сервер', async () => {
          const calls = stubCascadeApi({
            preview: () => jsonResponse(groupPlan()),
            apply: () => jsonResponse(cascadeResult(groupPlan(), { ports: 1, groups: 0, devices: 1 })),
          })
          const wrapper = mountConflict({}, groupRows(), groupDraft())
          await clickApplyNeighbor(wrapper)

          await wrapper.find('.cascade-ack input').setValue(true)
          await wrapper.find('.cascade-actions .btn-primary').trigger('click')
          await flushPromises()

          const post = calls.find((c) => c.method === 'POST' && !c.url.endsWith('/preview'))!
          expect(post.url).toContain('/interfaces/if-1/vlan-mode-cascade')
          expect(post.body).toMatchObject({ mode: 'trunk', plan_hash: 'hash-g', confirm: true, edited: { ports: { 'if-1': { group: 'g1' } } } })
          expect(lastEmit<InterfaceGroupDraft[]>(wrapper, 'update:groups')[0]).toMatchObject({ vlan_mode: 'trunk', vlan_ids: ['v10'] })
          expect(lastEmit<InterfaceDraftRow[]>(wrapper, 'update:modelValue').map((r) => [r.name, r.vlan_mode, r.vlan_ids])).toEqual([
            ['Gi0/1', 'trunk', ['v10']],
            ['Gi0/2', 'trunk', ['v10']],
          ])
          expect(wrapper.find('.cascade-modal').exists()).toBe(false)
          expect(wrapper.find('.conflict-modal').exists()).toBe(false)
          expect(useToast().toasts.at(-1)?.message).toContain('в этой форме изменено портов: 2 — сохраните форму')
        })

        it('«Отмена» в окне: ни запись на сервер, ни правка черновика не выполняются', async () => {
          const calls = stubCascadeApi({ preview: () => jsonResponse(groupPlan()) })
          const wrapper = mountConflict({}, groupRows(), groupDraft())
          await clickApplyNeighbor(wrapper)

          await wrapper.find('.cascade-actions .btn-secondary').trigger('click')

          expect(calls.filter((c) => !c.url.endsWith('/preview'))).toHaveLength(0)
          expect(wrapper.emitted('update:modelValue')).toBeFalsy()
          expect(wrapper.find('.conflict-modal').exists()).toBe(true)
        })
      })

      it('взять режим соседа: режим уже совпадает (пустой план) — сообщение, окно закрывается, черновик не меняется', async () => {
        stubCascadeApi({
          preview: () => jsonResponse(makePlan({ empty: true, groups: [], ports: [], devices: [], totals: { ...makePlan().totals, ports: 0 } })),
        })
        const wrapper = mountConflict()

        await clickApplyNeighbor(wrapper)

        expect(wrapper.find('.conflict-modal').exists()).toBe(false)
        expect(wrapper.emitted('update:modelValue')).toBeFalsy()
        expect(useToast().toasts.at(-1)).toMatchObject({ type: 'info' })
      })

      it('взять режим соседа: ошибка предпросмотра сообщается через notify, окно расхождения остаётся', async () => {
        stubCascadeApi({ preview: () => jsonResponse({ detail: 'Область изменения превышает 1000 портов' }, 422) })
        const wrapper = mountConflict()

        await clickApplyNeighbor(wrapper)

        expect(wrapper.find('.conflict-modal').exists()).toBe(true)
        expect(wrapper.emitted('update:modelValue')).toBeFalsy()
        expect(useToast().toasts.at(-1)).toMatchObject({ type: 'error' })
      })

      it('«Отмена» в окне последствий ничего не применяет и оставляет окно расхождения', async () => {
        const plan = makePlan({ groups: [groupChange()], totals: { ...makePlan().totals, ports: 2, groups: 1 } })
        const calls = stubCascadeApi({ preview: () => jsonResponse(plan) })
        const wrapper = mountConflict()
        await clickApplyCurrent(wrapper)

        await wrapper.find('.cascade-actions .btn-secondary').trigger('click')

        expect(wrapper.find('.cascade-modal').exists()).toBe(false)
        expect(wrapper.find('.conflict-modal').exists()).toBe(true)
        expect(calls.filter((c) => !c.url.endsWith('/preview'))).toHaveLength(0)
      })

      it('409 при применении (данные изменились): запрашивается новый план, окно показывает его и просит подтвердить заново', async () => {
        const first = makePlan({ groups: [groupChange()], totals: { ...makePlan().totals, ports: 2, groups: 1 }, hash: 'old' })
        const second = makePlan({
          groups: [groupChange(), groupChange({ id: 'g10', name: 'Резерв' })],
          totals: { ...makePlan().totals, ports: 4, groups: 2 },
          hash: 'new',
        })
        let previews = 0
        const calls = stubCascadeApi({
          preview: () => jsonResponse(previews++ === 0 ? first : second),
          apply: () => jsonResponse({ detail: 'Данные изменились после предпросмотра — повторите операцию' }, 409),
        })
        const wrapper = mountConflict()
        await clickApplyCurrent(wrapper)
        await wrapper.find('.cascade-ack input').setValue(true)

        await wrapper.find('.cascade-actions .btn-primary').trigger('click')
        await flushPromises()

        expect(calls.filter((c) => c.url.endsWith('/preview'))).toHaveLength(2)
        expect(wrapper.find('.cascade-modal').exists()).toBe(true)
        expect(wrapper.find('.cascade-desc').text()).toContain('портов — 4')
        expect((wrapper.find('.cascade-ack input').element as HTMLInputElement).checked).toBe(false) // подтверждение сброшено
        expect(useToast().toasts.at(-1)).toMatchObject({ type: 'warning' })
        expect(wrapper.emitted('update:modelValue')).toBeFalsy()
      })

      it('режим уже совпадает (пустой план): сообщение, без применения, окно закрывается', async () => {
        const calls = stubCascadeApi({
          preview: () => jsonResponse(makePlan({ empty: true, groups: [], ports: [], devices: [], totals: { ...makePlan().totals, ports: 0 } })),
        })
        const wrapper = mountConflict()

        await clickApplyCurrent(wrapper)

        expect(calls.filter((c) => !c.url.endsWith('/preview'))).toHaveLength(0)
        expect(wrapper.find('.conflict-modal').exists()).toBe(false)
        expect(useToast().toasts.at(-1)).toMatchObject({ type: 'info' })
      })

      it('ошибка предпросмотра не закрывает окно расхождения молча — сообщается через notify', async () => {
        stubCascadeApi({ preview: () => jsonResponse({ detail: 'Область изменения превышает 1000 портов' }, 422) })
        const wrapper = mountConflict()

        await clickApplyCurrent(wrapper)

        expect(wrapper.find('.conflict-modal').exists()).toBe(true)
        expect(wrapper.find('.cascade-modal').exists()).toBe(false)
        expect(useToast().toasts.at(-1)).toMatchObject({ type: 'error' })
      })
    })

    it('ошибка запроса при "Применить текущую конфигурацию" не закрывает окно молча — сообщается через notify', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), id: 'if-1', name: 'Gi0/1' }]
      const wrapper = mount(DeviceInterfacesEditor, {
        props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, conflicts: { 'if-1': flagsConflict } },
      })
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => jsonResponse({ detail: 'Интерфейс не найден' }, 404)),
      )

      await wrapper.find('.conflict-icon-btn').trigger('click')
      await wrapper.find('.conflict-modal-actions .btn-primary').trigger('click')
      await flushPromises()

      expect(wrapper.find('.conflict-modal').exists()).toBe(true) // окно осталось открытым
      expect(wrapper.emitted('neighbors-changed')).toBeFalsy() // запись не удалась — соседи прежние
    })
  })
})

// Группы портов (правка формы устройства, п.4): у членов группы поля, которыми управляет группа,
// недоступны для правки в строке — значения задаёт группа, иначе следующее сохранение перезаписало бы
// ручную правку (сервер применяет параметры группы поверх значений порта).
describe('DeviceInterfacesEditor.vue — группы портов', () => {
  const groupVlans: VLANDefinition[] = [
    { id: 'v10', vlan_id: 10, name: 'Серверы', description: '', domain_id: null, domain_name: '', devices: [] },
    { id: 'v20', vlan_id: 20, name: 'Гости', description: '', domain_id: null, domain_name: '', devices: [] },
  ]

  function group(patch: Partial<InterfaceGroupDraft> = {}): InterfaceGroupDraft {
    return { id: 'g1', key: 'g1', name: 'Серверные', vlan_mode: '', vlan_ids: [], ips: [], manage_open_ports: false, open_ports: [], ...patch }
  }

  function member(name: string, patch: Partial<InterfaceDraftRow> = {}): InterfaceDraftRow {
    return { ...emptyRow(), name, group_key: 'g1', ...patch }
  }

  function mountEditor(rows: InterfaceDraftRow[], groups: InterfaceGroupDraft[]) {
    return mount(DeviceInterfacesEditor, { props: { modelValue: rows, groups, typeOptions, speedOptions, vlanOptions: groupVlans } })
  }

  beforeEach(() => useToast().toasts.splice(0))

  it('показывает панель групп и имя группы в строке её порта', () => {
    const wrapper = mountEditor(
      [member('Gi0/1'), { ...emptyRow(), name: 'Gi0/2' }],
      [group({ ips: [{ ip_address: '10.0.0.5', prefix_length: '', purpose: '' }] })],
    )

    expect(wrapper.find('.groups-panel').text()).toContain('Серверные')
    const summaries = wrapper.findAll('.expand-toggle').map((b) => b.text())
    expect(summaries[0]).toContain('Группа «Серверные»')
    expect(summaries[1]).not.toContain('Группа')
  })

  it('у члена группы заблокированы управляемые ею режим порта, VLAN и IP; у порта вне группы — нет', async () => {
    const rows = [
      member('Gi0/1', { vlan_mode: 'access', vlan_ids: ['v10'], ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] }),
      { ...emptyRow(), name: 'Gi0/2', ips: [{ ip_address: '192.168.0.1', prefix_length: '24', purpose: '' }] },
    ]
    const wrapper = mountEditor(rows, [group({ vlan_mode: 'access', vlan_ids: ['v10'], ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] })])
    await expandRow(wrapper, 0)
    await expandRow(wrapper, 1)

    const [locked, free] = wrapper.findAll('.iface-detail')
    for (const radio of locked.findAll('input[type="radio"]')) expect(radio.attributes('disabled')).toBeDefined()
    expect(locked.find('.vlan-block .searchable-select input').attributes('disabled')).toBeDefined()
    expect(locked.find('.ip-row input[placeholder="IP-адрес"]').attributes('disabled')).toBeDefined()
    expect(locked.find('.ip-row input[placeholder="Префикс"]').attributes('disabled')).toBeDefined()
    expect(locked.find('button[aria-label="Удалить IP интерфейса"]').exists()).toBe(false)
    expect(locked.text()).toContain('задан группой «Серверные»')

    for (const radio of free.findAll('input[type="radio"]')) expect(radio.attributes('disabled')).toBeUndefined()
    expect(free.find('.ip-row input[placeholder="IP-адрес"]').attributes('disabled')).toBeUndefined()
    expect(free.find('button[aria-label="Удалить IP интерфейса"]').exists()).toBe(true)
    expect(free.text()).not.toContain('задан группой')
  })

  it('у члена группы, задающей назначение IP, поле «Назначение» заблокировано вместе с адресом и префиксом; у порта вне группы — нет', async () => {
    const ip = (purpose: string) => [{ ip_address: '10.0.0.5', prefix_length: '24', purpose }]
    const rows = [member('Gi0/1', { ips: ip('Администрирование') }), { ...emptyRow(), name: 'Gi0/2', ips: ip('Своё') }]
    const wrapper = mountEditor(rows, [group({ ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'Администрирование' }] })])
    await expandRow(wrapper, 0)
    await expandRow(wrapper, 1)

    const [locked, free] = wrapper.findAll('.iface-detail')
    expect(locked.find('.ip-row input[placeholder="Назначение"]').attributes('disabled')).toBeDefined()
    expect(locked.find('.ip-row input[placeholder="IP-адрес"]').attributes('disabled')).toBeDefined()
    expect(locked.text()).toContain('IP-адрес и его назначение задан группой «Серверные»')
    expect(free.find('.ip-row input[placeholder="Назначение"]').attributes('disabled')).toBeUndefined()
  })

  it('поле «Назначение» заблокировано, как только группа задаёт IP, — даже если назначение в самой группе пустое', async () => {
    const rows = [member('Gi0/1', { ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] })]
    const wrapper = mountEditor(rows, [group({ ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] })])
    await expandRow(wrapper)

    const detail = wrapper.find('.iface-detail')
    for (const placeholder of ['IP-адрес', 'Префикс', 'Назначение']) {
      expect(detail.find(`.ip-row input[placeholder="${placeholder}"]`).attributes('disabled')).toBeDefined()
    }
    expect(detail.text()).toContain('IP-адрес и его назначение задан группой «Серверные»')
  })

  it('если группа общего IP не задаёт, поле «Назначение» IP порта остаётся редактируемым', async () => {
    const rows = [member('Gi0/1', { ips: [{ ip_address: '192.168.0.1', prefix_length: '24', purpose: 'Своё' }] })]
    const wrapper = mountEditor(rows, [group({ vlan_mode: 'access', vlan_ids: ['v10'] })])
    await expandRow(wrapper)

    expect(wrapper.find('.iface-detail .ip-row input[placeholder="Назначение"]').attributes('disabled')).toBeUndefined()
  })

  it('параметры, которыми группа не управляет, в строке её порта остаются редактируемыми', async () => {
    const wrapper = mountEditor([member('Gi0/1')], [group({ ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] })])
    await expandRow(wrapper)

    const detail = wrapper.find('.iface-detail')
    for (const radio of detail.findAll('input[type="radio"]')) expect(radio.attributes('disabled')).toBeUndefined()
    expect(detail.find('.ports-block .add-btn').exists()).toBe(true)
  })

  it('открытые порты порта, заданные группой, доступны только для чтения', async () => {
    const rows = [
      member('Gi0/1', { open_ports: [{ protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }] }),
      { ...emptyRow(), name: 'Gi0/2' },
    ]
    const wrapper = mountEditor(rows, [
      group({ manage_open_ports: true, open_ports: [{ protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }] }),
    ])
    await expandRow(wrapper, 0)

    const block = wrapper.find('.ports-block')
    expect(block.find('.add-btn').exists()).toBe(false)
    expect(block.find('.copy-ports-row').exists()).toBe(false)
    expect(block.text()).toContain('Список открытых портов задан группой')
  })

  it('массовое редактирование не меняет режим порта и VLAN у портов, где их задаёт группа, но применяется к остальным', async () => {
    const rows: InterfaceDraftRow[] = [member('Gi0/1', { vlan_mode: 'access', vlan_ids: ['v10'] }), { ...emptyRow(), name: 'Gi0/2', vlan_mode: 'access' }]
    const wrapper = mountEditor(rows, [group({ vlan_mode: 'access', vlan_ids: ['v10'] })])

    await wrapper.findAll('.iface-row input[aria-label="Выбрать интерфейс"]')[0].setValue(true)
    await wrapper.findAll('.iface-row input[aria-label="Выбрать интерфейс"]')[1].setValue(true)
    await wrapper.find('select[aria-label="Режим порта — массовое редактирование"]').setValue('trunk')
    await wrapper.find('button[aria-label="Применить к выбранным"]').trigger('click')

    const emitted = wrapper.emitted('update:modelValue') as InterfaceDraftRow[][][]
    const result = emitted[emitted.length - 1][0]
    expect(result[0]).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'] })
    expect(result[1].vlan_mode).toBe('trunk')
  })

  it('открытые порты нельзя скопировать на порт, чей список задаёт группа', async () => {
    const source = { ...emptyRow(), name: 'Gi0/1', open_ports: [{ protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }] }
    const target = member('Gi0/2')
    const wrapper = mountEditor([source, target], [group({ manage_open_ports: true })])
    await expandRow(wrapper, 0)

    await wrapper.find('.copy-target-select').setValue('1')
    await wrapper.find('.copy-ports-row .btn').trigger('click')

    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(
      useToast()
        .toasts.map((t) => t.message)
        .join(' '),
    ).toContain('задан группой «Серверные»')
  })

  it('создание группы в панели отдаёт наружу и порты, и группы (v-model и v-model:groups)', async () => {
    const wrapper = mountEditor([{ ...emptyRow(), name: 'Gi0/1' }], [])

    await wrapper.find('.groups-head button').trigger('click')
    await wrapper.find('.group-modal .field input').setValue('Новая')
    await wrapper.findAll('.member-check input')[0].setValue(true)
    await wrapper.find('input[aria-label="Общий IP-адрес группы"]').setValue('10.1.1.1')
    await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

    const groups = (wrapper.emitted('update:groups') as InterfaceGroupDraft[][][])[0][0]
    const rows = (wrapper.emitted('update:modelValue') as InterfaceDraftRow[][][])[0][0]
    expect(groups[0]).toMatchObject({ name: 'Новая', ips: [expect.objectContaining({ ip_address: '10.1.1.1' })] })
    expect(rows[0]).toMatchObject({ group_key: groups[0].key })
    expect(rows[0].ips[0].ip_address).toBe('10.1.1.1')
  })
})

describe('DeviceInterfacesEditor.vue — блок «Подключение» порта', () => {
  const connected = {
    peer_device_id: 'dev-b',
    peer_device_name: 'sw-b',
    peer_interface_id: 'b-1',
    peer_interface_name: 'Gi0/1',
    connection_type_id: 'ct-1',
    description: '',
  }

  // Свободные порты соседа приходят с сервера (api/deviceConnectivity.ts): здесь — порты sw-b без занятых.
  function stubPeerPorts(ports: Array<{ id: string; name: string; occupied?: boolean }>) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const include = new Set(new URLSearchParams(url.split('?')[1] ?? '').getAll('include'))
        const items = ports
          .filter((p) => !p.occupied || include.has(p.id))
          .map((p) => ({ is_management: false, is_data_transfer: false, vlan_mode: 'access', occupied: false, ...p }))
        return new Response(JSON.stringify({ items, total: items.length, offset: 0, limit: 200 }))
      }),
    )
  }

  function mountWith(rows: InterfaceDraftRow[], editConnections?: boolean) {
    stubPeerPorts([{ id: 'b-1', name: 'Gi0/1' }])
    return mount(DeviceInterfacesEditor, {
      props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, deviceId: 'dev-1', ...(editConnections === undefined ? {} : { editConnections }) },
    })
  }

  it('по умолчанию (окно «Управлять портами») блока «Подключение» нет — подключения там не сохраняются', async () => {
    const wrapper = mountWith([{ ...emptyRow(), id: 'if-1', name: 'eth0' }])
    await expandRow(wrapper)
    expect(wrapper.find('.connection-block').exists()).toBe(false)
  })

  it('с editConnections блок показан в раскрытой строке; «Подключить» кладёт черновик в connection строки', async () => {
    const wrapper = mountWith([{ ...emptyRow(), id: 'if-1', name: 'eth0' }], true)
    expect(wrapper.find('.connection-block').exists()).toBe(false) // свёрнутая строка — деталей нет
    await expandRow(wrapper)

    await wrapper.find('.connection-connect-btn').trigger('click')

    const rows = wrapper.emitted('update:modelValue')!.at(-1)![0] as InterfaceDraftRow[]
    expect(rows[0].connection).toEqual({ peer_device_id: '', peer_interface_id: '', connection_type_id: '', description: '' })
  })

  it('свёрнутая строка подписана подключением: «↔ устройство · порт»; незаконченное — «порт не выбран»; без подключения подписи нет', () => {
    const wrapper = mountWith(
      [
        { ...emptyRow(), id: 'if-1', name: 'eth0', connection: connected },
        { ...emptyRow(), id: 'if-2', name: 'eth1', connection: { ...connected, peer_interface_id: '' } },
        { ...emptyRow(), id: 'if-3', name: 'eth2', connection: null },
      ],
      true,
    )
    const toggles = wrapper.findAll('.expand-toggle').map((t) => t.text())
    expect(toggles[0]).toContain('↔ sw-b · Gi0/1')
    expect(toggles[1]).toContain('↔ порт не выбран')
    expect(toggles[2]).not.toContain('↔')
  })

  it('порт соседа, выбранный в другой строке, не предлагается в этой', async () => {
    const wrapper = mountWith(
      [
        { ...emptyRow(), id: 'if-1', name: 'eth0', connection: connected },
        { ...emptyRow(), id: 'if-2', name: 'eth1', connection: { ...connected, peer_interface_id: '' } },
      ],
      true,
    )
    stubPeerPorts([
      { id: 'b-1', name: 'Gi0/1' },
      { id: 'b-2', name: 'Gi0/2' },
    ])
    await wrapper.findAll('.expand-toggle')[1].trigger('click')
    await flushPromises() // свободные порты sw-b приходят с сервера

    const select = wrapper.find('.iface-detail-row .connection-peer-port .searchable-select')
    await select.find('input').trigger('focus')
    expect(select.findAll('.ss-option').map((o) => o.text())).toEqual(['Gi0/2'])
  })
})

describe('DeviceInterfacesEditor.vue — подключения между портами этого устройства и обмен соседями', () => {
  const toRow = (key: string, extra: Record<string, unknown> = {}) => ({
    peer_device_id: '__self__',
    peer_interface_id: '',
    peer_row_key: key,
    connection_type_id: 'ct-1',
    description: '',
    ...extra,
  })
  const toPort = (id: string, extra: Record<string, unknown> = {}) => ({
    peer_device_id: 'dev-b',
    peer_device_name: 'sw-b',
    peer_interface_id: id,
    connection_type_id: 'ct-1',
    description: '',
    ...extra,
  })
  const row = (name: string, extra: Partial<InterfaceDraftRow> = {}): InterfaceDraftRow => ({ ...emptyRow(), name, ...extra })

  function mountWith(rows: InterfaceDraftRow[], extra: Record<string, unknown> = {}) {
    useCatalogsStore().items['interfaces'] = [] as never
    // Редактор подключения просит порты соседа у сервера; здесь это не предмет проверки — отвечаем пустой страницей.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 200 }))),
    )
    return mount(DeviceInterfacesEditor, {
      props: { modelValue: rows, typeOptions, speedOptions, vlanOptions, deviceId: null, editConnections: true, ...extra },
    })
  }
  const lastRows = (wrapper: ReturnType<typeof mount>) => wrapper.emitted('update:modelValue')!.at(-1)![0] as InterfaceDraftRow[]
  async function expandAll(wrapper: ReturnType<typeof mount>, count: number) {
    for (let i = count - 1; i >= 0; i--) await expandRow(wrapper, i)
  }
  const editors = (wrapper: ReturnType<typeof mount>) => wrapper.findAllComponents(InterfaceConnectionEditor)

  it('«+ Интерфейс» с редактированием подключений даёт строке уникальный ключ; без — ключа нет', async () => {
    const withKeys = mountWith([row('eth0', { key: 'k0' })])
    // Кнопка добавления — по тексту: в панели несколько кнопок.
    await withKeys
      .findAll('button')
      .find((b) => b.text().includes('Интерфейс'))!
      .trigger('click')
    const added = lastRows(withKeys).at(-1)!
    expect(added.key).toBeTruthy()
    expect(added.key).not.toBe('k0')

    const plain = mountWith([], { editConnections: false })
    await plain
      .findAll('button')
      .find((b) => b.text().includes('Интерфейс'))!
      .trigger('click')
    expect(lastRows(plain)[0]).not.toHaveProperty('key')
  })

  it('строки без id и без ключа (копия устройства) получают ключи сразу при показе; строки с id или ключом не трогаются', () => {
    const wrapper = mountWith([row('a'), row('b', { key: 'kept' }), row('c', { id: 'if-3' })])
    const rows = lastRows(wrapper)
    expect(rows[0].key).toBeTruthy()
    expect(rows[1].key).toBe('kept')
    expect(rows[2]).not.toHaveProperty('key')
  })

  it('без editConnections ключи не назначаются и модель не перезаписывается', () => {
    const wrapper = mountWith([row('a')], { editConnections: false })
    expect(wrapper.emitted('update:modelValue')).toBeFalsy()
  })

  it('кандидаты в соседи — другие порты устройства: без самой строки, без портов с собственным подключением и без выбранных соседом другой строкой', async () => {
    const rows = [
      row('eth0', { key: 'k0' }),
      row('eth1', { key: 'k1' }),
      row('eth2', { key: 'k2', connection: toPort('b-1') }), // у порта своё подключение
      row('eth3', { id: 'if-4' }),
      row('eth4', { key: 'k4' }), // его уже выбрала eth5
      row('eth5', { key: 'k5', connection: toRow('k4') }),
    ]
    const wrapper = mountWith(rows)
    await expandAll(wrapper, rows.length)

    const selfPorts = (i: number) => editors(wrapper)[i].props('selfPorts') as unknown as SelfPortCandidate[]
    // eth2 и eth5 имеют собственные подключения, eth4 уже выбрала eth5 — остаются только eth1 и eth3.
    expect(selfPorts(0).map((c) => c.label)).toEqual(['eth1 (строка 2)', 'eth3 (строка 4)'])
    // несохранённая строка адресуется ключом, сохранённая — id
    expect(selfPorts(0)[0]).toMatchObject({ value: 'row:k1', rowKey: 'k1' })
    expect(selfPorts(0)[1]).toMatchObject({ value: 'if-4', interfaceId: 'if-4' })
    // у выбравшей строки её сосед остаётся в списке
    expect(selfPorts(5).map((c) => c.label)).toContain('eth4 (строка 5)')
    // а у остальных строк eth4 уже недоступен
    expect(selfPorts(1).map((c) => c.label)).not.toContain('eth4 (строка 5)')
  })

  it('порт, уже указывающий на эту строку, в её списке не предлагается: кабель описывается с одной стороны', async () => {
    const rows = [row('eth0', { key: 'k0', connection: toRow('k1') }), row('eth1', { key: 'k1' })]
    const wrapper = mountWith(rows)
    await expandAll(wrapper, 2)
    expect((editors(wrapper)[1].props('selfPorts') as unknown as SelfPortCandidate[]).map((c) => c.label)).toEqual([])
  })

  it('удаление строки снимает ссылки на неё в подключениях других портов: сосед сбрасывается, остальное остаётся', async () => {
    const rows = [
      row('eth0', { key: 'k0', connection: toRow('k1', { description: 'кабель' }) }),
      row('eth1', { key: 'k1' }),
      row('eth2', { key: 'k2', connection: toPort('b-1') }),
    ]
    const wrapper = mountWith(rows)

    await wrapper.findAll('button[aria-label="Удалить интерфейс"]')[1].trigger('click')

    const next = lastRows(wrapper)
    expect(next.map((r) => r.name)).toEqual(['eth0', 'eth2'])
    expect(next[0].connection).toEqual({ peer_device_id: '__self__', peer_interface_id: '', connection_type_id: 'ct-1', description: 'кабель' })
    expect(next[0].connection).not.toHaveProperty('peer_row_key')
    expect(next[1].connection).toMatchObject({ peer_interface_id: 'b-1' }) // чужое подключение не тронуто
  })

  it('удаление сохранённой строки снимает ссылки на её id', async () => {
    const rows = [row('eth0', { id: 'if-1', connection: toPort('if-2', { peer_device_id: 'dev-1' }) }), row('eth1', { id: 'if-2' })]
    const wrapper = mountWith(rows)
    await wrapper.findAll('button[aria-label="Удалить интерфейс"]')[1].trigger('click')
    expect(lastRows(wrapper)[0].connection).toMatchObject({ peer_interface_id: '' })
  })

  it('свёрнутая строка с соседом из этой же формы подписана «↔ это устройство · имя порта»', () => {
    const wrapper = mountWith([row('eth0', { key: 'k0', connection: toRow('k1') }), row('uplink', { key: 'k1' })])
    expect(wrapper.findAll('.expand-toggle')[0].text()).toContain('↔ это устройство · uplink')
  })

  it('порты других устройств, освобождаемые формой, передаются редактору подключения: отключённый и переставленный порт', async () => {
    const baseline = new Map([
      ['if-1', toPort('b-1')],
      ['if-2', toPort('b-2')],
      ['if-3', toPort('b-3')],
    ])
    const rows = [
      row('eth0', { id: 'if-1', connection: null }), // отключён → b-1 свободен
      row('eth1', { id: 'if-2', connection: toPort('b-9') }), // переставлен → b-2 свободен
      row('eth2', { id: 'if-3', connection: toPort('b-3') }), // не менялся → b-3 по-прежнему занят
    ]
    const wrapper = mountWith(rows, { connectionBaseline: baseline })
    await expandAll(wrapper, 3)
    const freed = [...(editors(wrapper)[0].props('freedPeerIds') as Set<string>)].sort()
    expect(freed).toEqual(['b-1', 'b-2'])
  })

  it('без снимка подключений освобождаемых портов нет', async () => {
    const wrapper = mountWith([row('eth0', { id: 'if-1', connection: null })])
    await expandAll(wrapper, 1)
    expect([...(editors(wrapper)[0].props('freedPeerIds') as Set<string>)]).toEqual([])
  })
})

describe('DeviceInterfacesEditor.vue — расхождение с соседом при редактировании подключения: применить конфигурацию соседа или текущую', () => {
  const connected = {
    peer_device_id: 'dev-b',
    peer_device_name: 'sw-b',
    peer_interface_id: 'b-1',
    peer_interface_name: 'Gi0/1',
    connection_type_id: 'ct-1',
    description: '',
  }
  const toRow = (key: string) => ({ peer_device_id: '__self__', peer_interface_id: '', peer_row_key: key, connection_type_id: 'ct-1', description: '' })
  const row = (name: string, extra: Partial<InterfaceDraftRow> = {}): InterfaceDraftRow => ({ ...emptyRow(), name, ...extra })
  const lastRows = (wrapper: ReturnType<typeof mount>) => wrapper.emitted('update:modelValue')!.at(-1)![0] as InterfaceDraftRow[]
  const toastText = () =>
    useToast()
      .toasts.map((t) => t.message)
      .join(' | ')

  interface Call {
    url: string
    method: string
    body?: Record<string, unknown>
  }

  // Фейковый сервер: порт соседа b-1 (свободные порты sw-b) с изменяемой конфигурацией; PUT на ресурс interfaces
  // меняет её, поэтому после «Применить текущую конфигурацию» повторное чтение портов соседа уже без расхождения.
  function stubServer(neighbor: { is_management: boolean; is_data_transfer: boolean; vlan_mode: 'access' | 'trunk' }, cascadePreview?: () => Response) {
    const calls: Call[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        const body = init?.body ? (JSON.parse(init.body as string) as Record<string, unknown>) : undefined
        calls.push({ url, method, body })
        if (method === 'PUT' && url.endsWith('/resources/interfaces/b-1')) {
          Object.assign(neighbor, body)
          return jsonResponse({ id: 'b-1', ...neighbor })
        }
        if (url.includes('/vlan-mode-cascade/preview') && cascadePreview) return cascadePreview()
        if (/\/devices\/dev-b\/free-interfaces/.test(url)) {
          return jsonResponse({ items: [{ id: 'b-1', name: 'Gi0/1', occupied: false, ...neighbor }], total: 1, offset: 0, limit: 200 })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 200 })
      }),
    )
    return calls
  }

  // Родитель держит v-model: изменения строк возвращаются в props, как в DeviceFormModal.
  function mountLive(rows: InterfaceDraftRow[], extra: Record<string, unknown> = {}) {
    useCatalogsStore().items['interfaces'] = [] as never
    const wrapper = mount(DeviceInterfacesEditor, {
      props: {
        modelValue: rows,
        typeOptions,
        speedOptions,
        vlanOptions,
        deviceId: 'dev-1',
        editConnections: true,
        ...extra,
        'onUpdate:modelValue': (value: InterfaceDraftRow[]) => wrapper.setProps({ modelValue: value }),
      },
    })
    return wrapper
  }
  const applyButtons = (wrapper: ReturnType<typeof mount>) => wrapper.findAll('.connection-diffs-actions button')

  beforeEach(() => useToast().toasts.splice(0))

  it('«Применить конфигурацию соседа»: порту сразу и назначение, и режим соседа (правка назначения не теряется при смене режима)', async () => {
    stubServer({ is_management: true, is_data_transfer: true, vlan_mode: 'trunk' })
    const wrapper = mountLive([row('eth0', { key: 'k0', connection: connected })], { deviceId: null })
    await expandRow(wrapper)
    await flushPromises()
    expect(wrapper.find('.connection-diffs').exists()).toBe(true) // сообщение появилось само, до сохранения формы

    await applyButtons(wrapper)[0].trigger('click')
    await flushPromises()

    expect(lastRows(wrapper)[0]).toMatchObject({ is_management: true, is_data_transfer: true, vlan_mode: 'trunk' })
    expect(toastText()).toContain('применена конфигурация соседа — сохраните форму')
    expect(wrapper.find('.connection-diffs').exists()).toBe(false)
  })

  it('«Применить текущую конфигурацию» соседу на другом устройстве: PUT назначения сразу, строка формы не меняется, панель обновляется', async () => {
    const calls = stubServer({ is_management: true, is_data_transfer: false, vlan_mode: 'access' })
    const wrapper = mountLive([row('eth0', { id: 'if-1', is_management: false, is_data_transfer: true, vlan_mode: 'access', connection: connected })])
    await expandRow(wrapper)
    await flushPromises()

    await applyButtons(wrapper)[1].trigger('click')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/resources/interfaces/b-1'))
    expect(put?.body).toEqual({ is_management: false, is_data_transfer: true })
    expect(wrapper.emitted('update:modelValue')).toBeUndefined() // порт этой строки не менялся
    expect(wrapper.emitted('neighbors-changed')).toHaveLength(1)
    expect(toastText()).toContain('изменено сразу')
    expect(wrapper.find('.connection-diffs').exists()).toBe(false) // порты соседа перечитаны — расхождения нет
  })

  it('соседу на другом устройстве режим уходит каскадом от порта соседа: предпросмотр с режимом ЭТОГО порта, назначение — отдельным PUT', async () => {
    const calls = stubServer({ is_management: true, is_data_transfer: true, vlan_mode: 'access' }, () =>
      jsonResponse(makePlan({ target_mode: 'trunk', start_interface_id: 'b-1' })),
    )
    const wrapper = mountLive([row('eth0', { id: 'if-1', is_management: false, is_data_transfer: true, vlan_mode: 'trunk', connection: connected })])
    await expandRow(wrapper)
    await flushPromises()

    await applyButtons(wrapper)[1].trigger('click')
    await flushPromises()

    expect(calls.find((c) => c.method === 'PUT' && c.url.endsWith('/resources/interfaces/b-1'))?.body).toEqual({ is_management: false, is_data_transfer: true })
    const preview = calls.find((c) => c.url.endsWith('/interfaces/b-1/vlan-mode-cascade/preview'))
    expect(preview?.body).toMatchObject({ mode: 'trunk' })
  })

  it('сосед — другой порт этого устройства: правится его строка черновика (назначение и режим), запросов на запись нет', async () => {
    const calls = stubServer({ is_management: false, is_data_transfer: false, vlan_mode: 'access' })
    const rows = [
      row('eth0', { key: 'kA', is_management: true, is_data_transfer: false, vlan_mode: 'access', connection: toRow('kB') }),
      row('eth1', { key: 'kB', is_management: false, is_data_transfer: true, vlan_mode: 'trunk', connection: toRow('kA') }),
    ]
    const wrapper = mountLive(rows, { deviceId: null })
    await expandRow(wrapper, 0)
    await flushPromises()
    expect(wrapper.find('.connection-diffs').exists()).toBe(true)

    await applyButtons(wrapper)[1].trigger('click')
    await flushPromises()

    expect(lastRows(wrapper)[1]).toMatchObject({ name: 'eth1', is_management: true, is_data_transfer: false, vlan_mode: 'access' })
    expect(lastRows(wrapper)[0]).toMatchObject({ name: 'eth0', is_management: true, vlan_mode: 'access' }) // текущий порт не тронут
    expect(calls.filter((c) => c.method !== 'GET')).toEqual([])
    expect(toastText()).toContain('применена текущая конфигурация — сохраните форму')
    expect(wrapper.find('.connection-diffs').exists()).toBe(false)
  })

  it('режим не сохранённого порта, заданный его группой, не меняется: предупреждение вместо правки (назначение при этом применяется)', async () => {
    stubServer({ is_management: true, is_data_transfer: false, vlan_mode: 'trunk' })
    const group: InterfaceGroupDraft = { key: 'g1', name: 'Серверные', vlan_mode: 'access', vlan_ids: [], ips: [], manage_open_ports: false, open_ports: [] }
    const wrapper = mountLive([row('eth0', { key: 'k0', group_key: 'g1', vlan_mode: 'access', connection: connected })], { deviceId: null, groups: [group] })
    await expandRow(wrapper)
    await flushPromises()

    await applyButtons(wrapper)[0].trigger('click')
    await flushPromises()

    expect(lastRows(wrapper)[0]).toMatchObject({ is_management: true, vlan_mode: 'access' })
    expect(toastText()).toContain('задан группой «Серверные»')
  })

  it('сервер отклонил запись соседу: ошибка в уведомлении, расхождение остаётся, кнопки снова доступны', async () => {
    useCatalogsStore().items['interfaces'] = [] as never
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'PUT') return jsonResponse({ detail: 'Нет прав на изменение порта' }, 403)
        return jsonResponse({
          items: [{ id: 'b-1', name: 'Gi0/1', occupied: false, is_management: true, is_data_transfer: false, vlan_mode: 'access' }],
          total: 1,
          offset: 0,
          limit: 200,
        })
      }),
    )
    const wrapper = mountLive([row('eth0', { id: 'if-1', is_management: false, is_data_transfer: true, connection: connected })])
    await expandRow(wrapper)
    await flushPromises()

    await applyButtons(wrapper)[1].trigger('click')
    await flushPromises()

    expect(toastText()).toContain('Нет прав на изменение порта')
    expect(wrapper.find('.connection-diffs').exists()).toBe(true)
    expect(applyButtons(wrapper).every((b) => b.attributes('disabled') === undefined)).toBe(true)
    expect(wrapper.emitted('neighbors-changed')).toBeUndefined()
  })

  describe('проверка расхождений перед сохранением формы (reviewNeighborMismatches)', () => {
    const snapshot = (is_management: boolean) => new Map([['if-1', { is_management, is_data_transfer: true, vlan_mode: 'access' as const }]])
    const dialog = (wrapper: ReturnType<typeof mount>) => wrapper.find('.review-modal')
    const dialogButton = (wrapper: ReturnType<typeof mount>, text: string) => {
      const button = wrapper.findAll('.review-modal button').find((b) => b.text() === text)
      if (!button) throw new Error(`В диалоге нет кнопки «${text}»`)
      return button
    }
    // Порт if-1 «Управление» нет, «Передача данных» есть; сосед b-1 — наоборот по «Управлению».
    const savedRow = (extra: Partial<InterfaceDraftRow> = {}) =>
      row('eth0', { id: 'if-1', is_management: false, is_data_transfer: true, vlan_mode: 'access', connection: connected, ...extra })
    const NEIGHBOR = { is_management: true, is_data_transfer: true, vlan_mode: 'access' as const }
    type ReviewVm = {
      reviewNeighborMismatches: (
        initial?: ReadonlyMap<string, { is_management: boolean; is_data_transfer: boolean; vlan_mode: 'access' | 'trunk' }>,
      ) => Promise<boolean>
    }
    const review = (wrapper: ReturnType<typeof mount>, initial?: Parameters<ReviewVm['reviewNeighborMismatches']>[0]) =>
      (wrapper.vm as unknown as ReviewVm).reviewNeighborMismatches(initial)

    it('нет редактирования подключений (окно «Управлять портами») — сразу true, к серверу не обращается', async () => {
      const calls = stubServer({ ...NEIGHBOR })
      const wrapper = mountLive([savedRow()], { editConnections: false })
      expect(await review(wrapper)).toBe(true)
      expect(calls).toEqual([])
      expect(dialog(wrapper).exists()).toBe(false)
    })

    it('прежнее, никем не тронутое расхождение (подключение и конфигурация как при открытии формы) диалог не поднимает', async () => {
      stubServer({ ...NEIGHBOR })
      const wrapper = mountLive([savedRow()], { connectionBaseline: new Map([['if-1', connected]]) })
      expect(await review(wrapper, snapshot(false))).toBe(true)
      expect(dialog(wrapper).exists()).toBe(false)
    })

    it('конфигурация сохранённого порта изменена в форме — расхождение с соседом показано, оба вида сразу в одной строке', async () => {
      stubServer({ ...NEIGHBOR, vlan_mode: 'trunk' })
      const wrapper = mountLive([savedRow()], { connectionBaseline: new Map([['if-1', connected]]) })
      const result = review(wrapper, snapshot(true)) // при открытии у порта было «Управление» — теперь снято
      await flushPromises()

      expect(dialog(wrapper).attributes('role')).toBe('alertdialog')
      expect(wrapper.findAll('.review-item')).toHaveLength(1)
      expect(dialog(wrapper).text()).toContain('Порт «eth0» ↔ «Gi0/1» (sw-b)')
      expect(dialog(wrapper).text()).toContain('«Управление»: нет / у соседа да')
      expect(dialog(wrapper).text()).toContain('режим порта: access / у соседа trunk')
      expect(dialog(wrapper).text()).toContain('изменятся сразу') // сосед на другом устройстве
      await dialogButton(wrapper, 'Сохранить как есть').trigger('click')
      expect(await result).toBe(true)
    })

    it('«Сохранить как есть» и «Вернуться к форме»/крестик/клик мимо окна: true или false, окно закрыто, ничего не записано', async () => {
      const calls = stubServer({ ...NEIGHBOR })
      const open = async () => {
        const wrapper = mountLive([row('eth0', { key: 'k0', connection: connected })], { deviceId: null })
        const result = review(wrapper)
        await flushPromises()
        expect(dialog(wrapper).exists()).toBe(true)
        return { wrapper, result }
      }

      const keep = await open()
      await dialogButton(keep.wrapper, 'Сохранить как есть').trigger('click')
      expect(await keep.result).toBe(true)
      expect(dialog(keep.wrapper).exists()).toBe(false)

      const back = await open()
      await dialogButton(back.wrapper, 'Вернуться к форме').trigger('click')
      expect(await back.result).toBe(false)

      const cross = await open()
      await cross.wrapper.find('.review-modal .icon-btn').trigger('click')
      expect(await cross.result).toBe(false)

      const outside = await open()
      await outside.wrapper.find('.modal-overlay').trigger('mousedown')
      await outside.wrapper.find('.modal-overlay').trigger('click')
      expect(await outside.result).toBe(false)
      expect(calls.filter((c) => c.method !== 'GET')).toEqual([])
    })

    it('«Применить текущую конфигурацию» соседу на другом устройстве: PUT, расхождение пропадает из списка, остаётся «Сохранить»', async () => {
      const calls = stubServer({ ...NEIGHBOR })
      const wrapper = mountLive([row('eth0', { key: 'k0', is_management: false, is_data_transfer: true, connection: connected })], { deviceId: null })
      const result = review(wrapper)
      await flushPromises()

      await dialogButton(wrapper, 'Применить текущую конфигурацию').trigger('click')
      await flushPromises()

      expect(calls.find((c) => c.method === 'PUT' && c.url.endsWith('/resources/interfaces/b-1'))?.body).toEqual({
        is_management: false,
        is_data_transfer: true,
      })
      expect(wrapper.findAll('.review-item')).toHaveLength(0)
      expect(dialog(wrapper).text()).toContain('Расхождений не осталось')
      await dialogButton(wrapper, 'Сохранить').trigger('click')
      expect(await result).toBe(true)
    })

    it('«Применить конфигурацию соседа» меняет строку формы, расхождение пропадает, соседа на сервере не трогает', async () => {
      const calls = stubServer({ ...NEIGHBOR })
      const wrapper = mountLive([row('eth0', { key: 'k0', is_management: false, is_data_transfer: true, connection: connected })], { deviceId: null })
      const result = review(wrapper)
      await flushPromises()

      await dialogButton(wrapper, 'Применить конфигурацию соседа').trigger('click')
      await flushPromises()

      expect(lastRows(wrapper)[0]).toMatchObject({ is_management: true, is_data_transfer: true })
      expect(wrapper.findAll('.review-item')).toHaveLength(0)
      expect(calls.filter((c) => c.method !== 'GET')).toEqual([])
      await dialogButton(wrapper, 'Сохранить').trigger('click')
      expect(await result).toBe(true)
    })

    it('два порта этого устройства, подключённых друг к другу, — одно расхождение, а не два; сосед правится в форме', async () => {
      stubServer({ ...NEIGHBOR })
      const rows = [
        row('eth0', { key: 'kA', is_management: true, vlan_mode: 'access', connection: toRow('kB') }),
        row('eth1', { key: 'kB', is_management: false, vlan_mode: 'trunk', connection: toRow('kA') }),
      ]
      const wrapper = mountLive(rows, { deviceId: null })
      const result = review(wrapper)
      await flushPromises()
      expect(wrapper.findAll('.review-item')).toHaveLength(1)

      await dialogButton(wrapper, 'Применить текущую конфигурацию').trigger('click')
      await flushPromises()
      expect(lastRows(wrapper)[1]).toMatchObject({ name: 'eth1', is_management: true, vlan_mode: 'access' })
      expect(wrapper.findAll('.review-item')).toHaveLength(0)
      await dialogButton(wrapper, 'Сохранить').trigger('click')
      expect(await result).toBe(true)
    })

    it('не удалось прочитать порты соседа — сохранение не блокируется (true), ошибка в уведомлении, диалога нет', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => jsonResponse({ detail: 'Сервер недоступен' }, 500)),
      )
      const wrapper = mountLive([row('eth0', { key: 'k0', connection: connected })], { deviceId: null })
      expect(await review(wrapper)).toBe(true)
      expect(dialog(wrapper).exists()).toBe(false)
      expect(toastText()).toContain('Сервер недоступен')
    })
  })
})

describe('DeviceInterfacesEditor.vue: подинтерфейсы порта', () => {
  const vlansForSubs: VLANDefinition[] = [{ id: 'v-10', vlan_id: 10, name: 'Серверы', description: '', domain_id: null, domain_name: '', devices: [] }]

  function mountWithPort(patch: Partial<InterfaceDraftRow> = {}) {
    const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'Gi0/0', ...patch }]
    return mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vlansForSubs } })
  }

  it('в раскрытых деталях порта есть блок «Подинтерфейсы»; в свёрнутой строке его нет', async () => {
    const wrapper = mountWithPort()
    expect(wrapper.text()).not.toContain('Подинтерфейсы')

    await expandRow(wrapper)

    expect(wrapper.find('.sub-block').exists()).toBe(true)
    expect(wrapper.find('.sub-block').text()).toContain('Подинтерфейсы не добавлены')
  })

  it('«+ Подинтерфейс» кладёт в строку порта список с одним подинтерфейсом, остальные поля порта не меняются', async () => {
    const wrapper = mountWithPort({ description: 'uplink', vlan_ids: ['v-10'] })
    await expandRow(wrapper)

    await wrapper.find('.sub-head button').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    const [row] = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
    expect(row).toMatchObject({ name: 'Gi0/0', description: 'uplink' })
    expect(row.subinterfaces).toHaveLength(1)
    expect(row.subinterfaces![0]).toMatchObject({ name: '', vlan_id: '', ips: [], open_ports: [] })
  })

  it('имя порта передаётся редактору подинтерфейсов: выбор VLAN подставляет «<порт>.<VLAN>»', async () => {
    const wrapper = mountWithPort({
      vlan_ids: ['v-10'],
      subinterfaces: [{ key: 'k1', name: '', vlan_id: '', is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [] }],
    })
    await expandRow(wrapper)

    // SearchableSelect редактора подинтерфейсов: в карточке порта есть ещё и select VLAN access-порта.
    wrapper.findComponent(InterfaceSubinterfacesEditor).findComponent(SearchableSelect).vm.$emit('update:modelValue', 'v-10')
    await flushPromises()

    const emitted = wrapper.emitted('update:modelValue')!
    const [row] = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
    expect(row.subinterfaces![0]).toMatchObject({ vlan_id: 'v-10', name: 'Gi0/0.10' })
  })

  it('в свёрнутой строке показывается число подинтерфейсов', () => {
    const wrapper = mountWithPort({
      subinterfaces: [
        { key: 'k1', name: 'Gi0/0.10', vlan_id: 'v-10', is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [] },
        { key: 'k2', name: 'Gi0/0.20', vlan_id: 'v-20', is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [] },
      ],
    })
    expect(wrapper.find('.expand-toggle').text()).toContain('2 подинт.')
  })

  it('у порта без подинтерфейсов счётчика в свёрнутой строке нет', () => {
    expect(mountWithPort({ subinterfaces: [] }).find('.expand-toggle').text()).not.toContain('подинт.')
  })

  const subRow = (patch: Record<string, unknown>) => ({
    key: 'k',
    name: '',
    vlan_id: 'v-10',
    is_management: false,
    is_data_transfer: false,
    description: '',
    ips: [],
    open_ports: [],
    ...patch,
  })

  describe('подинтерфейс на VLAN, которого нет на порту или у устройства', () => {
    it('свёрнутая строка порта показывает значок со списком таких подинтерфейсов', () => {
      const wrapper = mountWithPort({
        vlan_ids: ['v-10'],
        subinterfaces: [subRow({ key: 'a', name: 'Gi0/0.10' }), subRow({ key: 'b', name: 'Gi0/0.30', vlan_id: 'v-gone' })],
      })

      const icon = wrapper.find('.expand-toggle .stale-sub-icon')
      expect(icon.exists()).toBe(true)
      expect(icon.attributes('title')).toContain('«Gi0/0.30»')
      expect(icon.attributes('title')).not.toContain('«Gi0/0.10»')
    })

    it('значок появляется и для VLAN устройства, который не выбран на самом порту', () => {
      const wrapper = mountWithPort({ vlan_ids: [], subinterfaces: [subRow({ name: 'Gi0/0.10' })] }) // v-10 есть у устройства, но с порта убран

      expect(wrapper.find('.expand-toggle .stale-sub-icon').attributes('title')).toContain('«Gi0/0.10»')
    })

    it('значка нет, если все VLAN подинтерфейсов выбраны на порту, и у порта без подинтерфейсов', () => {
      expect(
        mountWithPort({ vlan_ids: ['v-10'], subinterfaces: [subRow({ name: 'Gi0/0.10' })] })
          .find('.stale-sub-icon')
          .exists(),
      ).toBe(false)
      expect(mountWithPort().find('.stale-sub-icon').exists()).toBe(false)
    })

    it('«Все VLAN» на порту: подинтерфейс на любом VLAN устройства считается выбранным', () => {
      const wrapper = mountWithPort({ vlan_mode: 'trunk', all_vlans: true, subinterfaces: [subRow({ name: 'Gi0/0.10' })] })

      expect(wrapper.find('.stale-sub-icon').exists()).toBe(false)
    })
  })

  describe('VLAN подинтерфейса выбирается из VLAN порта', () => {
    const twoVlans: VLANDefinition[] = [
      { id: 'v-10', vlan_id: 10, name: 'Серверы', description: '', domain_id: null, domain_name: '', devices: [] },
      { id: 'v-20', vlan_id: 20, name: 'Гости', description: '', domain_id: null, domain_name: '', devices: [] },
    ]
    function mountPorts(rows: InterfaceDraftRow[], groups: InterfaceGroupDraft[] = []) {
      return mount(DeviceInterfacesEditor, { props: { modelValue: rows, groups, typeOptions, speedOptions, vlanOptions: twoVlans } })
    }
    const options = (wrapper: ReturnType<typeof mountPorts>) =>
      (wrapper.findComponent(InterfaceSubinterfacesEditor).findComponent(SearchableSelect).props('options') as { value: string }[]).map((o) => o.value)

    it('в списке только VLAN, выбранные на этом порту (не все VLAN устройства)', async () => {
      const wrapper = mountPorts([{ ...emptyRow(), name: 'Gi0/0', vlan_ids: ['v-20'], subinterfaces: [subRow({ vlan_id: '' })] }])
      await expandRow(wrapper)

      expect(options(wrapper)).toEqual(['v-20'])
    })

    it('у порта с «Все VLAN» (trunk) в списке все VLAN устройства', async () => {
      const wrapper = mountPorts([
        { ...emptyRow(), name: 'Gi0/0', vlan_mode: 'trunk', all_vlans: true, vlan_ids: ['v-10', 'v-20'], subinterfaces: [subRow({ vlan_id: '' })] },
      ])
      await expandRow(wrapper)

      expect(options(wrapper)).toEqual(['v-10', 'v-20'])
    })

    it('если на порту нет VLAN — добавить подинтерфейс нельзя', async () => {
      const wrapper = mountPorts([{ ...emptyRow(), name: 'Gi0/0', vlan_ids: [] }])
      await expandRow(wrapper)

      expect(wrapper.find('.sub-head button').attributes('disabled')).toBeDefined()
      expect(wrapper.find('.sub-block').text()).toContain('выберите VLAN порта')
    })

    it('порт в группе, которая задаёт подинтерфейсы, показывает их только для просмотра с пояснением', async () => {
      const group: InterfaceGroupDraft = { ...emptyGroup('Серверные'), key: 'g1', vlan_mode: 'trunk', vlan_ids: ['v-10'], manage_subinterfaces: true }
      const wrapper = mountPorts(
        [{ ...emptyRow(), name: 'Gi0/0', group_key: 'g1', vlan_ids: ['v-10'], subinterfaces: [subRow({ name: 'Gi0/0.10' })] }],
        [group],
      )
      await expandRow(wrapper)

      expect(wrapper.find('.sub-block').text()).toContain('Список подинтерфейсов задан группой «Серверные»')
      expect(wrapper.find('.sub-head button').exists()).toBe(false)
      expect(wrapper.find('.sub-block input[aria-label="Имя подинтерфейса"]').attributes('disabled')).toBeDefined()
    })

    it('порт в группе, которая подинтерфейсами не управляет, редактируется как обычно', async () => {
      const group: InterfaceGroupDraft = { ...emptyGroup('Серверные'), key: 'g1', vlan_mode: 'trunk', vlan_ids: ['v-10'] }
      const wrapper = mountPorts([{ ...emptyRow(), name: 'Gi0/0', group_key: 'g1', vlan_ids: ['v-10'] }], [group])
      await expandRow(wrapper)

      expect(wrapper.find('.sub-head button').exists()).toBe(true)
      expect(wrapper.find('.sub-block .group-lock').exists()).toBe(false)
    })
  })

  describe('массовый перенос подинтерфейсов с недоступных VLAN', () => {
    const vlansBulk: VLANDefinition[] = [
      { id: 'v-20', vlan_id: 20, name: 'Гости', description: '', domain_id: null, domain_name: '', devices: [] },
      { id: 'v-10', vlan_id: 10, name: 'Серверы', description: '', domain_id: null, domain_name: '', devices: [] },
    ]
    const reserve: VLANDefinition = { id: 'v-30', vlan_id: 30, name: 'Резерв', description: '', domain_id: null, domain_name: '', devices: [] }

    function mountBulk(rows: InterfaceDraftRow[]) {
      useToast().toasts.splice(0)
      return mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vlansBulk, vlanCatalog: [reserve] } })
    }
    const bulkSelect = (wrapper: ReturnType<typeof mountBulk>) => wrapper.find('select[aria-label="Перенести все такие подинтерфейсы на VLAN"]')
    const staleRows = (): InterfaceDraftRow[] => [
      { ...emptyRow(), name: 'Gi0/0', vlan_ids: ['v-10', 'v-20'], subinterfaces: [subRow({ key: 'a', name: 'Gi0/0.30', vlan_id: 'v-30' })] },
      {
        ...emptyRow(),
        name: 'Gi0/1',
        vlan_ids: ['v-10', 'v-20'],
        subinterfaces: [subRow({ key: 'b', name: 'Gi0/1.30', vlan_id: 'v-30' }), subRow({ key: 'c', name: 'Gi0/1.10', vlan_id: 'v-10' })],
      },
    ]

    it('панели нет, пока все подинтерфейсы на доступных VLAN', () => {
      expect(
        mountBulk([{ ...emptyRow(), name: 'Gi0/0', subinterfaces: [subRow({ name: 'Gi0/0.10' })] }])
          .find('.stale-bulk')
          .exists(),
      ).toBe(false)
    })

    it('панель показывает число таких подинтерфейсов; список VLAN упорядочен по номеру, «Перенести» выключена, пока VLAN не выбран', () => {
      const wrapper = mountBulk(staleRows())

      expect(wrapper.find('.stale-bulk').text()).toContain('Подинтерфейсов на VLAN, не назначенном устройству: 2')
      expect(
        bulkSelect(wrapper)
          .findAll('option')
          .map((o) => o.attributes('value')),
      ).toEqual(['', 'v-10', 'v-20'])
      expect(wrapper.find('.stale-bulk button').attributes('disabled')).toBeDefined()
    })

    it('«Перенести» меняет VLAN и автоимена там, где можно; занятое на порту остаётся, и об этом предупреждает уведомление', async () => {
      const wrapper = mountBulk(staleRows())

      await bulkSelect(wrapper).setValue('v-10')
      await wrapper.find('.stale-bulk button').trigger('click')

      const emitted = wrapper.emitted('update:modelValue')!
      const rows = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
      expect(rows[0].subinterfaces![0]).toMatchObject({ key: 'a', vlan_id: 'v-10', name: 'Gi0/0.10' })
      expect(rows[1].subinterfaces!.map((s) => [s.name, s.vlan_id])).toEqual([
        ['Gi0/1.30', 'v-30'],
        ['Gi0/1.10', 'v-10'],
      ]) // v-10 на Gi0/1 уже занят
      const [toast] = useToast().toasts
      expect(toast.type).toBe('warning')
      expect(toast.message).toContain('Перенесено подинтерфейсов: 1 — на VLAN 10 — Серверы.')
      expect(toast.message).toContain('«Gi0/1.30»')
      expect((bulkSelect(wrapper).element as HTMLSelectElement).value).toBe('') // выбор сброшен
    })

    it('на порт, где целевой VLAN не выбран, подинтерфейс массовым переносом не попадает', async () => {
      const rows = staleRows()
      rows[0] = { ...rows[0], vlan_ids: ['v-20'] } // на Gi0/0 нет VLAN 10
      const wrapper = mountBulk(rows)

      await bulkSelect(wrapper).setValue('v-10')
      await wrapper.find('.stale-bulk button').trigger('click')

      const emitted = wrapper.emitted('update:modelValue')
      expect(emitted === undefined || (emitted[emitted.length - 1][0] as InterfaceDraftRow[])[0].subinterfaces![0].vlan_id === 'v-30').toBe(true)
      expect(useToast().toasts[0].message).toContain('«Gi0/0.30»')
    })

    it('если переносится всё — уведомление об успехе', async () => {
      const wrapper = mountBulk([staleRows()[0]])

      await bulkSelect(wrapper).setValue('v-20')
      await wrapper.find('.stale-bulk button').trigger('click')

      const emitted = wrapper.emitted('update:modelValue')!
      expect((emitted[emitted.length - 1][0] as InterfaceDraftRow[])[0].subinterfaces![0]).toMatchObject({ vlan_id: 'v-20', name: 'Gi0/0.20' })
      expect(useToast().toasts.map((t) => [t.type, t.message])).toEqual([['success', 'Перенесено подинтерфейсов: 1 — на VLAN 20 — Гости.']])
    })

    it('если ничего перенести нельзя — строки не меняются (нет update:modelValue), только предупреждение', async () => {
      const rows: InterfaceDraftRow[] = [
        {
          ...emptyRow(),
          name: 'Gi0/0',
          subinterfaces: [subRow({ key: 'a', name: 'Gi0/0.10', vlan_id: 'v-10' }), subRow({ key: 'b', name: 'Gi0/0.30', vlan_id: 'v-30' })],
        },
      ]
      const wrapper = mountBulk(rows)

      await bulkSelect(wrapper).setValue('v-10')
      await wrapper.find('.stale-bulk button').trigger('click')

      expect(wrapper.emitted('update:modelValue')).toBeUndefined()
      expect(useToast().toasts.map((t) => t.type)).toEqual(['warning'])
    })
  })

  describe('«Показать»: раскрытие портов с подинтерфейсами на недоступном VLAN', () => {
    function mountTwoPorts() {
      const rows: InterfaceDraftRow[] = [
        { ...emptyRow(), name: 'Gi0/0', subinterfaces: [subRow({ key: 'a', name: 'Gi0/0.10' })] },
        { ...emptyRow(), name: 'Gi0/1', subinterfaces: [subRow({ key: 'b', name: 'Gi0/1.30', vlan_id: 'v-gone' })] },
        { ...emptyRow(), name: 'Gi0/2' },
      ]
      return mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vlansForSubs } })
    }

    it('раскрывает только порты с такими подинтерфейсами, уже раскрытые не сворачивает, возвращает их число', async () => {
      const wrapper = mountTwoPorts()
      await expandRow(wrapper, 2) // пользователь уже раскрыл третий порт сам
      expect(wrapper.findAll('.iface-detail-row')).toHaveLength(1)

      const found = await (wrapper.vm as unknown as { revealStaleSubinterfaces: () => Promise<number> }).revealStaleSubinterfaces()

      expect(found).toBe(1)
      expect(wrapper.findAll('.iface-detail-row')).toHaveLength(2) // Gi0/1 и ранее раскрытый Gi0/2; Gi0/0 (VLAN доступен) не тронут
      expect(wrapper.find('.sub-warn').text()).toContain('больше не назначен устройству')
    })

    it('без проблемных подинтерфейсов ничего не раскрывает и возвращает 0', async () => {
      const wrapper = mountWithPort({ subinterfaces: [subRow({ name: 'Gi0/0.10' })] })

      const found = await (wrapper.vm as unknown as { revealStaleSubinterfaces: () => Promise<number> }).revealStaleSubinterfaces()

      expect(found).toBe(0)
      expect(wrapper.find('.iface-detail-row').exists()).toBe(false)
    })
  })

  describe('переименование порта', () => {
    function lastRow(wrapper: ReturnType<typeof mountWithPort>): InterfaceDraftRow {
      const emitted = wrapper.emitted('update:modelValue')!
      return (emitted[emitted.length - 1][0] as InterfaceDraftRow[])[0]
    }

    it('автоимена подинтерфейсов пересчитываются под новое имя порта, вручную заданные остаются', async () => {
      const wrapper = mountWithPort({
        subinterfaces: [subRow({ key: 'a', name: 'Gi0/0.10', description: 'Серверы' }), subRow({ key: 'b', name: 'wan-uplink', vlan_id: 'v-gone' })],
      })

      await wrapper.find('.iface-table tbody tr.iface-row input.cell-input').setValue('Gi0/1')

      const row = lastRow(wrapper)
      expect(row.name).toBe('Gi0/1')
      expect(row.subinterfaces!.map((s) => s.name)).toEqual(['Gi0/1.10', 'wan-uplink'])
      expect(row.subinterfaces![0]).toMatchObject({ key: 'a', vlan_id: 'v-10', description: 'Серверы' })
    })

    it('у порта без подинтерфейсов ключ subinterfaces не появляется («не трогали» остаётся «не трогали»)', async () => {
      const wrapper = mountWithPort()
      await wrapper.find('.iface-table tbody tr.iface-row input.cell-input').setValue('Gi0/1')

      expect(lastRow(wrapper)).not.toHaveProperty('subinterfaces')
    })

    it('автоимя подинтерфейса на недоступном VLAN тоже следует за портом, если VLAN есть в справочнике', async () => {
      const reserve: VLANDefinition = { id: 'v-30', vlan_id: 30, name: 'Резерв', description: '', domain_id: null, domain_name: '', devices: [] }
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'Gi0/0', subinterfaces: [subRow({ name: 'Gi0/0.30', vlan_id: 'v-30' })] }]
      const wrapper = mount(DeviceInterfacesEditor, {
        props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vlansForSubs, vlanCatalog: [reserve] },
      })

      await wrapper.find('.iface-table tbody tr.iface-row input.cell-input').setValue('Gi0/1')

      expect(lastRow(wrapper as never).subinterfaces![0].name).toBe('Gi0/1.30')
    })

    it('если у подинтерфейсов автоимён нет, список остаётся тем же (только имя порта меняется)', async () => {
      const subs = [subRow({ name: 'wan-uplink' })]
      const wrapper = mountWithPort({ subinterfaces: subs })
      await wrapper.find('.iface-table tbody tr.iface-row input.cell-input').setValue('Gi0/1')

      expect(lastRow(wrapper).subinterfaces).toStrictEqual(subs)
    })
  })
})

describe('DeviceInterfacesEditor.vue — «Все VLAN»: сверка с соседом и выбор значения при «Применить…»', () => {
  const v10: VLANDefinition = { id: 'a10', vlan_id: 10, name: 'Серверы', description: '', domain_id: null, domain_name: '', devices: [] }
  const v20: VLANDefinition = { id: 'a20', vlan_id: 20, name: 'Камеры', description: '', domain_id: null, domain_name: '', devices: [] }
  const ownVlans = [v10, v20]
  const connected = {
    peer_device_id: 'dev-b',
    peer_device_name: 'sw-b',
    peer_interface_id: 'b-1',
    peer_interface_name: 'Gi0/1',
    connection_type_id: 'ct-1',
    description: '',
  }
  const trunkRow = (extra: Partial<InterfaceDraftRow> = {}): InterfaceDraftRow => ({
    ...emptyRow(),
    id: 'if-1',
    name: 'eth0',
    vlan_mode: 'trunk',
    all_vlans: false,
    vlan_ids: ['a10'],
    connection: connected,
    ...extra,
  })
  const toastText = () =>
    useToast()
      .toasts.map((t) => t.message)
      .join(' | ')
  const lastRows = (wrapper: ReturnType<typeof mount>) => wrapper.emitted('update:modelValue')!.at(-1)![0] as InterfaceDraftRow[]

  interface Call {
    url: string
    method: string
    body?: Record<string, unknown>
  }

  // Фейковый сервер: порт соседа b-1 устройства dev-b (trunk; «Все VLAN» и набор настраиваются) с его VLAN.
  function stubServer(neighbor: { all_vlans: boolean; vlan_ids?: string[] }, cascadePreview?: () => Response) {
    const calls: Call[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        const body = init?.body ? (JSON.parse(init.body as string) as Record<string, unknown>) : undefined
        calls.push({ url, method, body })
        if (url.includes('/vlan-mode-cascade/preview') && cascadePreview) return cascadePreview()
        if (method === 'PUT' && url.endsWith('/interfaces/b-1/port-config')) {
          neighbor.all_vlans = body!.all_vlans === true
          if (Array.isArray(body!.vlan_ids)) neighbor.vlan_ids = body!.vlan_ids as string[]
          return jsonResponse({ id: 'b-1', name: 'Gi0/1', vlan_mode: 'trunk', all_vlans: neighbor.all_vlans })
        }
        if (/\/devices\/dev-b\/free-interfaces/.test(url)) {
          return jsonResponse({
            items: [
              { id: 'b-1', name: 'Gi0/1', is_management: false, is_data_transfer: false, vlan_mode: 'trunk', all_vlans: neighbor.all_vlans, occupied: false },
            ],
            total: 1,
            offset: 0,
            limit: 200,
          })
        }
        if (url.endsWith('/resources/interfaces/b-1'))
          return jsonResponse({ id: 'b-1', physical_device_id: 'dev-b', name: 'Gi0/1', vlan_mode: 'trunk', all_vlans: neighbor.all_vlans })
        if (url.endsWith('/resources/devices/dev-b')) return jsonResponse({ id: 'dev-b', device_type_id: 'dt-b' })
        if (url.endsWith('/devices/dev-b/interface-vlans'))
          return jsonResponse({ items: [{ interface_id: 'b-1', all_vlans: neighbor.all_vlans, vlan_ids: neighbor.vlan_ids ?? [] }] })
        if (url.includes('/resources/device-type-vlans'))
          return jsonResponse({ items: [{ vlan_id: 'b10' }, { vlan_id: 'b20' }, { vlan_id: 'b30' }], total: 3, offset: 0, limit: 1000 })
        if (url.includes('/resources/device-vlans')) return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
        if (url.endsWith('/vlan-dashboard')) {
          const def = (id: string, number: number) => ({
            id,
            vlan_id: number,
            name: `VLAN ${number}`,
            description: '',
            domain_id: null,
            domain_name: '',
            devices: [],
          })
          return jsonResponse({ items: [10, 20, 30].map((n) => ({ vlan_id: n, definitions: [def(`b${n}`, n)] })) })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 200 })
      }),
    )
    return calls
  }

  // Родитель держит v-model, как DeviceFormModal.
  function mountLive(rows: InterfaceDraftRow[], extra: Record<string, unknown> = {}) {
    useCatalogsStore().items['interfaces'] = [] as never
    const wrapper = mount(DeviceInterfacesEditor, {
      props: {
        modelValue: rows,
        typeOptions,
        speedOptions,
        vlanOptions: ownVlans,
        deviceId: 'dev-1',
        editConnections: true,
        ...extra,
        'onUpdate:modelValue': (value: InterfaceDraftRow[]) => wrapper.setProps({ modelValue: value }),
      },
      attachTo: document.body,
    })
    return wrapper
  }
  const applyButtons = (wrapper: ReturnType<typeof mount>) => wrapper.findAll('.connection-diffs-actions button')
  const choiceModal = () => document.body.querySelector('[data-testid="all-vlans-choice"]')
  const choiceButton = (testId: string) => document.body.querySelector<HTMLElement>(`[data-testid="${testId}"]`)!

  beforeEach(() => useToast().toasts.splice(0))

  it('сосед на другом устройстве с «Все VLAN», у этого порта признака нет: панель показывает расхождение «Все VLAN»', async () => {
    stubServer({ all_vlans: true })
    const wrapper = mountLive([trunkRow()])
    await expandRow(wrapper)
    await flushPromises()

    expect(wrapper.find('.connection-diffs').text()).toContain('«Все VLAN»: нет / у соседа да')
    wrapper.unmount()
  })

  it('«Применить конфигурацию соседа»: по умолчанию предлагается «Все VLAN» соседа; «Применить» ставит признак порту формы (черновик), запросов на запись нет', async () => {
    const calls = stubServer({ all_vlans: true })
    const wrapper = mountLive([trunkRow()])
    await expandRow(wrapper)
    await flushPromises()

    await applyButtons(wrapper)[0].trigger('click')
    await flushPromises()
    expect(choiceModal()).not.toBeNull()
    expect(document.body.querySelector('[data-testid="choice-source-text"]')!.textContent).toBe('Все VLAN')
    choiceButton('choice-apply').click()
    await flushPromises()

    expect(choiceModal()).toBeNull()
    expect(lastRows(wrapper)[0]).toMatchObject({ all_vlans: true, vlan_ids: ['a10', 'a20'] }) // форма показывает все VLAN отмеченными
    expect(calls.filter((c) => c.method !== 'GET')).toEqual([])
    expect(toastText()).toContain('установлено: Все VLAN — сохраните форму')
    expect(wrapper.find('.connection-diffs').exists()).toBe(false)
    wrapper.unmount()
  })

  it('«Применить текущую конфигурацию»: у этого порта «Все VLAN», у соседа набор вручную — «другое значение» уходит соседу PUT-ом port-config', async () => {
    const calls = stubServer({ all_vlans: false, vlan_ids: ['b10'] })
    const wrapper = mountLive([trunkRow({ all_vlans: true, vlan_ids: ['a10', 'a20'] })])
    await expandRow(wrapper)
    await flushPromises()
    expect(wrapper.find('.connection-diffs').text()).toContain('«Все VLAN»: да / у соседа нет')

    await applyButtons(wrapper)[1].trigger('click')
    await flushPromises()
    // значение источника по умолчанию — «Все VLAN»; пользователь выбирает другое: только VLAN 20 устройства соседа
    choiceButton('choice-other').click()
    await flushPromises()
    choiceButton('choice-pick').click()
    await flushPromises()
    const checks = [...document.body.querySelectorAll<HTMLInputElement>('.vlan-picker-modal .vlan-check:not(.vlan-check-all) input')]
    expect(checks).toHaveLength(3) // VLAN устройства соседа: 10, 20, 30
    for (const check of checks.slice(0, 3)) if (check.checked) check.click() // снять отмеченные «Все VLAN»
    checks[1].click()
    await flushPromises()
    document.body.querySelector<HTMLElement>('.vlan-picker-modal .picker-foot button')!.click()
    await flushPromises()
    choiceButton('choice-apply').click()
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/interfaces/b-1/port-config'))
    expect(put?.body).toEqual({ all_vlans: false, vlan_ids: ['b20'], mode: 'trunk' })
    expect(wrapper.emitted('update:modelValue')).toBeUndefined() // порт этой строки не менялся
    expect(wrapper.emitted('neighbors-changed')).toHaveLength(1)
    expect(toastText()).toContain('установлено: VLAN 20')
    wrapper.unmount()
  })

  it('«Применить текущую конфигурацию»: «Все VLAN» этого порта переносится соседу признаком (набор соседа не нужен)', async () => {
    const calls = stubServer({ all_vlans: false, vlan_ids: ['b10'] })
    const wrapper = mountLive([trunkRow({ all_vlans: true, vlan_ids: ['a10', 'a20'] })])
    await expandRow(wrapper)
    await flushPromises()

    await applyButtons(wrapper)[1].trigger('click')
    await flushPromises()
    choiceButton('choice-apply').click()
    await flushPromises()

    expect(calls.find((c) => c.method === 'PUT' && c.url.endsWith('/interfaces/b-1/port-config'))?.body).toEqual({ all_vlans: true, mode: 'trunk' })
    expect(wrapper.find('.connection-diffs').exists()).toBe(false) // порты соседа перечитаны — расхождения нет
    wrapper.unmount()
  })

  it('набор вручную у источника переносится по номерам VLAN на VLAN устройства цели', async () => {
    const calls = stubServer({ all_vlans: true })
    // у этого порта набор VLAN 10 и 20 (без признака), у соседа «Все VLAN»: соседу — набор, перенесённый на его VLAN
    const wrapper = mountLive([trunkRow({ vlan_ids: ['a10', 'a20'] })])
    await expandRow(wrapper)
    await flushPromises()

    await applyButtons(wrapper)[1].trigger('click')
    await flushPromises()
    expect(document.body.querySelector('[data-testid="choice-source-text"]')!.textContent).toBe('VLAN 10, 20')
    choiceButton('choice-apply').click()
    await flushPromises()

    expect(calls.find((c) => c.method === 'PUT' && c.url.endsWith('/interfaces/b-1/port-config'))?.body).toEqual({
      all_vlans: false,
      vlan_ids: ['b10', 'b20'],
      mode: 'trunk',
    })
    wrapper.unmount()
  })

  it('«Отмена» в окне выбора значения: ничего не записывается, расхождение остаётся', async () => {
    const calls = stubServer({ all_vlans: false, vlan_ids: ['b10'] })
    const wrapper = mountLive([trunkRow({ all_vlans: true, vlan_ids: ['a10', 'a20'] })])
    await expandRow(wrapper)
    await flushPromises()

    await applyButtons(wrapper)[1].trigger('click')
    await flushPromises()
    document.body.querySelector<HTMLElement>('.choice-foot .btn-secondary')!.click() // «Отмена»
    await flushPromises()

    expect(choiceModal()).toBeNull()
    expect(calls.filter((c) => c.method !== 'GET')).toEqual([])
    expect(toastText()).toContain('не изменено')
    expect(wrapper.find('.connection-diffs').exists()).toBe(true)
    expect(applyButtons(wrapper).every((b) => b.attributes('disabled') === undefined)).toBe(true)
    wrapper.unmount()
  })

  it('сосед — другой порт этого устройства: значение правится в его строке черновика, запросов на запись нет', async () => {
    const calls = stubServer({ all_vlans: false })
    const toRow = { peer_device_id: '__self__', peer_interface_id: '', peer_row_key: 'kB', connection_type_id: 'ct-1', description: '' }
    const rows = [
      trunkRow({ id: undefined, key: 'kA', name: 'eth0', all_vlans: true, vlan_ids: ['a10', 'a20'], connection: toRow }),
      trunkRow({ id: undefined, key: 'kB', name: 'eth1', all_vlans: false, vlan_ids: ['a10'], connection: { ...toRow, peer_row_key: 'kA' } }),
    ]
    const wrapper = mountLive(rows, { deviceId: null })
    await expandRow(wrapper, 0)
    await flushPromises()

    await applyButtons(wrapper)[1].trigger('click') // «Применить текущую конфигурацию»: соседу eth1 — «Все VLAN» eth0
    await flushPromises()
    choiceButton('choice-apply').click()
    await flushPromises()

    expect(lastRows(wrapper)[1]).toMatchObject({ name: 'eth1', all_vlans: true, vlan_ids: ['a10', 'a20'] })
    expect(calls.filter((c) => c.method !== 'GET')).toEqual([])
    expect(toastText()).toContain('сохраните форму')
    wrapper.unmount()
  })

  it('смена режима на trunk вместе с «Все VLAN»: порт формы получает «Все VLAN» по умолчанию — окно предлагает набор соседа по номерам VLAN', async () => {
    const calls = stubServer({ all_vlans: false, vlan_ids: ['b10'] }, () =>
      jsonResponse(
        makePlan({
          target_mode: 'trunk',
          start_interface_id: 'if-1',
          edited_device_id: 'dev-1',
          ports: [portChange({ id: 'if-1', name: 'eth0', device_id: 'dev-1', device_name: 'esxi-01', deferred: true, from_mode: 'access', to_mode: 'trunk' })],
          devices: [{ id: 'dev-1', name: 'esxi-01', deferred: true, port_count: 1, group_count: 0 }],
          totals: { ports: 1, devices: 1, groups: 0, deferred_ports: 1, immediate_ports: 0, immediate_devices: 0, dropped_vlans: 0 },
        }),
      ),
    )
    const wrapper = mountLive([trunkRow({ vlan_mode: 'access', vlan_ids: ['a20'] })])
    await expandRow(wrapper)
    await flushPromises()
    expect(wrapper.find('.connection-diffs').text()).toContain('режим порта: access / у соседа trunk')

    await applyButtons(wrapper)[0].trigger('click') // «Применить конфигурацию соседа»: режим trunk
    await flushPromises()

    // после смены режима у порта формы «Все VLAN», у соседа — набор вручную: значение выбирает пользователь
    expect(choiceModal()).not.toBeNull()
    expect(document.body.querySelector('[data-testid="choice-source-text"]')!.textContent).toBe('VLAN 10') // VLAN 10 соседа → VLAN 10 этого устройства
    choiceButton('choice-apply').click()
    await flushPromises()

    expect(lastRows(wrapper)[0]).toMatchObject({ vlan_mode: 'trunk', all_vlans: false, vlan_ids: ['a10'] })
    expect(calls.some((c) => c.url.endsWith('/interfaces/if-1/vlan-mode-cascade/preview'))).toBe(true)
    expect(calls.filter((c) => c.method === 'PUT')).toEqual([])
    wrapper.unmount()
  })

  it('режим порта расходится: в панели только режим, «Все VLAN» отдельной строкой не показывается и значения не спрашиваются', async () => {
    stubServer({ all_vlans: true })
    const wrapper = mountLive([trunkRow({ vlan_mode: 'access', all_vlans: false, vlan_ids: ['a10'] })])
    await expandRow(wrapper)
    await flushPromises()

    expect(wrapper.find('.connection-diffs').text()).toContain('режим порта: access / у соседа trunk')
    expect(wrapper.find('.connection-diffs').text()).not.toContain('«Все VLAN»')
    expect(choiceModal()).toBeNull()
    wrapper.unmount()
  })

  it('значок расхождения «Все VLAN» у строки открывает окно решения: «Применить конфигурацию соседа» предлагает значение соседа', async () => {
    stubServer({ all_vlans: true })
    const conflict = {
      otherInterfaceId: 'b-1',
      otherDeviceName: 'sw-b',
      otherInterfaceName: 'Gi0/1',
      flagsDiffer: false,
      vlanModeDiffer: false,
      allVlansDiffer: true,
      other: { is_management: false, is_data_transfer: false, vlan_mode: 'trunk' as const, all_vlans: true },
    }
    const wrapper = mountLive([trunkRow({ connection: null })], { conflicts: { 'if-1': conflict } })
    await expandRow(wrapper)

    await wrapper.get('[data-testid="all-vlans-conflict"]').trigger('click')
    expect(wrapper.find('.conflict-modal h3').text()).toBe('Расхождение «Все VLAN»')
    expect(wrapper.find('.conflict-compare').text()).toContain('Все VLAN')
    await wrapper.find('.conflict-modal-actions .btn-secondary').trigger('click')
    await flushPromises()
    expect(choiceModal()).not.toBeNull()
    choiceButton('choice-apply').click()
    await flushPromises()

    expect(lastRows(wrapper)[0]).toMatchObject({ all_vlans: true })
    expect(wrapper.find('.conflict-modal').exists()).toBe(false)
    wrapper.unmount()
  })

  it('проверка перед сохранением: расхождение «Все VLAN» попадает в диалог и устраняется тем же выбором значения', async () => {
    stubServer({ all_vlans: true })
    const wrapper = mountLive([trunkRow()], { connectionBaseline: new Map([['if-1', connected]]) })
    type ReviewVm = {
      reviewNeighborMismatches: (
        initial?: ReadonlyMap<string, { is_management: boolean; is_data_transfer: boolean; vlan_mode: 'access' | 'trunk'; all_vlans?: boolean }>,
      ) => Promise<boolean>
    }
    // порт менялся в этой форме: раньше «Все VLAN» у него было выключено так же, но режим был access
    const result = (wrapper.vm as unknown as ReviewVm).reviewNeighborMismatches(
      new Map([['if-1', { is_management: false, is_data_transfer: false, vlan_mode: 'access' }]]),
    )
    await flushPromises()

    expect(wrapper.find('.review-modal').text()).toContain('«Все VLAN»: нет / у соседа да')
    const apply = wrapper.findAll('.review-modal button').find((b) => b.text() === 'Применить конфигурацию соседа')!
    await apply.trigger('click')
    await flushPromises()
    choiceButton('choice-apply').click()
    await flushPromises()

    expect(lastRows(wrapper)[0]).toMatchObject({ all_vlans: true })
    expect(wrapper.find('.review-modal').text()).toContain('Расхождений не осталось')
    await wrapper
      .findAll('.review-modal button')
      .find((b) => b.text() === 'Сохранить')!
      .trigger('click')
    expect(await result).toBe(true)
    wrapper.unmount()
  })
})

describe('DeviceInterfacesEditor.vue: порядок интерфейсов (стрелки вверх/вниз)', () => {
  const named = (...names: string[]): InterfaceDraftRow[] => names.map((name) => ({ ...emptyRow(), name }))
  const portNames = (wrapper: ReturnType<typeof mount>) =>
    wrapper.findAll('.iface-table tbody tr.iface-row').map((tr) => (tr.find('input.cell-input').element as HTMLInputElement).value)
  const lastEmitted = (wrapper: ReturnType<typeof mount>) => (wrapper.emitted('update:modelValue')!.at(-1)![0] as InterfaceDraftRow[]).map((r) => r.name)

  it('у каждой строки есть столбец со стрелками; у первой «выше» и у последней «ниже» недоступны', () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: named('Gi0/1', 'Gi0/2', 'Gi0/3'), typeOptions, speedOptions, vlanOptions } })

    const buttons = wrapper
      .findAll('.iface-table tbody tr.iface-row')
      .map((tr) => tr.findAll('.order-btn').map((b) => (b.element as HTMLButtonElement).disabled))
    expect(buttons).toEqual([
      [true, false],
      [false, false],
      [false, true],
    ])
  })

  it('«ниже» меняет порт местами со следующим и отдаёт новый порядок', async () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: named('Gi0/1', 'Gi0/2', 'Gi0/3'), typeOptions, speedOptions, vlanOptions } })

    await wrapper.findAll('.iface-table tbody tr.iface-row')[0].findAll('.order-btn')[1].trigger('click')

    expect(lastEmitted(wrapper)).toEqual(['Gi0/2', 'Gi0/1', 'Gi0/3'])
  })

  it('«выше» меняет порт местами с предыдущим', async () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: named('Gi0/1', 'Gi0/2', 'Gi0/3'), typeOptions, speedOptions, vlanOptions } })

    await wrapper.findAll('.iface-table tbody tr.iface-row')[2].findAll('.order-btn')[0].trigger('click')

    expect(lastEmitted(wrapper)).toEqual(['Gi0/1', 'Gi0/3', 'Gi0/2'])
  })

  it('на границе списка клик по недоступной стрелке ничего не меняет', async () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: named('Gi0/1', 'Gi0/2'), typeOptions, speedOptions, vlanOptions } })

    await wrapper.findAll('.iface-table tbody tr.iface-row')[0].findAll('.order-btn')[0].trigger('click')

    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(portNames(wrapper)).toEqual(['Gi0/1', 'Gi0/2'])
  })

  it('развёрнутая строка едет вместе со своим портом, а не остаётся на месте', async () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: named('Gi0/1', 'Gi0/2'), typeOptions, speedOptions, vlanOptions } })
    await expandRow(wrapper, 0)

    await wrapper.findAll('.iface-table tbody tr.iface-row')[0].findAll('.order-btn')[1].trigger('click')
    await wrapper.setProps({ modelValue: named('Gi0/2', 'Gi0/1') })

    const rows = wrapper.findAll('.iface-table tbody tr')
    const detailAt = rows.findIndex((tr) => tr.find('td[colspan="11"]').exists())
    expect(detailAt).toBeGreaterThan(0)
    expect((rows[detailAt - 1].find('input.cell-input').element as HTMLInputElement).value).toBe('Gi0/1')
  })
})
