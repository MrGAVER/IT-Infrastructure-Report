import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConnectionFormModal from '../ConnectionFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useDevicesStore } from '../../stores/devices'
import { useConnectionsStore } from '../../stores/connections'
import { useToast } from '../../composables/useToast'
import { portRoleOf } from '../../utils/portConfig'
import type { DeviceInterface, PortConfigFacet, PortConfigPreview, PortConfigPreviewSide } from '../../api/types'

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

// Эмулятор GET /connections/port-config/preview над каталогом интерфейсов (роль и режим берутся
// оттуда, VLAN — из карты `vlans`; одобрение — по полному «ключу» расхождения). Правила те же, что
// у backend/app/services/port_config.py: различие роли, режима или набора VLAN; неактивное
// подключение — всегда ok; одобрение действует, пока ключ расхождения тот же.
interface PreviewWorld {
  vlans?: Record<string, number[]>
  approved?: Record<string, string>
}
const configKey = (s: PortConfigPreviewSide, d: PortConfigPreviewSide) =>
  `${s.role}>${d.role}|${s.mode}>${d.mode}|${s.vlans.join(',')}>${d.vlans.join(',')}`

function previewFor(url: string, world: PreviewWorld): PortConfigPreview {
  const p = new URL(url, 'http://x').searchParams
  const interfaces = useCatalogsStore().items['interfaces'] as unknown as DeviceInterface[]
  const side = (id: string): PortConfigPreviewSide => {
    const i = interfaces.find((x) => x.id === id)!
    return { interface_id: id, role: portRoleOf(i), mode: i.vlan_mode ?? 'trunk', vlans: world.vlans?.[id] ?? [] }
  }
  const source = side(p.get('source_interface_id')!)
  const destination = side(p.get('destination_interface_id')!)
  const diff: PortConfigFacet[] = []
  if (source.role !== destination.role) diff.push('role')
  if (source.mode !== destination.mode) diff.push('mode')
  if (source.vlans.join() !== destination.vlans.join()) diff.push('vlans')
  const active = p.get('is_active') !== 'false'
  const connectionId = p.get('connection_id')
  const approved = connectionId !== null && world.approved?.[connectionId] === configKey(source, destination)
  return { status: !active || !diff.length ? 'ok' : approved ? 'approved' : 'mismatch', diff: active ? diff : [], source, destination }
}

describe('ConnectionFormModal.vue — роли портов и обязательное решение при расхождении', () => {
  // «Назначение линии связи» из подключения удалено: его целиком определяют роли двух портов
  // (is_management / is_data_transfer). При расхождении форма НЕ сохраняет подключение молча —
  // сначала пользователь выбирает решение (выровнять любой порт или одобрить расхождение).
  function setupInterfaces(source: Partial<DeviceInterface>, destination: Partial<DeviceInterface>) {
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = [
      { id: 'if-src', name: 'Gi0/1', physical_device_id: 'dev-src', is_management: false, is_data_transfer: false, ...source },
      { id: 'if-dst', name: 'Gi0/2', physical_device_id: 'dev-dst', is_management: false, is_data_transfer: false, ...destination },
    ] as never
    catalogs.items['connection-types'] = [{ id: 'ct-1', name: 'Медь' }]
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

  async function fillCableType(wrapper: ReturnType<typeof mount>) {
    await chooseOption(wrapper.find('.form-grid .searchable-select'), 'Медь')
  }

  async function fillAndSubmit(wrapper: ReturnType<typeof mount>) {
    await selectBothEndpoints(wrapper)
    await fillCableType(wrapper)
    await wrapper.find('.modal-foot .btn-primary').trigger('click')
    await flushPromises()
  }

  interface Call { url: string; method: string; body?: Record<string, unknown> }

  function stubApi(opts: { portRoleStatus?: number; approveStatus?: number; previewStatus?: number; world?: PreviewWorld } = {}) {
    const calls: Call[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        const body = init?.body ? (JSON.parse(init.body as string) as Record<string, unknown>) : undefined
        calls.push({ url, method, body })
        if (method === 'GET' && url.includes('/connections/port-config/preview')) {
          if (opts.previewStatus) return jsonResponse({ detail: 'Сервер недоступен' }, opts.previewStatus)
          return jsonResponse(previewFor(url, opts.world ?? {}))
        }
        if (method === 'PUT' && url.includes('/port-role')) {
          if (opts.portRoleStatus) return jsonResponse({ detail: 'Порт не найден' }, opts.portRoleStatus)
          const id = url.match(/interfaces\/([^/]+)\/port-role/)![1]
          // Как настоящий сервер: порт целиком (с режимом и прочими полями), а не только роль.
          const existing = (useCatalogsStore().items['interfaces'] as unknown as DeviceInterface[]).find((i) => i.id === id)
          return jsonResponse({ ...existing, ...body })
        }
        if (method === 'POST' && url.endsWith('/resources/connections')) return jsonResponse({ id: 'conn-new' }, 201)
        if (method === 'PUT' && url.includes('/resources/connections/')) return jsonResponse({ id: 'conn-1' })
        if (method === 'POST' && url.endsWith('/connections/port-config/approve')) {
          if (opts.approveStatus) return jsonResponse({ detail: 'Сервер недоступен' }, opts.approveStatus)
          return jsonResponse({ items: [], skipped_ids: [] })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )
    return calls
  }

  const saveCalls = (calls: Call[]) => calls.filter((c) => c.url.includes('/resources/connections'))

  it('поля «Назначение линии связи» в форме больше нет', async () => {
    setupInterfaces({ is_data_transfer: true }, { is_data_transfer: true })
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    await selectBothEndpoints(wrapper)

    expect(wrapper.find('input[list="purpose-presets"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Назначение линии связи')
  })

  it('после выбора обоих портов показывает роль каждого из них', async () => {
    setupInterfaces({ is_management: true }, { is_data_transfer: true })
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    await selectBothEndpoints(wrapper)

    const roles = wrapper.find('.port-roles')
    expect(roles.exists()).toBe(true)
    expect(roles.text()).toContain('Gi0/1 — Управление активами')
    expect(roles.text()).toContain('Gi0/2 — Передача данных')
    expect(roles.classes()).toContain('mismatch')
  })

  it('роли совпадают — предупреждения нет, подключение сохраняется сразу и без поля purpose', async () => {
    setupInterfaces({ is_data_transfer: true }, { is_data_transfer: true })
    const calls = stubApi()
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })

    await fillAndSubmit(wrapper)

    expect(wrapper.find('.port-roles').classes()).not.toContain('mismatch')
    expect(wrapper.find('.resolution').exists()).toBe(false)
    const [create] = saveCalls(calls)
    expect(create.method).toBe('POST')
    expect(create.body).toEqual({ source_interface_id: 'if-src', destination_interface_id: 'if-dst', connection_type_id: 'ct-1', is_active: true, description: null })
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })

  it('роли расходятся — сохранение не выполняется, а спрашивает решение', async () => {
    setupInterfaces({ is_management: true }, { is_data_transfer: true })
    const calls = stubApi()
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })

    await fillAndSubmit(wrapper)

    expect(saveCalls(calls)).toEqual([])
    expect(wrapper.emitted('saved')).toBeUndefined()
    const resolution = wrapper.find('.resolution')
    expect(resolution.exists()).toBe(true)
    expect(resolution.text()).toContain('Gi0/1')
    expect(resolution.text()).toContain('Gi0/2')
    // Вместо «Отмена/Добавить» — четыре варианта решения.
    expect(wrapper.find('.modal-foot').exists()).toBe(false)
    expect(resolution.findAll('button')).toHaveLength(4)
  })

  it('«Вернуться к правке» закрывает вопрос, ничего не отправляя', async () => {
    setupInterfaces({ is_management: true }, { is_data_transfer: true })
    const calls = stubApi()
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    await fillAndSubmit(wrapper)

    await wrapper.find('[data-resolution="back"]').trigger('click')

    expect(wrapper.find('.resolution').exists()).toBe(false)
    expect(wrapper.find('.modal-foot').exists()).toBe(true)
    expect(calls.filter((c) => c.method !== 'GET')).toEqual([])
  })

  it('«Порту назначения задать роль как у источника»: сначала меняется роль порта, затем сохраняется подключение', async () => {
    setupInterfaces({ is_management: true }, { is_data_transfer: true })
    const calls = stubApi()
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    await fillAndSubmit(wrapper)

    await wrapper.find('[data-resolution="keep-source"]').trigger('click')
    await flushPromises()

    const writes = calls.filter((c) => c.method !== 'GET')
    expect(writes.map((c) => `${c.method} ${c.url.replace(/^.*\/api\/v1/, '')}`)).toEqual([
      'PUT /interfaces/if-dst/port-role',
      'POST /resources/connections',
    ])
    expect(writes[0].body).toEqual({ is_management: true, is_data_transfer: false })
    expect(wrapper.emitted('saved')).toHaveLength(1)
    // Кэш портов обновлён — расхождения в форме больше нет.
    const catalogs = useCatalogsStore()
    expect(catalogs.items['interfaces'].find((i) => i.id === 'if-dst')).toMatchObject({ is_management: true, is_data_transfer: false })
  })

  it('«Порту источника задать роль как у назначения» меняет порт-источник', async () => {
    setupInterfaces({ is_management: true }, { is_data_transfer: true })
    const calls = stubApi()
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    await fillAndSubmit(wrapper)

    await wrapper.find('[data-resolution="keep-destination"]').trigger('click')
    await flushPromises()

    const portRole = calls.find((c) => c.url.includes('/port-role'))!
    expect(portRole.url).toContain('/interfaces/if-src/port-role')
    expect(portRole.body).toEqual({ is_management: false, is_data_transfer: true })
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })

  it('«Оставить как есть»: подключение сохраняется, затем расхождение одобряется; роли портов не трогаются', async () => {
    setupInterfaces({ is_management: true }, { is_data_transfer: true })
    const calls = stubApi()
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    await fillAndSubmit(wrapper)

    await wrapper.find('[data-resolution="approve"]').trigger('click')
    await flushPromises()

    const writes = calls.filter((c) => c.method !== 'GET')
    expect(writes.map((c) => `${c.method} ${c.url.replace(/^.*\/api\/v1/, '')}`)).toEqual([
      'POST /resources/connections',
      'POST /connections/port-config/approve',
    ])
    expect(writes[1].body).toEqual({ connection_ids: ['conn-new'] })
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })

  it('не удалось одобрить: подключение всё равно сохранено, форма закрывается, пользователь получает предупреждение', async () => {
    setupInterfaces({ is_management: true }, { is_data_transfer: true })
    stubApi({ approveStatus: 500 })
    const toasts = useToast().toasts
    toasts.splice(0)
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    await fillAndSubmit(wrapper)

    await wrapper.find('[data-resolution="approve"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(toasts.some((t) => t.type === 'warning' && t.message.includes('расхождение не одобрено'))).toBe(true)
  })

  it('не удалось изменить роль порта: подключение не создаётся, ошибка показана в форме', async () => {
    setupInterfaces({ is_management: true }, { is_data_transfer: true })
    const calls = stubApi({ portRoleStatus: 404 })
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    await fillAndSubmit(wrapper)

    await wrapper.find('[data-resolution="keep-source"]').trigger('click')
    await flushPromises()

    expect(saveCalls(calls)).toEqual([])
    expect(wrapper.emitted('saved')).toBeUndefined()
    expect(wrapper.find('.form-error').text()).toContain('Порт не найден')
  })

  describe('режим порта и VLAN (сверка делает сервер)', () => {
    const previewCalls = (calls: Call[]) => calls.filter((c) => c.url.includes('/connections/port-config/preview'))
    const lastPreviewParams = (calls: Call[]) => new URL(previewCalls(calls).at(-1)!.url, 'http://x').searchParams

    it('после выбора обоих портов показывает у каждого роль, режим и VLAN и запрашивает сверку у сервера', async () => {
      setupInterfaces({ is_data_transfer: true, vlan_mode: 'trunk' }, { is_data_transfer: true, vlan_mode: 'trunk' })
      const calls = stubApi({ world: { vlans: { 'if-src': [10, 11, 12, 20], 'if-dst': [10, 11, 12, 20] } } })
      const wrapper = mount(ConnectionFormModal, { props: { connection: null } })

      await selectBothEndpoints(wrapper)
      await flushPromises()

      const roles = wrapper.find('.port-roles')
      expect(roles.text()).toContain('Gi0/1 — Передача данных · trunk · VLAN 10–12, 20')
      expect(roles.text()).toContain('Gi0/2 — Передача данных · trunk · VLAN 10–12, 20')
      expect(roles.classes()).not.toContain('mismatch')
      expect(previewCalls(calls)).toHaveLength(1)
      const params = lastPreviewParams(calls)
      expect([params.get('source_interface_id'), params.get('destination_interface_id'), params.get('is_active')]).toEqual(['if-src', 'if-dst', 'true'])
      expect(params.has('connection_id')).toBe(false) // новое подключение
    })

    it('режимы различаются (роли и VLAN те же) — предупреждение называет режим, сохранение спрашивает решение без выравнивания роли', async () => {
      setupInterfaces({ is_data_transfer: true, vlan_mode: 'trunk' }, { is_data_transfer: true, vlan_mode: 'access' })
      const calls = stubApi()
      const wrapper = mount(ConnectionFormModal, { props: { connection: null } })

      await fillAndSubmit(wrapper)

      expect(wrapper.find('.port-roles').classes()).toContain('mismatch')
      expect(wrapper.find('.port-roles .warning-text').text()).toContain('(режим)')
      expect(saveCalls(calls)).toEqual([])
      const resolution = wrapper.find('.resolution')
      expect(resolution.exists()).toBe(true)
      expect(resolution.text()).toContain('«Gi0/1» — Передача данных · trunk')
      expect(resolution.text()).toContain('«Gi0/2» — Передача данных · access')
      expect(resolution.find('[data-resolution="keep-source"]').exists()).toBe(false) // роль выравнивать нечего
      expect(resolution.find('[data-hint="port-setup"]').text()).toContain('Управлять портами')
      expect(resolution.find('[data-resolution="approve"]').exists()).toBe(true)
    })

    it('наборы VLAN различаются — то же: решение обязательно, «одобрить» сохраняет подключение и одобряет расхождение', async () => {
      setupInterfaces({ is_data_transfer: true }, { is_data_transfer: true })
      const calls = stubApi({ world: { vlans: { 'if-src': [10, 20], 'if-dst': [10, 30] } } })
      const wrapper = mount(ConnectionFormModal, { props: { connection: null } })

      await fillAndSubmit(wrapper)
      expect(wrapper.find('.port-roles .warning-text').text()).toContain('(VLAN)')
      expect(saveCalls(calls)).toEqual([])

      await wrapper.find('[data-resolution="approve"]').trigger('click')
      await flushPromises()

      expect(saveCalls(calls)[0].method).toBe('POST')
      expect(calls.some((c) => c.url.endsWith('/connections/port-config/approve') && JSON.stringify(c.body) === '{"connection_ids":["conn-new"]}')).toBe(true)
      expect(wrapper.emitted('saved')).toHaveLength(1)
    })

    it('различаются роль И режим: после выравнивания роли остаток (режим) снова требует решения — молча не сохраняется', async () => {
      setupInterfaces({ is_management: true, vlan_mode: 'trunk' }, { is_data_transfer: true, vlan_mode: 'access' })
      const calls = stubApi()
      const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
      await fillAndSubmit(wrapper)
      expect(wrapper.find('.port-roles .warning-text').text()).toContain('(роль, режим)')

      await wrapper.find('[data-resolution="keep-source"]').trigger('click')
      await flushPromises()

      expect(calls.some((c) => c.method === 'PUT' && c.url.includes('/interfaces/if-dst/port-role'))).toBe(true)
      expect(saveCalls(calls)).toEqual([]) // подключение ещё не сохранено
      const resolution = wrapper.find('.resolution')
      expect(resolution.exists()).toBe(true)
      expect(resolution.text()).toContain('(режим)')
      expect(resolution.find('[data-resolution="keep-source"]').exists()).toBe(false) // роли уже совпадают

      await resolution.find('[data-resolution="approve"]').trigger('click')
      await flushPromises()

      expect(saveCalls(calls)[0].method).toBe('POST')
      expect(wrapper.emitted('saved')).toHaveLength(1)
    })

    it('различается только роль: после выравнивания подключение сохраняется сразу, без повторного вопроса', async () => {
      setupInterfaces({ is_management: true }, { is_data_transfer: true })
      const calls = stubApi()
      const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
      await fillAndSubmit(wrapper)

      await wrapper.find('[data-resolution="keep-source"]').trigger('click')
      await flushPromises()

      expect(wrapper.find('.resolution').exists()).toBe(false)
      expect(saveCalls(calls)[0].method).toBe('POST')
      expect(wrapper.emitted('saved')).toHaveLength(1)
    })

    it('неактивное подключение расхождением не считается: предупреждения нет, сохраняется сразу', async () => {
      setupInterfaces({ is_data_transfer: true, vlan_mode: 'trunk' }, { is_data_transfer: true, vlan_mode: 'access' })
      const calls = stubApi()
      const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
      await selectBothEndpoints(wrapper)
      await flushPromises()
      expect(wrapper.find('.port-roles').classes()).toContain('mismatch')

      await wrapper.find('.checkbox-field input').setValue(false)
      await flushPromises()

      expect(lastPreviewParams(calls).get('is_active')).toBe('false')
      expect(wrapper.find('.port-roles').classes()).not.toContain('mismatch')
      await fillCableType(wrapper)
      await wrapper.find('.modal-foot .btn-primary').trigger('click')
      await flushPromises()
      expect(wrapper.find('.resolution').exists()).toBe(false)
      expect(saveCalls(calls)[0].method).toBe('POST')
    })

    it('«Сохранить» сразу после выбора порта дожидается ответа сервера и только потом решает, спрашивать ли', async () => {
      setupInterfaces({ is_data_transfer: true, vlan_mode: 'trunk' }, { is_data_transfer: true, vlan_mode: 'access' })
      const calls = stubApi()
      const respond = (globalThis.fetch as unknown as { getMockImplementation: () => (url: string, init?: RequestInit) => Promise<Response> }).getMockImplementation()
      let release!: () => void
      const gate = new Promise<void>((resolve) => (release = resolve))
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          if (url.includes('/connections/port-config/preview')) await gate // ответ сверки «задерживается»
          return respond(url, init)
        }),
      )
      const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
      await selectBothEndpoints(wrapper)
      await fillCableType(wrapper)

      await wrapper.find('.modal-foot .btn-primary').trigger('click')
      await flushPromises()
      expect(saveCalls(calls)).toEqual([]) // ушло бы сохранение «вслепую», не будь ожидания
      expect(wrapper.find('.resolution').exists()).toBe(false) // решение ещё не принято — ответа нет

      release()
      await flushPromises()

      expect(wrapper.find('.resolution').exists()).toBe(true)
      expect(saveCalls(calls)).toEqual([])
    })

    it('после «Управлять портами» сверка пересчитывается — VLAN порта могли измениться без смены роли и режима', async () => {
      setupInterfaces({ is_data_transfer: true }, { is_data_transfer: true })
      useCatalogsStore().loaded = true // иначе DevicePortsModal.onMounted перезатрёт items['interfaces'] через reload()
      const calls = stubApi({ world: { vlans: { 'if-src': [10], 'if-dst': [10] } } })
      const respond = (globalThis.fetch as unknown as { getMockImplementation: () => (url: string, init?: RequestInit) => Promise<Response> }).getMockImplementation()
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          // Сохранение портов в модалке возвращает порты устройства как есть (роль и режим те же).
          if ((init?.method ?? 'GET') === 'PUT' && url.includes('/devices/dev-src/interfaces')) {
            const ports = (useCatalogsStore().items['interfaces'] as unknown as DeviceInterface[]).filter((i) => i.physical_device_id === 'dev-src')
            return jsonResponse({ items: ports })
          }
          return respond(url, init)
        }),
      )
      const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
      await selectBothEndpoints(wrapper)
      await flushPromises()
      const before = previewCalls(calls).length
      expect(before).toBe(1)

      await wrapper.find('[aria-label="Управлять портами исходного устройства"]').trigger('click')
      await flushPromises()
      await new DOMWrapper(document.body).find('.modal-foot button.btn-primary').trigger('click')
      await flushPromises()

      expect(previewCalls(calls)).toHaveLength(before + 1)
    })

    it('сервер недоступен: роли по-прежнему сверяются по каталогу, режим и VLAN не показываются', async () => {
      setupInterfaces({ is_management: true }, { is_data_transfer: true })
      const calls = stubApi({ previewStatus: 500 })
      const wrapper = mount(ConnectionFormModal, { props: { connection: null } })

      await fillAndSubmit(wrapper)

      expect(wrapper.find('.port-roles').text()).toContain('Gi0/1 — Управление активами')
      expect(wrapper.find('.port-roles').text()).not.toContain('VLAN')
      expect(wrapper.find('.resolution').exists()).toBe(true) // молча не сохраняется
      expect(saveCalls(calls)).toEqual([])
    })

    it('сервер недоступен и роли совпадают: форма не блокирует сохранение', async () => {
      setupInterfaces({ is_data_transfer: true }, { is_data_transfer: true })
      const calls = stubApi({ previewStatus: 500 })
      const wrapper = mount(ConnectionFormModal, { props: { connection: null } })

      await fillAndSubmit(wrapper)

      expect(wrapper.find('.resolution').exists()).toBe(false)
      expect(saveCalls(calls)[0].method).toBe('POST')
    })

    it('при правке подключения сервер получает его id — чтобы учесть одобрение', async () => {
      setupInterfaces({ is_data_transfer: true }, { is_data_transfer: true })
      const calls = stubApi()
      mount(ConnectionFormModal, {
        props: {
          connection: {
            id: 'conn-7', source_interface_id: 'if-src', destination_interface_id: 'if-dst', connection_type_id: 'ct-1', is_active: true, description: null,
          } as never,
        },
      })
      await flushPromises()

      expect(lastPreviewParams(calls).get('connection_id')).toBe('conn-7')
    })

    it('одобренное расхождение режима и VLAN не спрашивается повторно, пока оно не изменилось; изменилось — спрашивается заново', async () => {
      const connection = {
        id: 'conn-1', source_interface_id: 'if-src', destination_interface_id: 'if-dst', connection_type_id: 'ct-1', is_active: true, description: null,
        port_config_status: 'approved' as const,
      }
      setupInterfaces({ is_data_transfer: true, vlan_mode: 'trunk' }, { is_data_transfer: true, vlan_mode: 'access' })
      const approvedKey = 'data>data|trunk>access|10,20>10'

      const calls = stubApi({ world: { vlans: { 'if-src': [10, 20], 'if-dst': [10] }, approved: { 'conn-1': approvedKey } } })
      const same = mount(ConnectionFormModal, { props: { connection: connection as never } })
      await flushPromises()
      expect(same.find('.port-roles .approved-text').text()).toContain('(режим, VLAN) одобрено ранее')
      await same.find('.modal-foot .btn-primary').trigger('click')
      await flushPromises()
      expect(same.find('.resolution').exists()).toBe(false)
      expect(saveCalls(calls)[0].method).toBe('PUT')

      // VLAN приёмника изменили после одобрения — подпись уже другая.
      const changedCalls = stubApi({ world: { vlans: { 'if-src': [10, 20], 'if-dst': [10, 30] }, approved: { 'conn-1': approvedKey } } })
      const changed = mount(ConnectionFormModal, { props: { connection: connection as never } })
      await flushPromises()
      await changed.find('.modal-foot .btn-primary').trigger('click')
      await flushPromises()
      expect(changed.find('.resolution').exists()).toBe(true)
      expect(saveCalls(changedCalls)).toEqual([])
    })
  })

  describe('редактирование подключения с уже одобренным расхождением', () => {
    const approvedConnection = {
      id: 'conn-1', source_interface_id: 'if-src', destination_interface_id: 'if-dst', connection_type_id: 'ct-1',
      is_active: true, description: null,
      source_device_name: 'src-dev', source_interface_name: 'Gi0/1', destination_device_name: 'dst-dev', destination_interface_name: 'Gi0/2', connection_type_name: 'Медь',
      source_port_role: 'management' as const, destination_port_role: 'data' as const, port_config_status: 'approved' as const,
      source_vlan_mode: 'trunk' as const, destination_vlan_mode: 'trunk' as const, source_vlans: [], destination_vlans: [], port_config_diff: ['role' as const],
    }

    it('роли те же, что были одобрены — повторно не спрашивает и сохраняет сразу', async () => {
      setupInterfaces({ is_management: true }, { is_data_transfer: true })
      const calls = stubApi({ world: { approved: { 'conn-1': 'management>data|trunk>trunk|>' } } })
      const wrapper = mount(ConnectionFormModal, { props: { connection: approvedConnection } })
      await flushPromises()

      expect(wrapper.find('.port-roles').text()).toContain('одобрено ранее')
      await wrapper.find('.modal-foot .btn-primary').trigger('click')
      await flushPromises()

      expect(wrapper.find('.resolution').exists()).toBe(false)
      expect(saveCalls(calls)[0].method).toBe('PUT')
      expect(wrapper.emitted('saved')).toHaveLength(1)
    })

    it('роль порта изменилась после одобрения — решение нужно принять заново', async () => {
      setupInterfaces({ is_management: true }, { is_management: true, is_data_transfer: true })
      const calls = stubApi({ world: { approved: { 'conn-1': 'management>data|trunk>trunk|>' } } })
      const wrapper = mount(ConnectionFormModal, { props: { connection: approvedConnection } })
      await flushPromises()

      await wrapper.find('.modal-foot .btn-primary').trigger('click')
      await flushPromises()

      expect(wrapper.find('.resolution').exists()).toBe(true)
      expect(saveCalls(calls)).toEqual([])
    })
  })
})

describe('ConnectionFormModal.vue — prefill (фикс п.3.4, визуальный режим подключений)', () => {
  // Источник и назначение уже выбраны перетаскиванием на схеме (ConnectionCanvasModal.vue) —
  // форма должна открыться сразу с обоими портами подставленными, без ручного выбора устройств.
  it('подставляет устройства и порты источника/назначения из prefill при создании', () => {
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = [
      { id: 'if-src', physical_device_id: 'dev-src', name: 'Gi0/1' },
      { id: 'if-dst', physical_device_id: 'dev-dst', name: 'Gi0/2' },
    ]
    const devices = useDevicesStore()
    devices.all = [
      { id: 'dev-src', system_name: 'srv-01', serial_number: 'SN-1' } as never,
      { id: 'dev-dst', system_name: 'srv-02', serial_number: 'SN-2' } as never,
    ]

    const wrapper = mount(ConnectionFormModal, { props: { connection: null, prefill: { sourceInterfaceId: 'if-src', destinationInterfaceId: 'if-dst' } } })

    const sourceFieldset = wrapper.findAll('.endpoint')[0]
    const destinationFieldset = wrapper.findAll('.endpoint')[1]
    expect(displayedValue(sourceFieldset.findAll('.searchable-select')[0])).toBe('srv-01')
    expect(displayedValue(sourceFieldset.findAll('.searchable-select')[1])).toBe('Gi0/1')
    expect(displayedValue(destinationFieldset.findAll('.searchable-select')[0])).toBe('srv-02')
    expect(displayedValue(destinationFieldset.findAll('.searchable-select')[1])).toBe('Gi0/2')
  })

  it('игнорируется при редактировании существующего подключения (connection важнее подсказки)', () => {
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = [
      { id: 'if-a', physical_device_id: 'dev-a', name: 'eth0' },
      { id: 'if-b', physical_device_id: 'dev-b', name: 'eth1' },
      { id: 'if-c', physical_device_id: 'dev-c', name: 'eth2' },
    ]
    const devices = useDevicesStore()
    devices.all = [
      { id: 'dev-a', system_name: 'a', serial_number: 'SN-A' } as never,
      { id: 'dev-b', system_name: 'b', serial_number: 'SN-B' } as never,
      { id: 'dev-c', system_name: 'c', serial_number: 'SN-C' } as never,
    ]
    const connection = {
      id: 'c1', source_interface_id: 'if-a', destination_interface_id: 'if-b', connection_type_id: 'ct-1',
      is_active: true, description: null,
      source_device_name: 'a', source_interface_name: 'eth0', destination_device_name: 'b', destination_interface_name: 'eth1', connection_type_name: 'Медь',
      source_port_role: 'data' as const, destination_port_role: 'data' as const, port_config_status: 'ok' as const,
      source_vlan_mode: 'trunk' as const, destination_vlan_mode: 'trunk' as const, source_vlans: [], destination_vlans: [], port_config_diff: [],
    }

    const wrapper = mount(ConnectionFormModal, { props: { connection, prefill: { sourceInterfaceId: 'if-a', destinationInterfaceId: 'if-c' } } })

    const destinationFieldset = wrapper.findAll('.endpoint')[1]
    expect(displayedValue(destinationFieldset.findAll('.searchable-select')[1])).toBe('eth1') // из connection, не из prefill
  })

  it('не подставляет ничего без prefill (обычное создание "с чистого листа")', () => {
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })
    const sourceFieldset = wrapper.findAll('.endpoint')[0]
    expect(displayedValue(sourceFieldset.findAll('.searchable-select')[0])).toBe('')
  })
})
