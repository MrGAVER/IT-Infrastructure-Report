import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConnectionsView from '../ConnectionsView.vue'
import { useConnectionsStore } from '../../stores/connections'
import { useCatalogsStore } from '../../stores/catalogs'
import type { Connection } from '../../api/types'

// DevicePortsModal.vue телепортируется в body (см. DevicePortsModal.spec.ts) — ищем там же.
function body(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

const connectionFixture: Connection = {
  id: 'conn-1',
  source_interface_id: 'if-1',
  source_device_name: 'srv-01',
  source_interface_name: 'eth0',
  destination_interface_id: 'if-2',
  destination_device_name: 'sw-01',
  destination_interface_name: 'gi0/1',
  connection_type_id: 'ct-1',
  connection_type_name: 'Витая пара',
  purpose: '',
  is_active: true,
  description: '',
} as unknown as Connection

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })))
})

describe('ConnectionsView.vue — управление портами прямо из строки таблицы', () => {
  it('открывает DevicePortsModal для устройства-источника, найденного через каталог интерфейсов', async () => {
    const connections = useConnectionsStore()
    connections.all = [connectionFixture]
    connections.total = 1
    connections.loaded = true

    const catalogs = useCatalogsStore()
    catalogs.loaded = true
    // Единственный способ узнать physical_device_id по interface_id — уже загруженный каталог
    // 'interfaces' (Connection отдаёт только *_name, см. комментарий в ConnectionsView.vue).
    catalogs.items['interfaces'] = [{ id: 'if-1', name: 'eth0', physical_device_id: 'dev-1' }]

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/resources/interfaces') && (init?.method ?? 'GET') === 'GET') {
          return jsonResponse({ items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0' }], total: 1, offset: 0, limit: 1000 })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    const wrapper = mount(ConnectionsView)
    await flushPromises()

    await wrapper.find('[aria-label="Управлять портами исходного устройства"]').trigger('click')
    await flushPromises()

    expect(body().text()).toContain('Порты устройства «srv-01»')
  })

  it('после сохранения портов перечитывает список подключений (могло измениться имя порта)', async () => {
    const connections = useConnectionsStore()
    connections.all = [connectionFixture]
    connections.total = 1
    connections.loaded = true
    const reloadSpy = vi.spyOn(connections, 'reload')

    const catalogs = useCatalogsStore()
    catalogs.loaded = true
    catalogs.items['interfaces'] = [{ id: 'if-1', name: 'eth0', physical_device_id: 'dev-1' }]

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.includes('/resources/interfaces') && (init?.method ?? 'GET') === 'GET') {
          return jsonResponse({ items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0' }], total: 1, offset: 0, limit: 1000 })
        }
        if ((init?.method ?? 'GET') === 'PUT' && url.includes('/devices/dev-1/interfaces')) {
          return jsonResponse({ items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0-renamed' }] })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    const wrapper = mount(ConnectionsView)
    await flushPromises()
    await wrapper.find('[aria-label="Управлять портами исходного устройства"]').trigger('click')
    await flushPromises()

    await body().find('.modal-foot button.btn-primary').trigger('click')
    await flushPromises()

    expect(reloadSpy).toHaveBeenCalled()
    expect(body().text()).not.toContain('Порты устройства')
  })

  it('клик по кнопке порта для устройства, отсутствующего в каталоге интерфейсов, ничего не открывает', async () => {
    const connections = useConnectionsStore()
    connections.all = [connectionFixture]
    connections.total = 1
    connections.loaded = true
    const catalogs = useCatalogsStore()
    catalogs.loaded = true
    catalogs.items['interfaces'] = [] // if-1 не найден -> physical_device_id неизвестен

    const wrapper = mount(ConnectionsView)
    await flushPromises()
    await wrapper.find('[aria-label="Управлять портами исходного устройства"]').trigger('click')
    await flushPromises()

    expect(body().text()).not.toContain('Порты устройства')
  })
})
