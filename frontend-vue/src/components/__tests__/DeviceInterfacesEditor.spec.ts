import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceInterfacesEditor from '../DeviceInterfacesEditor.vue'
import type { CatalogItem, InterfaceDraftRow, VLANDefinition } from '../../api/types'

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
    vlan_mode: 'access',
    ips: [],
  }
}

// Раскрывает панель деталей (VLAN на порту / IP-адреса / описание) для строки с индексом i —
// с п.3.4 они убраны из компактной таблицы под toggle.
async function expandRow(wrapper: ReturnType<typeof mount>, i = 0) {
  await wrapper.findAll('.expand-toggle')[i].trigger('click')
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  // generate() теперь спрашивает подтверждение, если в таблице уже есть данные (п.3.3) —
  // jsdom не реализует window.confirm, поэтому по умолчанию мокаем "пользователь согласился";
  // тесты на отмену явно переопределяют это на vi.fn(() => false).
  vi.stubGlobal('confirm', vi.fn(() => true))
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
    const existing: InterfaceDraftRow[] = [{ id: 'if-1', name: 'old-name', interface_type_id: '', mac_address: '', speed_id: '', is_management: true, is_data_transfer: false, description: '', vlan_ids: ['vlan-1'], vlan_mode: 'trunk', ips: [{ id: 'ip-1', ip_address: '10.0.0.1', prefix_length: '24', purpose: '' }] }]
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
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1' }, { ...emptyRow(), name: 'eth2' }]
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

    it('с галочкой на пустом списке — предупреждения нет (нечего терять)', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })
      await wrapper.find('.replace-all-check input').setValue(true)
      await wrapper.find('.generator input[type="number"]').setValue('1')
      await wrapper.find('.generator button.btn-secondary').trigger('click')

      expect(confirm).not.toHaveBeenCalled()
      expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    })

    it('отмена подтверждения — данные не перезаписываются, событие не эмитится, галочка остаётся включённой', async () => {
      vi.stubGlobal('confirm', vi.fn(() => false))
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
      expect(headers).toEqual(['', '#', 'Имя', 'Тип', 'MAC', 'Скорость', 'Упр.', 'Данные', 'VLAN / IP', ''])
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

    it('рендерит чекбокс на каждый допустимый VLAN с подписью "номер — имя [домен]"', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)
      // .iface-detail — иначе findAll('.vlan-check') подхватил бы ещё и чекбоксы из панели
      // "Массовое редактирование" (тот же vlanOptions используется и там).
      const labels = wrapper.findAll('.iface-detail .vlan-check:not(.vlan-check-all)').map((l) => l.text())
      expect(labels).toEqual(['10 — Управление', '20 — Гостевой [Филиал-1]'])
    })

    it('уже назначенный VLAN отображается отмеченным чекбоксом', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk', vlan_ids: ['v-guest'] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)
      const checkboxes = wrapper.findAll('.iface-detail .vlan-check:not(.vlan-check-all) input[type="checkbox"]')
      expect((checkboxes[0].element as HTMLInputElement).checked).toBe(false) // v-mgmt
      expect((checkboxes[1].element as HTMLInputElement).checked).toBe(true) // v-guest
    })

    it('установка чекбокса добавляет id VLAN в vlan_ids, снятие — убирает', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk', vlan_ids: ['v-mgmt'] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)

      const checkboxes = wrapper.findAll('.iface-detail .vlan-check:not(.vlan-check-all) input[type="checkbox"]')
      await checkboxes[1].setValue(true) // отмечаем v-guest в дополнение к уже стоящему v-mgmt
      let emitted = wrapper.emitted('update:modelValue')!
      expect((emitted[0][0] as InterfaceDraftRow[])[0].vlan_ids).toEqual(['v-mgmt', 'v-guest'])

      await wrapper.setProps({ modelValue: emitted[0][0] as InterfaceDraftRow[] })
      await wrapper.findAll('.iface-detail .vlan-check:not(.vlan-check-all) input[type="checkbox"]')[0].setValue(false) // снимаем v-mgmt
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
      expect(wrapper.find('.iface-detail .vlan-checks').exists()).toBe(true)
    })

    it('переключение на Access показывает одиночный select вместо чекбоксов', async () => {
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
      expect(wrapper.find('.iface-detail .vlan-checks').exists()).toBe(false) // не .vlan-checks вообще — тот же класс и в панели массового редактирования
      expect((wrapper.find('.iface-detail select').element as HTMLSelectElement).value).toBe('v-mgmt')
    })

    it('переключение с trunk (несколько VLAN) на access оставляет только первый VLAN', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'trunk', vlan_ids: ['v-mgmt', 'v-guest'] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)

      await wrapper.findAll('.vlan-mode-row input[type="radio"]')[1].setValue(true) // Access
      const result = (wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[])[0]
      expect(result.vlan_ids).toEqual(['v-mgmt'])
    })

    it('в режиме access выбор VLAN из select задаёт единственный элемент vlan_ids', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_mode: 'access', vlan_ids: [] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      await expandRow(wrapper)

      await wrapper.find('.iface-detail select').setValue('v-guest')
      const result = (wrapper.emitted('update:modelValue')![0][0] as InterfaceDraftRow[])[0]
      expect(result.vlan_ids).toEqual(['v-guest'])
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
      expect(wrapper.find('.bulk-edit-bar').exists()).toBe(false)
    })

    it('п.1.3.5: "Массовое редактирование" и таблица "Список интерфейсов" — один визуальный блок (общий iface-panel), а не два отдельных', () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: threeRows(), typeOptions, speedOptions, vlanOptions: vOptions } })
      const panel = wrapper.find('.iface-panel')
      expect(panel.exists()).toBe(true)
      expect(panel.find('.bulk-edit-bar').exists()).toBe(true)
      expect(panel.find('.iface-list-head').exists()).toBe(true)
      expect(panel.find('.iface-table-wrap').exists()).toBe(true)
    })

    it('без отмеченных строк по клику "Применить" показывает ошибку и ничего не эмитит', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: threeRows(), typeOptions, speedOptions, vlanOptions: vOptions } })
      await wrapper.find('.bulk-edit-bar button').trigger('click')
      expect(wrapper.emitted('update:modelValue')).toBeFalsy()
    })

    it('"Выбрать все" отмечает чекбоксы "Выбрать" на всех строках таблицы', async () => {
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: threeRows(), typeOptions, speedOptions, vlanOptions: vOptions } })
      await wrapper.find('.bulk-edit-bar .if-select-label input').setValue(true)
      const rowChecks = wrapper.findAll('.iface-table tbody .col-select input')
      expect(rowChecks.every((c) => (c.element as HTMLInputElement).checked)).toBe(true)
    })

    it('применяет тип/скорость только к отмеченным строкам, остальные поля строк не трогает', async () => {
      const rows = threeRows()
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })

      const rowChecks = wrapper.findAll('.iface-table tbody .col-select input')
      await rowChecks[0].setValue(true) // отмечаем только eth0
      await wrapper.find('.bulk-field select').setValue('t-eth') // "Тип интерфейса"
      await wrapper.find('.bulk-edit-bar button').trigger('click')

      const emitted = wrapper.emitted('update:modelValue')!
      const result = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
      expect(result[0].interface_type_id).toBe('t-eth') // отмеченная — изменена
      expect(result[1].interface_type_id).toBe('') // не отмеченная — без изменений
      expect(result[2].vlan_ids).toEqual(['v-mgmt']) // не отмеченная — VLAN не тронут
    })

    it('VLAN из панели добавляется к уже стоящим на порту (объединение, не замена)', async () => {
      const rows = threeRows()
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })

      const rowChecks = wrapper.findAll('.iface-table tbody .col-select input')
      await rowChecks[2].setValue(true) // отмечаем eth2 (уже с v-mgmt)
      await wrapper.find('.bulk-edit-bar .vlan-check input').setValue(true) // добавляем v-mgmt ещё раз через панель
      await wrapper.find('.bulk-edit-bar button').trigger('click')

      const emitted = wrapper.emitted('update:modelValue')!
      const result = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
      expect(result[2].vlan_ids).toEqual(['v-mgmt']) // без дублей
    })

    it('после применения панель сбрасывается — выбор и поля возвращаются к значениям по умолчанию', async () => {
      const rows = threeRows()
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })

      await wrapper.findAll('.iface-table tbody .col-select input')[0].setValue(true)
      await wrapper.find('.bulk-field select').setValue('t-eth')
      await wrapper.find('.bulk-edit-bar button').trigger('click')
      await wrapper.setProps({ modelValue: wrapper.emitted('update:modelValue')!.at(-1)![0] as InterfaceDraftRow[] })

      expect((wrapper.find('.bulk-field select').element as HTMLSelectElement).value).toBe('')
      expect((wrapper.findAll('.iface-table tbody .col-select input')[0].element as HTMLInputElement).checked).toBe(false)
    })
  })

  describe('п.3: подсказка при наведении на обрезанный текст в ячейках таблицы', () => {
    it('длинное имя интерфейса и сводка VLAN/IP используют v-truncate-tooltip', async () => {
      vi.useFakeTimers()
      try {
        const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'GigabitEthernet0/0/0/1.100500', vlan_mode: 'trunk', vlan_ids: ['v-1'] }]
        const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })

        const nameInput = wrapper.find('.cell-input')
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
})
