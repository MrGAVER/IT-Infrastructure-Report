import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DevicePortsModal from '../DevicePortsModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useVLANsStore } from '../../stores/vlans'

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
    expect(body().find('.iface-card input[type="text"]').element).toHaveProperty('value', 'eth0')
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
            items: [{ id: 'dv-1', physical_device_id: 'dev-1', vlan_id: 'v-assigned', ip_address: null, prefix_length: null, is_management: false, description: null }],
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

    // Каталог типа устройства (v-type) и уже назначенный VLAN (v-assigned) — оба доступны для
    // чекбокса "VLAN на порту"; посторонний VLAN (ни в каталоге, ни назначен) — недоступен.
    // .iface-card — иначе подхватились бы ещё и чекбоксы из панели "Массовое редактирование".
    const labels = body()
      .findAll('.iface-card .vlan-check')
      .map((l) => l.text())
    expect(labels).toEqual(['10 — Каталожный', '20 — Назначенный'])
    expect(labels.some((t) => t.includes('Посторонний'))).toBe(false)
  })
})
