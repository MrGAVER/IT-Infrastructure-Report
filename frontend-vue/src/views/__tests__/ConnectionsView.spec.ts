import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConnectionsView from '../ConnectionsView.vue'
import ConnectionCanvasModal from '../../components/ConnectionCanvasModal.vue'
import PortConfigReviewModal from '../../components/PortConfigReviewModal.vue'
import { useConnectionsStore } from '../../stores/connections'
import { useCatalogsStore } from '../../stores/catalogs'
import { useDevicesStore } from '../../stores/devices'
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
  is_active: true,
  description: '',
  source_port_role: 'data',
  destination_port_role: 'data',
  port_config_status: 'ok',
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

describe('ConnectionsView.vue — визуальный режим (фикс п.3.4, батч4)', () => {
  it('кнопка "Визуальный режим" открывает схему подключений', async () => {
    const connections = useConnectionsStore()
    connections.loaded = true
    const catalogs = useCatalogsStore()
    catalogs.loaded = true
    const devices = useDevicesStore()
    devices.loaded = true

    const wrapper = mount(ConnectionsView)
    await flushPromises()

    expect(wrapper.findComponent(ConnectionCanvasModal).exists()).toBe(false)
    await wrapper.findAll('button').find((b) => b.text().includes('Визуальный режим'))!.trigger('click')

    expect(wrapper.findComponent(ConnectionCanvasModal).exists()).toBe(true)
  })

  it('после закрытия схемы перечитывает список подключений (могли добавиться новые перетаскиванием)', async () => {
    const connections = useConnectionsStore()
    connections.loaded = true
    const reloadSpy = vi.spyOn(connections, 'reload')
    const catalogs = useCatalogsStore()
    catalogs.loaded = true
    const devices = useDevicesStore()
    devices.loaded = true

    const wrapper = mount(ConnectionsView)
    await flushPromises()
    await wrapper.findAll('button').find((b) => b.text().includes('Визуальный режим'))!.trigger('click')
    await wrapper.findComponent(ConnectionCanvasModal).vm.$emit('close')
    await flushPromises()

    expect(wrapper.findComponent(ConnectionCanvasModal).exists()).toBe(false)
    expect(reloadSpy).toHaveBeenCalled()
  })
})

describe('ConnectionsView.vue — проверка ролей портов-соседей', () => {
  const mismatched: Connection = {
    ...connectionFixture,
    id: 'conn-2',
    source_device_name: 'srv-02',
    source_interface_name: 'idrac',
    destination_device_name: 'sw-02',
    destination_interface_name: 'gi0/7',
    source_port_role: 'management',
    destination_port_role: 'data',
    port_config_status: 'mismatch',
  }
  const approved: Connection = { ...mismatched, id: 'conn-3', source_device_name: 'srv-03', port_config_status: 'approved' }

  async function mountWith(rows: Connection[]) {
    const connections = useConnectionsStore()
    connections.all = rows
    connections.total = rows.length
    connections.loaded = true
    const catalogs = useCatalogsStore()
    catalogs.loaded = true
    const devices = useDevicesStore()
    devices.loaded = true
    const wrapper = mount(ConnectionsView)
    await flushPromises()
    return { wrapper, connections }
  }

  const rowsText = (wrapper: Awaited<ReturnType<typeof mountWith>>['wrapper']) => wrapper.findAll('tbody tr').map((r) => r.text())

  it('без расхождений баннер не показывается, а колонка «Роли портов» содержит роль порта', async () => {
    const { wrapper } = await mountWith([connectionFixture])

    expect(wrapper.find('.mismatch-banner').exists()).toBe(false)
    expect(wrapper.find('thead').text()).toContain('Роли портов')
    expect(wrapper.find('thead').text()).not.toContain('Назначение линии')
    expect(wrapper.find('tbody').text()).toContain('Передача данных')
    expect(wrapper.find('.port-badge').exists()).toBe(false)
  })

  it('показывает счётчик и баннер с числом расхождений; «Показать» включает фильтр расхождений', async () => {
    const { wrapper, connections } = await mountWith([connectionFixture, mismatched, approved])

    expect(wrapper.find('.mismatch-banner').text()).toContain('1')
    expect(wrapper.text()).toContain('Расхождения портов')

    await wrapper.find('[data-action="show-mismatches"]').trigger('click')

    expect(connections.portConfigFilter).toBe('mismatch')
    expect(rowsText(wrapper)).toHaveLength(1)
    expect(rowsText(wrapper)[0]).toContain('srv-02')
    expect(wrapper.find('[data-action="show-mismatches"]').exists()).toBe(false)
  })

  it('строка с расхождением показывает роли обоих портов и метку «Расхождение», одобренная — «Одобрено»', async () => {
    const { wrapper } = await mountWith([mismatched, approved])

    const [mismatchRow, approvedRow] = rowsText(wrapper)
    expect(mismatchRow).toContain('idrac: Управление активами')
    expect(mismatchRow).toContain('gi0/7: Передача данных')
    expect(mismatchRow).toContain('Расхождение')
    expect(approvedRow).toContain('Одобрено')
  })

  it('фильтры «Расхождения (N)» и «Одобренные (N)» оставляют только подходящие подключения', async () => {
    const { wrapper } = await mountWith([connectionFixture, mismatched, approved])

    expect(wrapper.find('[data-filter="mismatch"]').text()).toContain('(1)')
    expect(wrapper.find('[data-filter="approved"]').text()).toContain('(1)')

    await wrapper.find('[data-filter="approved"]').trigger('click')
    expect(rowsText(wrapper)).toHaveLength(1)
    expect(rowsText(wrapper)[0]).toContain('srv-03')

    await wrapper.find('[data-filter="mismatch"]').trigger('click')
    expect(rowsText(wrapper)[0]).toContain('srv-02')
  })

  it('поиск находит подключения по роли порта', async () => {
    const { wrapper, connections } = await mountWith([connectionFixture, mismatched])

    connections.search = 'управление'
    await flushPromises()

    expect(rowsText(wrapper)).toHaveLength(1)
    expect(rowsText(wrapper)[0]).toContain('srv-02')
  })

  it('клик по метке расхождения открывает окно проверки этого подключения', async () => {
    const { wrapper } = await mountWith([mismatched])

    await wrapper.find('.port-badge').trigger('click')

    const modal = wrapper.findComponent(PortConfigReviewModal)
    expect(modal.exists()).toBe(true)
    expect(modal.text()).toContain('srv-02')
    modal.vm.$emit('close')
    await flushPromises()
    expect(wrapper.findComponent(PortConfigReviewModal).exists()).toBe(false)
  })

  it('«Одобрить все показанные» после подтверждения отправляет id только подключений с расхождением', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    const calls: Array<{ url: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.endsWith('/connections/port-config/approve')) {
          return jsonResponse({ items: [{ ...mismatched, port_config_status: 'approved' }], skipped_ids: [] })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )
    const { wrapper, connections } = await mountWith([connectionFixture, mismatched, approved])
    connections.portConfigFilter = 'mismatch'
    await flushPromises()

    await wrapper.find('[data-action="approve-all"]').trigger('click')
    await flushPromises()

    expect(calls.find((c) => c.url.endsWith('/connections/port-config/approve'))!.body).toEqual({ connection_ids: ['conn-2'] })
    expect(connections.mismatchCount).toBe(0)
  })

  it('«Одобрить все показанные» ничего не отправляет, если пользователь отказался в подтверждении', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false))
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 }))
    vi.stubGlobal('fetch', fetchMock)
    const { wrapper, connections } = await mountWith([mismatched])
    connections.portConfigFilter = 'mismatch'
    await flushPromises()
    fetchMock.mockClear()

    await wrapper.find('[data-action="approve-all"]').trigger('click')
    await flushPromises()

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('кнопка пакетного одобрения видна только при включённом фильтре расхождений', async () => {
    const { wrapper } = await mountWith([mismatched])

    expect(wrapper.find('[data-action="approve-all"]').exists()).toBe(false)
  })

  it('смена фильтра сбрасывает страницу на первую', async () => {
    const rows = Array.from({ length: 10 }, (_, i) => ({ ...connectionFixture, id: `conn-x${i}` }))
    const { wrapper, connections } = await mountWith([...rows, mismatched])
    connections.setPage(2)
    expect(connections.page).toBe(2)

    await wrapper.find('[data-filter="mismatch"]').trigger('click')

    expect(connections.page).toBe(1)
    expect(rowsText(wrapper)).toHaveLength(1)
  })
})
