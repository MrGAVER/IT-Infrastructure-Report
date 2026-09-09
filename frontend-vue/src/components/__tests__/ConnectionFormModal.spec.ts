import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConnectionFormModal from '../ConnectionFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useDevicesStore } from '../../stores/devices'
import { useConnectionsStore } from '../../stores/connections'
import type { DeviceInterface } from '../../api/types'

// QuickAddModal.vue телепортируется в document.body — см. QuickAddModal.spec.ts.
function teleportedContent(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

// Фикс п.3.6: "Устройство"/"Порт"/"Тип подключения" — теперь SearchableSelect (см.
// SearchableSelect.spec.ts на сам механизм поиска), а не нативный <select>, поэтому
// .setValue() на select больше не годится — нужно открыть список и кликнуть нужную опцию по
// подписи. select — это САМ .searchable-select конкретного поля (не общий контейнер,
// который мог бы содержать несколько таких компонентов сразу, как fieldset .endpoint).
async function chooseOption(select: DOMWrapper<Element>, label: string) {
  await select.find('input').trigger('focus')
  const option = select.findAll('.ss-option').find((o) => o.text() === label)
  if (!option) throw new Error(`Опция "${label}" не найдена среди: ${select.findAll('.ss-option').map((o) => o.text())}`)
  await option.trigger('mousedown')
}

function displayedValue(root: DOMWrapper<Element>): string {
  return (root.find('.searchable-select input').element as HTMLInputElement).value
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })))
})

describe('ConnectionFormModal.vue — быстрое добавление типа подключения', () => {
  it('подставляет id быстро добавленного типа подключения в форму', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['connection-types'] = []
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/connection-types')) {
          return jsonResponse({ id: 'ct-new', name: 'Оптоволокно' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    // .form-grid .lookup-row — сужаем от общего ".lookup-row button", т.к. теперь такие кнопки
    // есть ещё у выбора портов источника/назначения (кнопка "Управлять портами", см.
    // DevicePortsModal.vue) — без сужения find() мог бы вернуть не ту кнопку.
    await wrapper.find('.form-grid .lookup-row button').trigger('click') // "+" рядом с типом подключения
    await teleportedContent().find('input[type="text"]').setValue('Оптоволокно')
    await teleportedContent().find('form').trigger('submit')
    await flushPromises()

    expect(displayedValue(wrapper.find('.form-grid .lookup-row'))).toBe('Оптоволокно')
  })
})

describe('ConnectionFormModal.vue — управление портами прямо из формы', () => {
  it('кнопка "Управлять портами" неактивна, пока устройство не выбрано', () => {
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    const btn = wrapper.find('[aria-label="Управлять портами исходного устройства"]')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('открывает DevicePortsModal с меткой выбранного устройства и сбрасывает удалённый порт после сохранения', async () => {
    const catalogs = useCatalogsStore()
    catalogs.loaded = true // иначе DevicePortsModal.onMounted перезатрёт items['interfaces'] через reload()
    catalogs.items['interfaces'] = [{ id: 'if-1', name: 'eth0', physical_device_id: 'dev-1' }]
    const devices = useDevicesStore()
    devices.all = [{ id: 'dev-1', system_name: 'srv-01', serial_number: 'SN-1' } as never]

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/resources/interfaces') && (init?.method ?? 'GET') === 'GET') {
          return jsonResponse({ items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0' }], total: 1, offset: 0, limit: 1000 })
        }
        // Сохранение портов в модалке удаляет единственный порт устройства.
        if ((init?.method ?? 'GET') === 'PUT' && url.includes('/devices/dev-1/interfaces')) {
          return jsonResponse({ items: [] })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    const sourceFieldset = wrapper.findAll('.endpoint')[0]
    const sourceDeviceSelect = sourceFieldset.findAll('.searchable-select')[0]
    const sourcePortSelect = sourceFieldset.findAll('.searchable-select')[1]

    await chooseOption(sourceFieldset.findAll('.searchable-select')[0], 'srv-01')
    await chooseOption(sourceFieldset.findAll('.searchable-select')[1], 'eth0')
    expect(displayedValue(sourcePortSelect)).toBe('eth0')

    await wrapper.find('[aria-label="Управлять портами исходного устройства"]').trigger('click')
    await flushPromises()

    expect(new DOMWrapper(document.body).text()).toContain('Порты устройства «srv-01»')

    await new DOMWrapper(document.body).find('.modal-foot button.btn-primary').trigger('click')
    await flushPromises()

    // Порт удалён в модалке -> в форме подключения выбор порта должен сброситься, а не
    // молча указывать на несуществующий id. sourceDeviceSelect не тронут — устройство осталось.
    expect(displayedValue(sourcePortSelect)).toBe('')
    expect(displayedValue(sourceDeviceSelect)).toBe('srv-01')
    // Модалка портов закрылась сама после сохранения.
    expect(new DOMWrapper(document.body).text()).not.toContain('Порты устройства')
  })
})

describe('ConnectionFormModal.vue — предупреждение о свободных портах (п.5)', () => {
  // Регрессия: раньше показывалось одно и то же "Нет свободных портов — все заняты активными
  // подключениями" в двух РАЗНЫХ по сути ситуациях — когда порты реально заняты, И когда у
  // устройства попросту ещё не заведено ни одного порта (обычное дело для только что
  // созданного устройства) — второй случай вводил в заблуждение: порты никуда не подключены.

  it('у устройства без единого порта — подсказка "нет портов", а не "все заняты"', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = []
    const devices = useDevicesStore()
    devices.all = [{ id: 'dev-1', system_name: 'srv-01', serial_number: 'SN-1' } as never]

    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    const sourceFieldset = wrapper.findAll('.endpoint')[0]
    await chooseOption(sourceFieldset.findAll('.searchable-select')[0], 'srv-01')

    expect(sourceFieldset.text()).toContain('У устройства пока нет ни одного порта')
    expect(sourceFieldset.text()).not.toContain('все заняты активными подключениями')
  })

  it('у устройства, чей единственный порт занят активным подключением — подсказка "все заняты"', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = [{ id: 'if-1', name: 'eth0', physical_device_id: 'dev-1' }] as never
    const devices = useDevicesStore()
    devices.all = [{ id: 'dev-1', system_name: 'srv-01', serial_number: 'SN-1' } as never]
    const connections = useConnectionsStore()
    connections.all = [
      { id: 'c-1', source_interface_id: 'if-1', destination_interface_id: 'if-other', is_active: true } as never,
    ]

    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    const sourceFieldset = wrapper.findAll('.endpoint')[0]
    await chooseOption(sourceFieldset.findAll('.searchable-select')[0], 'srv-01')

    expect(sourceFieldset.text()).toContain('Нет свободных портов — все заняты активными подключениями')
    expect(sourceFieldset.text()).not.toContain('нет ни одного порта')
  })

  it('у устройства со свободным портом никакая подсказка не показывается', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = [{ id: 'if-1', name: 'eth0', physical_device_id: 'dev-1' }] as never
    const devices = useDevicesStore()
    devices.all = [{ id: 'dev-1', system_name: 'srv-01', serial_number: 'SN-1' } as never]

    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    const sourceFieldset = wrapper.findAll('.endpoint')[0]
    await chooseOption(sourceFieldset.findAll('.searchable-select')[0], 'srv-01')

    expect(sourceFieldset.text()).not.toContain('нет ни одного порта')
    expect(sourceFieldset.text()).not.toContain('Нет свободных портов')
  })
})

describe('ConnectionFormModal.vue — поиск в полях "Устройство"/"Порт" (фикс п.3.6)', () => {
  it('поле "Устройство" фильтруется вводом текста и отсортировано по алфавиту', async () => {
    const devices = useDevicesStore()
    devices.all = [
      { id: 'dev-2', system_name: 'core-sw-02', serial_number: 'SN-2' } as never,
      { id: 'dev-1', system_name: 'access-sw-01', serial_number: 'SN-1' } as never,
    ]

    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    const sourceFieldset = wrapper.findAll('.endpoint')[0]
    const deviceSelect = sourceFieldset.findAll('.searchable-select')[0]

    await deviceSelect.find('input').trigger('focus')
    // Отсортировано: "access-sw-01" раньше "core-sw-02" по алфавиту, а не в порядке devicesStore.all.
    expect(deviceSelect.findAll('.ss-option').map((o) => o.text())).toEqual(['access-sw-01', 'core-sw-02'])

    await deviceSelect.find('input').setValue('core')
    const filtered = deviceSelect.findAll('.ss-option')
    expect(filtered).toHaveLength(1)
    expect(filtered[0].text()).toBe('core-sw-02')
  })

  it('поле "Порт" фильтруется вводом текста', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = [
      { id: 'if-1', name: 'GigabitEthernet0/1', physical_device_id: 'dev-1' },
      { id: 'if-2', name: 'GigabitEthernet0/2', physical_device_id: 'dev-1' },
    ] as never
    const devices = useDevicesStore()
    devices.all = [{ id: 'dev-1', system_name: 'srv-01', serial_number: 'SN-1' } as never]

    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    const sourceFieldset = wrapper.findAll('.endpoint')[0]
    await chooseOption(sourceFieldset.findAll('.searchable-select')[0], 'srv-01')

    const portSelect = sourceFieldset.findAll('.searchable-select')[1]
    await portSelect.find('input').trigger('focus')
    await portSelect.find('input').setValue('0/2')
    const filtered = portSelect.findAll('.ss-option')
    expect(filtered).toHaveLength(1)
    expect(filtered[0].text()).toBe('GigabitEthernet0/2')
  })
})

describe('ConnectionFormModal.vue — "Назначение линии связи" по данным портов (фикс п.3.3)', () => {
  function setupInterfaces(source: Partial<DeviceInterface>, destination: Partial<DeviceInterface>) {
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = [
      { id: 'if-src', name: 'Gi0/1', physical_device_id: 'dev-src', is_management: false, is_data_transfer: false, ...source },
      { id: 'if-dst', name: 'Gi0/2', physical_device_id: 'dev-dst', is_management: false, is_data_transfer: false, ...destination },
    ] as never
    const devices = useDevicesStore()
    devices.all = [
      { id: 'dev-src', system_name: 'src-dev', serial_number: 'SN-1' } as never,
      { id: 'dev-dst', system_name: 'dst-dev', serial_number: 'SN-2' } as never,
    ]
  }

  async function selectBothEndpoints(wrapper: ReturnType<typeof mount>) {
    const [sourceFieldset, destinationFieldset] = wrapper.findAll('.endpoint')
    await chooseOption(sourceFieldset.findAll('.searchable-select')[0], 'src-dev')
    await chooseOption(sourceFieldset.findAll('.searchable-select')[1], 'Gi0/1')
    await chooseOption(destinationFieldset.findAll('.searchable-select')[0], 'dst-dev')
    await chooseOption(destinationFieldset.findAll('.searchable-select')[1], 'Gi0/2')
  }

  function purposeInput(wrapper: ReturnType<typeof mount>) {
    return wrapper.find('input[list="purpose-presets"]')
  }

  it('оба порта отмечены "Управление" — назначение подставляется автоматически', async () => {
    setupInterfaces({ is_management: true, is_data_transfer: false }, { is_management: true, is_data_transfer: false })
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    await selectBothEndpoints(wrapper)
    expect((purposeInput(wrapper).element as HTMLInputElement).value).toBe('Управление активами')
  })

  it('оба порта отмечены "Передача данных" и "Управление" одновременно', async () => {
    setupInterfaces({ is_management: true, is_data_transfer: true }, { is_management: true, is_data_transfer: true })
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    await selectBothEndpoints(wrapper)
    expect((purposeInput(wrapper).element as HTMLInputElement).value).toBe('Передача данных и управление активами')
  })

  it('порты расходятся — предупреждение показывается, поле не заполняется автоматически', async () => {
    setupInterfaces({ is_management: true, is_data_transfer: false }, { is_management: false, is_data_transfer: true })
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    await selectBothEndpoints(wrapper)

    expect((purposeInput(wrapper).element as HTMLInputElement).value).toBe('')
    const warning = wrapper.find('.purpose-mismatch')
    expect(warning.exists()).toBe(true)
    expect(warning.text()).toContain('Gi0/1')
    expect(warning.text()).toContain('Gi0/2')
  })

  it('ручной нестандартный текст назначения не затирается при смене порта', async () => {
    setupInterfaces({ is_management: true, is_data_transfer: false }, { is_management: false, is_data_transfer: false })
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    const [sourceFieldset] = wrapper.findAll('.endpoint')
    await chooseOption(sourceFieldset.findAll('.searchable-select')[0], 'src-dev')
    await chooseOption(sourceFieldset.findAll('.searchable-select')[1], 'Gi0/1')

    await purposeInput(wrapper).setValue('Резервный канал для репликации СХД')

    const [, destinationFieldset] = wrapper.findAll('.endpoint')
    await chooseOption(destinationFieldset.findAll('.searchable-select')[0], 'dst-dev')
    await chooseOption(destinationFieldset.findAll('.searchable-select')[1], 'Gi0/2')

    expect((purposeInput(wrapper).element as HTMLInputElement).value).toBe('Резервный канал для репликации СХД')
  })

  it('кнопка выравнивания сохраняет флаги "проигравшего" порта и обновляет назначение', async () => {
    setupInterfaces({ is_management: true, is_data_transfer: false }, { is_management: false, is_data_transfer: true })
    vi.stubGlobal('confirm', vi.fn(() => true))
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.includes('/resources/interfaces') && method === 'GET' && url.includes('dev-dst')) {
          return new Response(JSON.stringify({ items: [{ id: 'if-dst', physical_device_id: 'dev-dst', name: 'Gi0/2', vlan_mode: 'access' }], total: 1, offset: 0, limit: 1000 }))
        }
        if (method === 'PUT' && url.includes('/devices/dev-dst/interfaces')) {
          return new Response(JSON.stringify({ items: [{ id: 'if-dst', physical_device_id: 'dev-dst', name: 'Gi0/2', is_management: true, is_data_transfer: false, vlan_mode: 'access' }] }))
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    await selectBothEndpoints(wrapper)

    // "Взять как на «Gi0/1»" — источник управляет, назначение должно перейти на порт назначения.
    await wrapper.find('.purpose-mismatch-actions button').trigger('click')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-dst/interfaces'))
    expect((put!.body as { interfaces: Array<{ id: string; is_management: boolean; is_data_transfer: boolean }> }).interfaces[0]).toMatchObject({
      id: 'if-dst',
      is_management: true,
      is_data_transfer: false,
    })
    expect(wrapper.find('.purpose-mismatch').exists()).toBe(false) // расхождения больше нет
    expect((purposeInput(wrapper).element as HTMLInputElement).value).toBe('Управление активами')
  })
})
