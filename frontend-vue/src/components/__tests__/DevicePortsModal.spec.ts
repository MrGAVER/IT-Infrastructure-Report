import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DevicePortsModal from '../DevicePortsModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'

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

function stubFetch() {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/resources/interfaces') && (init?.method ?? 'GET') === 'GET') {
      return jsonResponse({ items: [existingInterfaceFixture], total: 1, offset: 0, limit: 1000 })
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
})
