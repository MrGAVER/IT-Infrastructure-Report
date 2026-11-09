import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DevicePortsModal from '../DevicePortsModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useVLANsStore } from '../../stores/vlans'
import { useConnectionsStore } from '../../stores/connections'
import { useToast } from '../../composables/useToast'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

// Весь шаблон DevicePortsModal.vue телепортируется в document.body (см. компонент — как и
// QuickAddModal.vue), поэтому wrapper.find()/wrapper.text() на самом компоненте ничего не
// находят: нужно искать в body напрямую, тот же приём, что в ConnectionFormModal.spec.ts.
function body(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

const existingInterfaceFixture = {
  id: 'if-1',
  physical_device_id: 'dev-1',
  name: 'eth0',
  interface_type_id: null,
  mac_address: null,
  speed_id: null,
  is_management: false,
  is_data_transfer: false,
  description: null,
}

const deviceFixture = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' }

function stubFetch() {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/resources/interfaces') && (init?.method ?? 'GET') === 'GET') {
      return jsonResponse({ items: [existingInterfaceFixture], total: 1, offset: 0, limit: 1000 })
    }
    if (url.includes('/resources/devices/dev-1') && (init?.method ?? 'GET') === 'GET') {
      return jsonResponse(deviceFixture)
    }
    if ((init?.method ?? 'GET') === 'PUT' && url.includes('/devices/dev-1/interfaces')) {
      return jsonResponse({ items: [{ ...existingInterfaceFixture, name: 'eth0-renamed' }] })
    }
    return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
})

describe('DevicePortsModal.vue', () => {
  it('грузит существующие порты устройства и показывает их в редакторе', async () => {
    vi.stubGlobal('fetch', stubFetch())
    mount(DevicePortsModal, { props: { deviceId: 'dev-1', deviceLabel: 'srv-01' } })
    await flushPromises()

    expect(body().text()).toContain('srv-01')
    expect(body().find('.iface-table input.cell-input').element).toHaveProperty('value', 'eth0')
  })

  it('группы портов: грузятся вместе с портами и уходят тем же PUT — правка портов здесь не отвязывает их от групп', async () => {
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.includes('/devices/dev-1/interface-groups')) {
          return jsonResponse({
            items: [
              { id: 'g-1', physical_device_id: 'dev-1', name: 'Серверные', vlan_mode: null, vlan_ids: [], ips: [], manage_open_ports: false, open_ports: [] },
            ],
          })
        }
        if (url.includes('/resources/interfaces') && method === 'GET') {
          return jsonResponse({ items: [{ ...existingInterfaceFixture, group_id: 'g-1' }], total: 1, offset: 0, limit: 1000 })
        }
        if (url.includes('/resources/devices/dev-1') && method === 'GET') return jsonResponse(deviceFixture)
        if (method === 'PUT' && url.includes('/devices/dev-1/interfaces')) return jsonResponse({ items: [existingInterfaceFixture], groups: [] })
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )
    const catalogs = useCatalogsStore()
    catalogs.loaded = true

    mount(DevicePortsModal, { props: { deviceId: 'dev-1', deviceLabel: 'srv-01' } })
    await flushPromises()
    expect(body().find('.groups-panel').text()).toContain('Серверные')

    await body().find('.modal-foot .btn-primary, form .btn-primary, .btn-primary[type="submit"]').trigger('click')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-1/interfaces'))
    const payload = put?.body as { groups: Array<{ id: string; name: string }>; interfaces: Array<{ group_key: string | null }> }
    expect(payload.groups.map((g) => [g.id, g.name])).toEqual([['g-1', 'Серверные']])
    expect(payload.interfaces.map((i) => i.group_key)).toEqual(['g-1'])
  })

  it('сохраняет через PUT /devices/{id}/interfaces, точечно обновляет каталог и эмитит saved', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const catalogs = useCatalogsStore()
    // catalogs.loaded=true — иначе onMounted() внутри DevicePortsModal.vue вызовет
    // ensureLoaded() → reload(), который перезатрёт items['interfaces'], выставленный ниже
    // напрямую для теста, результатом мока GET /resources/interfaces.
    catalogs.loaded = true
    // Каталог уже содержит порт другого устройства — он не должен быть задет точечным
    // обновлением (см. catalogs.ts:replaceDeviceInterfaces).
    catalogs.items['interfaces'] = [{ id: 'if-other', name: 'eth0', physical_device_id: 'dev-2' }]

    const wrapper = mount(DevicePortsModal, { props: { deviceId: 'dev-1', deviceLabel: 'srv-01' } })
    await flushPromises()

    await body().find('.modal-foot button.btn-primary').trigger('click')
    await flushPromises()

    const emitted = wrapper.emitted('saved')
    expect(emitted).toBeTruthy()
    expect(emitted![0][0]).toBe('dev-1')
    expect(catalogs.items['interfaces']).toEqual([
      { id: 'if-other', name: 'eth0', physical_device_id: 'dev-2' },
      { ...existingInterfaceFixture, name: 'eth0-renamed' },
    ])
  })

  it('показывает ошибку сервера и не эмитит saved, если сохранение не удалось', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/resources/interfaces') && (init?.method ?? 'GET') === 'GET') {
          return jsonResponse({ items: [existingInterfaceFixture], total: 1, offset: 0, limit: 1000 })
        }
        if ((init?.method ?? 'GET') === 'PUT' && url.includes('/devices/dev-1/interfaces')) {
          return jsonResponse({ detail: 'Нарушение целостности данных: FOREIGN KEY' }, 409)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    const wrapper = mount(DevicePortsModal, { props: { deviceId: 'dev-1', deviceLabel: 'srv-01' } })
    await flushPromises()

    await body().find('.modal-foot button.btn-primary').trigger('click')
    await flushPromises()

    expect(body().text()).toContain('Нарушение целостности данных')
    expect(wrapper.emitted('saved')).toBeFalsy()
  })

  it('закрывает модалку по клику на "Отмена"', async () => {
    vi.stubGlobal('fetch', stubFetch())
    const wrapper = mount(DevicePortsModal, { props: { deviceId: 'dev-1', deviceLabel: 'srv-01' } })
    await flushPromises()

    await body().find('.modal-foot button.btn-secondary').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('вычисляет vlanOptions для редактора — каталог типа устройства ∪ уже назначенные устройству VLAN', async () => {
    const vlans = useVLANsStore()
    vlans.groups = [
      { vlan_id: 10, definitions: [{ id: 'v-type', vlan_id: 10, name: 'Каталожный', description: '', domain_id: null, domain_name: '', devices: [] }] },
      { vlan_id: 20, definitions: [{ id: 'v-assigned', vlan_id: 20, name: 'Назначенный', description: '', domain_id: null, domain_name: '', devices: [] }] },
      { vlan_id: 30, definitions: [{ id: 'v-other', vlan_id: 30, name: 'Посторонний', description: '', domain_id: null, domain_name: '', devices: [] }] },
    ]
    vlans.loaded = true

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/resources/interfaces') && (init?.method ?? 'GET') === 'GET') {
          return jsonResponse({ items: [existingInterfaceFixture], total: 1, offset: 0, limit: 1000 })
        }
        if (url.includes('/resources/devices/dev-1') && (init?.method ?? 'GET') === 'GET') {
          return jsonResponse(deviceFixture)
        }
        if (url.includes('/resources/device-type-vlans')) {
          return jsonResponse({ items: [{ id: 'l-1', device_type_id: 'dt-server', vlan_id: 'v-type' }], total: 1, offset: 0, limit: 1000 })
        }
        if (url.includes('/resources/device-vlans')) {
          return jsonResponse({
            items: [
              {
                id: 'dv-1',
                physical_device_id: 'dev-1',
                vlan_id: 'v-assigned',
                ip_address: null,
                prefix_length: null,
                is_management: false,
                description: null,
              },
            ],
            total: 1,
            offset: 0,
            limit: 1000,
          })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    mount(DevicePortsModal, { props: { deviceId: 'dev-1', deviceLabel: 'srv-01' } })
    await flushPromises()
    await body().find('.expand-toggle').trigger('click') // VLAN на порту скрыты под toggle (п.3.4)

    // Каталог типа устройства (v-type) и уже назначенный VLAN (v-assigned) — оба доступны для
    // чекбокса "VLAN на порту"; посторонний VLAN (ни в каталоге, ни назначен) — недоступен.
    // Список VLAN trunk-порта — во всплывающем окне (PortVlanPickerModal); :not(.vlan-check-all) — исключает
    // сводный чекбокс "Все VLAN" (п.1.4.3.2).
    await body().find('.iface-detail .vlan-picker-btn').trigger('click')
    const labels = body()
      .findAll('.vlan-picker-modal .vlan-check:not(.vlan-check-all)')
      .map((l) => l.text())
    expect(labels).toEqual(['10 — Каталожный', '20 — Назначенный'])
    expect(labels.some((t) => t.includes('Посторонний'))).toBe(false)
  })

  describe('уведомление о сохранении порта с расхождением относительно соседа', () => {
    // Порт if-1 (dev-1) подключён активным кабелем к порту if-other (dev-2) с конфигурацией
    // «управление: нет / передача данных: нет / trunk» — то есть той же, что у if-1 по умолчанию.
    // Сосед приходит с сервера вместе с подключением (GET /devices/{id}/interface-connections); общий список
    // подключений и каталог интерфейсов не используются — стор подключений пуст намеренно.
    function mountWithNeighbour(thisPort: { is_management: boolean }) {
      useToast().toasts.splice(0)
      const connections = useConnectionsStore()
      connections.loaded = true
      connections.all = []
      const port = { ...existingInterfaceFixture, ...thisPort, vlan_mode: 'trunk' }
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          if (url.includes('/resources/interfaces') && method === 'GET') return jsonResponse({ items: [port], total: 1, offset: 0, limit: 1000 })
          if (url.includes('/resources/devices/dev-1') && method === 'GET') return jsonResponse(deviceFixture)
          if (method === 'PUT' && url.includes('/devices/dev-1/interfaces')) return jsonResponse({ items: [port] })
          if (method === 'GET' && /\/devices\/dev-1\/interface-connections$/.test(url)) {
            return jsonResponse({
              items: [
                {
                  interface_id: 'if-1',
                  connection_id: 'c-1',
                  connection_type_id: 'ct',
                  description: null,
                  peer_interface_id: 'if-other',
                  peer_interface_name: 'Gi0/2',
                  peer_device_id: 'dev-2',
                  peer_device_name: 'sw-02',
                  peer_is_management: false,
                  peer_is_data_transfer: false,
                  peer_vlan_mode: 'trunk',
                },
              ],
            })
          }
          return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
        }),
      )
      return mount(DevicePortsModal, { props: { deviceId: 'dev-1', deviceLabel: 'srv-01' } })
    }

    it('порт сохранён с новой конфигурацией, расходящейся с соседом, — warning-toast с именами обоих портов', async () => {
      const wrapper = mountWithNeighbour({ is_management: false })
      await flushPromises()

      await body().find('tr:not(.bulk-edit-row) td.col-check input').setValue(true) // «Управление» только у нашего порта
      await body().find('.modal-foot button.btn-primary').trigger('click')
      await flushPromises()

      const toasts = useToast().toasts
      expect(toasts).toHaveLength(1)
      expect(toasts[0].type).toBe('warning')
      expect(toasts[0].message).toContain('Порты сохранены')
      expect(toasts[0].message).toContain('eth0')
      expect(toasts[0].message).toContain('Gi0/2 (sw-02)')
      expect(wrapper.emitted('saved')).toBeTruthy()
    })

    it('расхождение существовало при открытии и порт не менялся — повторного уведомления нет', async () => {
      const wrapper = mountWithNeighbour({ is_management: true })
      await flushPromises()

      await body().find('.modal-foot button.btn-primary').trigger('click')
      await flushPromises()

      expect(useToast().toasts).toHaveLength(0)
      expect(wrapper.emitted('saved')).toBeTruthy()
    })

    it('сохранение не удалось — уведомления о портах нет', async () => {
      const wrapper = mountWithNeighbour({ is_management: false })
      await flushPromises()
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_url: string, init?: RequestInit) =>
          (init?.method ?? 'GET') === 'PUT' ? jsonResponse({ detail: 'ошибка сервера' }, 409) : jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 }),
        ),
      )

      await body().find('tr:not(.bulk-edit-row) td.col-check input').setValue(true)
      await body().find('.modal-foot button.btn-primary').trigger('click')
      await flushPromises()

      expect(useToast().toasts).toHaveLength(0)
      expect(wrapper.emitted('saved')).toBeFalsy()
    })
  })

  it('подинтерфейс на VLAN, недоступном порту, блокирует сохранение: запись не уходит, ошибка показана', async () => {
    const puts: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        if (method === 'PUT') puts.push(url)
        if (url.includes('/devices/dev-1/subinterfaces')) {
          return jsonResponse({
            items: [
              {
                id: 'sub-1',
                parent_interface_id: 'if-1',
                name: 'eth0.10',
                vlan_id: 'v-10',
                is_management: false,
                is_data_transfer: false,
                description: null,
                ips: [],
                open_ports: [],
              },
            ],
          })
        }
        if (url.includes('/resources/interfaces') && method === 'GET')
          return jsonResponse({ items: [existingInterfaceFixture], total: 1, offset: 0, limit: 1000 })
        if (url.includes('/resources/devices/dev-1') && method === 'GET') return jsonResponse(deviceFixture)
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )
    mount(DevicePortsModal, { props: { deviceId: 'dev-1', deviceLabel: 'srv-01' } })
    await flushPromises()

    await body().find('.modal-foot .btn-primary').trigger('click')
    await flushPromises()

    expect(puts).toEqual([])
    expect(body().text()).toContain('VLAN подинтерфейса «eth0.10»')
  })

  // Пункт 3 предложений по улучшению (ревью merge/review-f06-stage2-f05-executors): порты сохраняются PUT-ом ЦЕЛИКОМ, поэтому пустой
  // редактор после сбоя загрузки нельзя сохранять — устройство потеряло бы все порты.
  describe('сбой загрузки портов', () => {
    const saveButton = () => document.body.querySelector('.btn-primary') as HTMLButtonElement

    /** Первый GET портов падает (503), затем отвечает как обычно; calls — все запросы. */
    function stubFlakyPorts() {
      const calls: Array<{ url: string; method: string }> = []
      let portGets = 0
      const ok = stubFetch()
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          calls.push({ url, method: init?.method ?? 'GET' })
          if (url.includes('/resources/interfaces') && url.includes('physical_device_id=dev-1') && (init?.method ?? 'GET') === 'GET' && ++portGets === 1) {
            return jsonResponse({ detail: 'сервер недоступен' }, 503)
          }
          return ok(url, init)
        }),
      )
      return calls
    }

    it('редактор скрыт, показано сообщение с причиной и «Повторить загрузку»; «Сохранить» неактивна и PUT не уходит', async () => {
      const calls = stubFlakyPorts()
      const wrapper = mount(DevicePortsModal, { props: { deviceId: 'dev-1', deviceLabel: 'srv-01' }, attachTo: document.body })
      await flushPromises()

      expect(document.body.querySelector('.load-notice')?.getAttribute('data-kind')).toBe('failed')
      expect(document.body.querySelector('.form-error')?.textContent).toContain('сервер недоступен')
      expect(document.body.querySelector('.iface-table')).toBeNull()
      expect(saveButton().disabled).toBe(true)

      saveButton().click()
      await flushPromises()
      expect(calls.filter((c) => c.method === 'PUT')).toEqual([])
      wrapper.unmount()
    })

    it('«Повторить загрузку»: порты появляются, сообщение и ошибка исчезают, «Сохранить» снова доступна', async () => {
      stubFlakyPorts()
      const wrapper = mount(DevicePortsModal, { props: { deviceId: 'dev-1', deviceLabel: 'srv-01' }, attachTo: document.body })
      await flushPromises()

      ;(document.body.querySelector('[data-action="retry-load"]') as HTMLButtonElement).click()
      await flushPromises()

      expect(document.body.querySelector('.load-notice')).toBeNull()
      expect(document.body.querySelector('.form-error')).toBeNull()
      expect((document.body.querySelector('.iface-table input.cell-input') as HTMLInputElement).value).toBe('eth0')
      expect(saveButton().disabled).toBe(false)
      wrapper.unmount()
    })
  })
})
