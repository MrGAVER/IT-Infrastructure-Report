import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DevicesView from '../DevicesView.vue'
import { useDevicesStore } from '../../stores/devices'
import { useCatalogsStore } from '../../stores/catalogs'
import { useVLANsStore } from '../../stores/vlans'
import { useDeviceStacksStore } from '../../stores/deviceStacks'
import type { Device } from '../../api/types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })),
  )
})

function device(overrides: Partial<Device>): Device {
  return {
    id: 'id-' + Math.random().toString(36).slice(2),
    device_type_id: 'dt-1',
    manufacturer_id: null,
    model_id: null,
    serial_number: 'SN-0000',
    system_name: null,
    operating_system_id: null,
    embedded_os_id: null,
    siem_enabled: false,
    building_id: null,
    room_id: null,
    rack_id: null,
    rack_position: null,
    description: null,
    diagram_icon_id: null,
    oac_certificate_number: null,
    oac_certificate_registry_date: null,
    stack_id: null,
    stack_name: null,
    stack_position: null,
    management_interface: '',
    management_ips: '',
    interface_count: 0,
    embedded_os_name: '',
    embedded_os_version: '',
    vlan_summary: '',
    ...overrides,
  }
}

function seed(devices: Device[]) {
  const store = useDevicesStore()
  store.all = devices
  store.total = devices.length
  store.loaded = true
  useCatalogsStore().items['device-types'] = [{ id: 'dt-1', name: 'Коммутатор' }]
  useCatalogsStore().loaded = true
  useVLANsStore().loaded = true
}

describe('DevicesView.vue', () => {
  it('кнопка "Стек" открывает форму создания стека', async () => {
    seed([])
    const wrapper = mount(DevicesView)
    await flushPromises()

    await wrapper
      .findAll('.filter-bar button')
      .find((b) => b.text() === 'Стек')!
      .trigger('click')

    expect(wrapper.find('.modal-head h2').text()).toBe('Добавить стек устройств')
  })

  it('устройства одного стека сворачиваются в одну строку с раскрывающимся списком участников', async () => {
    seed([
      device({ id: 'dev-1', system_name: 'core-sw-01', stack_id: 'stack-1', stack_name: 'Стек ядра', stack_position: 1 }),
      device({ id: 'dev-2', system_name: 'core-sw-02', stack_id: 'stack-1', stack_name: 'Стек ядра', stack_position: 2 }),
      device({ id: 'dev-3', system_name: 'edge-01' }),
    ])
    const wrapper = mount(DevicesView)
    await flushPromises()

    // 2 участника стека схлопнуты в одну строку + dev-3 отдельной строкой — 2 строки, не 3.
    expect(wrapper.findAll('tbody tr').filter((r) => !r.classes().includes('stack-member-row'))).toHaveLength(2)
    expect(wrapper.find('.stack-toggle').text()).toContain('Стек ядра')
    expect(wrapper.find('.stack-toggle').text()).toContain('2 устройства')
    expect(wrapper.findAll('.stack-member-row')).toHaveLength(0) // свёрнуто по умолчанию

    await wrapper.find('.stack-toggle').trigger('click')

    const memberRows = wrapper.findAll('.stack-member-row')
    expect(memberRows).toHaveLength(2)
    expect(memberRows[0].text()).toContain('#1')
    expect(memberRows[0].text()).toContain('core-sw-01')
    expect(memberRows[1].text()).toContain('#2')
    expect(memberRows[1].text()).toContain('core-sw-02')
  })

  it('повторный клик по строке стека снова сворачивает список участников', async () => {
    seed([
      device({ id: 'dev-1', system_name: 'sw-1', stack_id: 'stack-1', stack_name: 'Стек', stack_position: 1 }),
      device({ id: 'dev-2', system_name: 'sw-2', stack_id: 'stack-1', stack_name: 'Стек', stack_position: 2 }),
    ])
    const wrapper = mount(DevicesView)
    await flushPromises()

    await wrapper.find('.stack-toggle').trigger('click')
    expect(wrapper.findAll('.stack-member-row')).toHaveLength(2)

    await wrapper.find('.stack-toggle').trigger('click')
    expect(wrapper.findAll('.stack-member-row')).toHaveLength(0)
  })

  it('после создания стека форма переключается в режим редактирования, не закрываясь', async () => {
    seed([])
    const wrapper = mount(DevicesView)
    await flushPromises()

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        if (method === 'POST' && url.endsWith('/resources/device-stacks')) {
          return jsonResponse({ id: 'stack-new', name: 'Новый стек', description: null }, 201)
        }
        if (url.includes('/device-stacks/stack-new/detail')) {
          return jsonResponse({ stack: { id: 'stack-new', name: 'Новый стек', description: null }, members: [], connections: [] })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    await wrapper
      .findAll('.filter-bar button')
      .find((b) => b.text() === 'Стек')!
      .trigger('click')
    await wrapper.find('.modal input[type="text"]').setValue('Новый стек')
    await wrapper.find('.modal form').trigger('submit')
    await flushPromises()

    // Модалка не закрылась, а переключилась в режим редактирования только что созданного стека —
    // можно сразу добавлять участников, не открывая форму заново.
    expect(wrapper.find('.modal-head h2').text()).toBe('Редактировать стек устройств')
  })
})

describe('DevicesView.vue — тон «Нет» и нулевых счётчиков (UI-12)', () => {
  it('«Нет» в столбце SIEM нейтральный (neutral), «Да» — зелёный', async () => {
    seed([device({ id: 'a', system_name: 'a', siem_enabled: true }), device({ id: 'b', system_name: 'b', siem_enabled: false })])
    const wrapper = mount(DevicesView)
    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    expect(rows[0].find('.status').classes()).toContain('on')
    expect(rows[1].find('.status').classes()).toEqual(expect.arrayContaining(['off', 'neutral']))
  })

  it('«Без покрытия SIEM» = 0 — карточка не предупреждает; появляется устройство без SIEM — предупреждает', async () => {
    seed([device({ id: 'a', system_name: 'a', siem_enabled: true })])
    const wrapper = mount(DevicesView)
    await flushPromises()
    const card = () => wrapper.findAll('.stat-card').find((c) => c.text().includes('Без покрытия SIEM'))!

    expect(card().classes()).not.toContain('warn')

    const store = useDevicesStore()
    store.all = [...store.all, device({ id: 'b', system_name: 'b', siem_enabled: false })]
    store.total = 2
    await flushPromises()

    expect(card().classes()).toContain('warn')
  })
})

describe('DevicesView.vue — подпись счётчика строк (UI-09)', () => {
  const footText = (wrapper: ReturnType<typeof mount>) => wrapper.find('.table-foot span').text().replace(/\s+/g, ' ')

  it('со стеком число строк меньше числа устройств — подпись называет обе величины', async () => {
    seed([
      device({ id: 's1', system_name: 'stk-1', stack_id: 'st', stack_name: 'Стек', stack_position: 1 }),
      device({ id: 's2', system_name: 'stk-2', stack_id: 'st', stack_name: 'Стек', stack_position: 2 }),
      device({ id: 'x', system_name: 'edge-1' }),
    ])
    const wrapper = mount(DevicesView)
    await flushPromises()

    expect(footText(wrapper)).toBe('Показано 1–2 из 2 строк (устройств: 3)')
  })

  it('без стеков число строк равно числу устройств — подпись прежняя, без лишних скобок', async () => {
    seed([device({ id: 'a', system_name: 'a' }), device({ id: 'b', system_name: 'b' })])
    const wrapper = mount(DevicesView)
    await flushPromises()

    expect(footText(wrapper)).toBe('Показано 1–2 из 2')
  })

  it('поиск сужает обе величины: считаются отфильтрованные строки и устройства', async () => {
    seed([
      device({ id: 's1', system_name: 'stk-1', stack_id: 'st', stack_name: 'Стек', stack_position: 1 }),
      device({ id: 's2', system_name: 'stk-2', stack_id: 'st', stack_name: 'Стек', stack_position: 2 }),
      device({ id: 'x', system_name: 'edge-1' }),
    ])
    const wrapper = mount(DevicesView)
    await flushPromises()

    useDevicesStore().search = 'stk'
    await flushPromises()
    expect(footText(wrapper)).toBe('Показано 1–1 из 1 строк (устройств: 2)')

    useDevicesStore().search = 'edge'
    await flushPromises()
    expect(footText(wrapper)).toBe('Показано 1–1 из 1')
  })
})

describe('DevicesView.vue — стеки в дашборде «Стеки устройств» без перезагрузки страницы', () => {
  const NEW_STACK = { id: 'stack-new', name: 'Новый стек', description: null }

  /** Сервер, где стек уже создан: список /resources/device-stacks отдаёт его, остальное — пустые ответы. */
  function stubServerWithNewStack(calls: string[] = []) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push(`${method} ${url}`)
        if (method === 'POST' && url.endsWith('/resources/device-stacks')) return jsonResponse(NEW_STACK, 201)
        if (url.includes('/device-stacks/stack-new/detail')) return jsonResponse({ stack: NEW_STACK, members: [], connections: [] })
        if (url.includes('/resources/device-stacks')) return jsonResponse({ items: [NEW_STACK], total: 1, offset: 0, limit: 1000 })
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )
  }

  async function createStackFromRegistry(wrapper: ReturnType<typeof mount>) {
    await wrapper
      .findAll('.filter-bar button')
      .find((b) => b.text() === 'Стек')!
      .trigger('click')
    await wrapper.find('.modal input[type="text"]').setValue('Новый стек')
    await wrapper.find('.modal form').trigger('submit')
    await flushPromises()
  }

  it('стек, созданный в «Инвентаризации устройств», попадает в уже загруженный стор «Стеки устройств»', async () => {
    seed([])
    // Дашборд «Стеки устройств» уже открывали в этой сессии: стор загружен и пуст, ensureLoaded() его не перечитает.
    const stacks = useDeviceStacksStore()
    stacks.all = []
    stacks.loaded = true
    stubServerWithNewStack()
    const wrapper = mount(DevicesView)
    await flushPromises()

    await createStackFromRegistry(wrapper)

    expect(stacks.all.map((s) => s.id)).toEqual(['stack-new'])
  })

  it('закрытие окна стека крестиком (после добавления участников) обновляет и устройства, и стеки', async () => {
    seed([])
    const stacks = useDeviceStacksStore()
    stacks.all = []
    stacks.loaded = true
    const calls: string[] = []
    stubServerWithNewStack(calls)
    const wrapper = mount(DevicesView)
    await flushPromises()
    await createStackFromRegistry(wrapper)
    calls.length = 0

    await wrapper.find('.modal .icon-btn[aria-label="Закрыть"]').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.startsWith('GET') && c.includes('/devices'))).toBe(true)
    expect(calls.some((c) => c.startsWith('GET') && c.includes('/resources/device-stacks'))).toBe(true)
  })
})
