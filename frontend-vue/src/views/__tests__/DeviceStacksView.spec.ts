import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceStacksView from '../DeviceStacksView.vue'
import { useDeviceStacksStore } from '../../stores/deviceStacks'
import { useDevicesStore } from '../../stores/devices'
import { useCatalogsStore } from '../../stores/catalogs'
import { useAuthStore } from '../../stores/auth'
import type { Device, DeviceStack, StackVlanRow } from '../../api/types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

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

const CORE: DeviceStack = { id: 'stack-1', name: 'Стек ядра', description: '2 коммутатора Cisco' }
const ACCESS: DeviceStack = { id: 'stack-2', name: 'Стек доступа', description: null }

/** Сервер: список стеков отдаёт server.stacks (его можно менять между запросами), остальное — пустые ответы. */
interface FakeServer {
  stacks: DeviceStack[]
  /** Общие VLAN по id стека; 'error' — сервер отвечает ошибкой. Нет записи — у стека нет общих VLAN. */
  vlans?: Record<string, StackVlanRow[] | 'error'>
}

function stubServer(server: FakeServer, calls: string[] = []) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push(`${method} ${url}`)
      if (method === 'GET' && url.includes('/resources/device-stacks')) {
        return jsonResponse({ items: server.stacks, total: server.stacks.length, offset: 0, limit: 1000 })
      }
      const vlansMatch = method === 'GET' ? url.match(/\/device-stacks\/([^/]+)\/vlans/) : null
      if (vlansMatch) {
        const rows = server.vlans?.[vlansMatch[1]] ?? []
        if (rows === 'error') return jsonResponse({ detail: 'Сбой сервера' }, 500)
        return jsonResponse({ stack_id: vlansMatch[1], member_count: 2, items: rows, available: [] })
      }
      if (url.includes('/device-stacks/') && url.endsWith('/detail')) {
        return jsonResponse({ stack: server.stacks[0], members: [], connections: [] })
      }
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
    }),
  )
}

/** Реестр устройств и справочники уже загружены (как после захода на «Инвентаризацию устройств»). */
function seedDevices(devices: Device[]) {
  const store = useDevicesStore()
  store.all = devices
  store.total = devices.length
  store.loaded = true
  const catalogs = useCatalogsStore()
  catalogs.items['manufacturers'] = [{ id: 'mf-1', name: 'Cisco' }]
  catalogs.items['device-models'] = [{ id: 'dm-1', model: 'C9300' }] as never
  catalogs.items['buildings'] = [{ id: 'b-1', name: 'Главный корпус' }]
  catalogs.items['rooms'] = [{ id: 'r-1', name: 'Серверная' }] as never
  catalogs.loaded = true
}

const sharedVlan = (overrides: Partial<StackVlanRow> = {}): StackVlanRow => ({
  vlan_id: 'v-10',
  vlan_number: 10,
  vlan_name: 'Servers',
  domain_id: null,
  is_shared: true,
  ip_address: '10.0.10.1',
  prefix_length: 24,
  is_management: true,
  is_uniform: true,
  assigned_count: 2,
  member_count: 2,
  members: [],
  ...overrides,
})
const vlanCalls = (calls: string[]) => calls.filter((c) => c.startsWith('GET') && /\/device-stacks\/[^/]+\/vlans/.test(c))

const coreMembers = () => [
  device({
    id: 'd-2',
    system_name: 'core-sw-02',
    serial_number: 'SN-B',
    stack_id: 'stack-1',
    stack_name: 'Стек ядра',
    stack_position: 2,
    siem_enabled: false,
    manufacturer_id: 'mf-1',
    model_id: 'dm-1',
    building_id: 'b-1',
    room_id: 'r-1',
    management_ips: '10.0.0.2',
  }),
  device({
    id: 'd-1',
    system_name: 'core-sw-01',
    serial_number: 'SN-A',
    stack_id: 'stack-1',
    stack_name: 'Стек ядра',
    stack_position: 1,
    siem_enabled: true,
    manufacturer_id: 'mf-1',
    model_id: 'dm-1',
    building_id: 'b-1',
    room_id: 'r-1',
    management_ips: '10.0.0.1',
  }),
]

async function mountView(stacks: DeviceStack[], devices: Device[] = [], calls: string[] = [], vlans: FakeServer['vlans'] = {}) {
  const server: FakeServer = { stacks, vlans }
  stubServer(server, calls)
  seedDevices(devices)
  const wrapper = mount(DeviceStacksView)
  await flushPromises()
  return { wrapper, server }
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('DeviceStacksView.vue', () => {
  it('показывает подсказку, если стеков ещё нет', async () => {
    const { wrapper } = await mountView([])

    expect(wrapper.text()).toContain('Стеки устройств не созданы')
  })

  it('строка стека: название, описание, число устройств, модель, IP, расположение', async () => {
    const { wrapper } = await mountView([CORE, ACCESS], coreMembers())

    const rows = wrapper.findAll('.stack-row')
    expect(rows).toHaveLength(2)
    // «Стек доступа» идёт раньше «Стека ядра» (сортировка по названию)
    expect(rows[0].text()).toContain('Стек доступа')
    expect(rows[0].text()).toContain('Пусто')
    const core = rows[1].text()
    expect(core).toContain('Стек ядра')
    expect(core).toContain('2 коммутатора Cisco')
    expect(core).toContain('2 устройства')
    expect(core).toContain('Cisco · C9300')
    expect(core).toContain('10.0.0.1; 10.0.0.2')
    expect(core).toContain('Главный корпус · Серверная')
  })

  it('SIEM стека: у части участников — «1 из 2», у стека без устройств — прочерк', async () => {
    const { wrapper } = await mountView([CORE, ACCESS], coreMembers())

    const rows = wrapper.findAll('.stack-row')
    expect(rows[1].find('.status').text()).toBe('1 из 2')
    expect(rows[0].find('.status').exists()).toBe(false)
  })

  it('карточки сводки: стеки, устройства в стеках, пустые стеки, стеки без полного SIEM', async () => {
    const { wrapper } = await mountView([CORE, ACCESS], coreMembers())

    const stat = (label: string) =>
      wrapper
        .findAll('.stat-card')
        .find((c) => c.text().includes(label))!
        .find('.num')
        .text()
    expect(stat('Стеков')).toBe('2')
    expect(stat('Устройств в стеках')).toBe('2')
    expect(stat('Пустых стеков')).toBe('1')
    expect(stat('без полного SIEM')).toBe('1')
  })

  it('строка раскрывается в состав стека: участники по позиции, со всеми реквизитами; повторный клик сворачивает', async () => {
    const { wrapper } = await mountView([CORE], coreMembers())
    expect(wrapper.find('.members-table').exists()).toBe(false)

    await wrapper.find('.stack-toggle').trigger('click')

    const members = wrapper.findAll('.member-row')
    expect(members.map((m) => m.findAll('td')[1].text())).toEqual(['core-sw-01', 'core-sw-02'])
    expect(members[0].text()).toContain('SN-A')
    expect(members[0].text()).toContain('10.0.0.1')
    expect(wrapper.find('.stack-toggle').attributes('aria-expanded')).toBe('true')

    await wrapper.find('.stack-toggle').trigger('click')
    expect(wrapper.find('.members-table').exists()).toBe(false)
  })

  it('«Развернуть все» раскрывает все найденные стеки, повторно — сворачивает', async () => {
    const { wrapper } = await mountView([CORE, ACCESS], coreMembers())
    const toggleAll = () => wrapper.findAll('.filter-actions button').find((b) => /развернуть все|свернуть все/i.test(b.text()))!

    await toggleAll().trigger('click')
    expect(wrapper.findAll('.members-row')).toHaveLength(2)
    expect(toggleAll().text()).toBe('Свернуть все')

    await toggleAll().trigger('click')
    expect(wrapper.findAll('.members-row')).toHaveLength(0)
  })

  it('раскрытый пустой стек подсказывает, как добавить устройства', async () => {
    const { wrapper } = await mountView([ACCESS])

    await wrapper.find('.stack-toggle').trigger('click')

    expect(wrapper.find('.members-row').text()).toContain('В стеке пока нет устройств')
  })

  describe('поиск', () => {
    const searchInput = (wrapper: Awaited<ReturnType<typeof mountView>>['wrapper']) => wrapper.find('.search-box input')

    it('находит стек по названию, без учёта регистра', async () => {
      const { wrapper } = await mountView([CORE, ACCESS], coreMembers())

      await searchInput(wrapper).setValue('ДОСТУПА')

      const rows = wrapper.findAll('.stack-row')
      expect(rows).toHaveLength(1)
      expect(rows[0].text()).toContain('Стек доступа')
      expect(wrapper.find('.found-count').text()).toBe('Найдено 1 из 2')
    })

    it('находит стек по серийному номеру и IP его участника и по описанию', async () => {
      const { wrapper } = await mountView([CORE, ACCESS], coreMembers())

      await searchInput(wrapper).setValue('SN-B')
      expect(wrapper.findAll('.stack-row')).toHaveLength(1)
      expect(wrapper.find('.stack-row').text()).toContain('Стек ядра')

      await searchInput(wrapper).setValue('10.0.0.1')
      expect(wrapper.find('.stack-row').text()).toContain('Стек ядра')

      await searchInput(wrapper).setValue('коммутатора cisco')
      expect(wrapper.find('.stack-row').text()).toContain('Стек ядра')
    })

    it('несколько слов запроса сужают выбор: нужны все', async () => {
      const { wrapper } = await mountView([CORE, ACCESS], coreMembers())

      await searchInput(wrapper).setValue('ядра доступа')

      expect(wrapper.findAll('.stack-row')).toHaveLength(0)
    })

    it('если ничего не найдено — сообщение и «Сбросить фильтры», которые возвращают все стеки', async () => {
      const { wrapper } = await mountView([CORE, ACCESS], coreMembers())

      await searchInput(wrapper).setValue('нет такого')
      expect(wrapper.findAll('.stack-row')).toHaveLength(0)
      expect(wrapper.find('.empty-row').exists()).toBe(true)
      expect(wrapper.text()).not.toContain('Стеки устройств не созданы')

      await wrapper.find('.empty-row button').trigger('click')
      expect(wrapper.findAll('.stack-row')).toHaveLength(2)
      expect((searchInput(wrapper).element as HTMLInputElement).value).toBe('')
    })
  })

  it('пагинация: стеки режутся на страницы, поиск возвращает на первую', async () => {
    const many = Array.from({ length: 12 }, (_, i): DeviceStack => ({ id: `s-${i + 1}`, name: `Стек ${i + 1}`, description: null }))
    const { wrapper } = await mountView(many)

    expect(wrapper.find('.paged-foot .range').text()).toBe('Показано 1–10 из 12')
    expect(wrapper.findAll('.stack-row')).toHaveLength(10)

    await wrapper.find('.pager button[aria-label="Страница 2"]').trigger('click')
    expect(wrapper.find('.paged-foot .range').text()).toBe('Показано 11–12 из 12')

    await wrapper.find('.search-box input').setValue('Стек 1')
    expect(wrapper.find('.paged-foot .range').text()).toBe('Показано 1–4 из 4') // «Стек 1», «Стек 10», «Стек 11», «Стек 12»
  })

  describe('актуальность данных без перезагрузки страницы', () => {
    it('при открытии экрана стор стеков читается заново, даже если он уже был загружен', async () => {
      // Стор уже загружен прежним визитом и не знает про стек, созданный потом в «Инвентаризации устройств».
      const stale = useDeviceStacksStore()
      stale.all = [ACCESS]
      stale.loaded = true

      const { wrapper } = await mountView([ACCESS, CORE])

      expect(wrapper.findAll('.stack-row').map((r) => r.find('b').text())).toEqual(['Стек доступа', 'Стек ядра'])
    })

    it('«Обновить» перечитывает стеки и устройства', async () => {
      const calls: string[] = []
      const { wrapper, server } = await mountView([ACCESS], [], calls)
      server.stacks = [ACCESS, CORE]
      calls.length = 0

      await wrapper
        .findAll('.filter-actions button')
        .find((b) => b.text() === 'Обновить')!
        .trigger('click')
      await flushPromises()

      expect(calls.some((c) => c.startsWith('GET') && c.includes('/resources/device-stacks'))).toBe(true)
      expect(calls.some((c) => c.startsWith('GET') && c.includes('/devices'))).toBe(true)
      expect(wrapper.findAll('.stack-row')).toHaveLength(2)
    })

    it('закрытие окна стека крестиком перечитывает стеки и устройства (состав мог измениться в окне)', async () => {
      const calls: string[] = []
      const { wrapper } = await mountView([CORE], coreMembers(), calls)
      await wrapper.find('.stack-row .btn-secondary').trigger('click')
      await flushPromises()
      calls.length = 0

      await wrapper.find('.modal .icon-btn[aria-label="Закрыть"]').trigger('click')
      await flushPromises()

      expect(calls.some((c) => c.startsWith('GET') && c.includes('/resources/device-stacks'))).toBe(true)
      expect(calls.some((c) => c.startsWith('GET') && c.includes('/devices'))).toBe(true)
    })
  })

  describe('общие VLAN стека (подгружаются при раскрытии строки)', () => {
    it('до раскрытия строки запросов общих VLAN нет; при раскрытии показываются VLAN, адрес и состояние применения', async () => {
      const calls: string[] = []
      const { wrapper } = await mountView([CORE], coreMembers(), calls, { 'stack-1': [sharedVlan()] })
      expect(vlanCalls(calls)).toEqual([])

      await wrapper.find('.stack-toggle').trigger('click')
      await flushPromises()

      expect(vlanCalls(calls)).toHaveLength(1)
      const block = wrapper.find('.stack-vlans').text()
      expect(block).toContain('VLAN 10')
      expect(block).toContain('Servers')
      expect(block).toContain('10.0.10.1/24, «Управление»')
      expect(block).toContain('Применено ко всем (2)')
    })

    it('настройка применена не ко всем участникам — состояние-предупреждение с числами', async () => {
      const { wrapper } = await mountView([CORE], coreMembers(), [], {
        'stack-1': [sharedVlan({ is_uniform: false, assigned_count: 1, is_management: false })],
      })

      await wrapper.find('.stack-toggle').trigger('click')
      await flushPromises()

      const status = wrapper.find('.stack-vlan-item .status')
      expect(status.text()).toBe('VLAN назначен не у всех: 1 из 2')
      expect(status.classes()).toContain('off')
    })

    it('свернул и раскрыл снова — повторного запроса нет', async () => {
      const calls: string[] = []
      const { wrapper } = await mountView([CORE], coreMembers(), calls, { 'stack-1': [sharedVlan()] })

      await wrapper.find('.stack-toggle').trigger('click')
      await flushPromises()
      await wrapper.find('.stack-toggle').trigger('click')
      await wrapper.find('.stack-toggle').trigger('click')
      await flushPromises()

      expect(vlanCalls(calls)).toHaveLength(1)
      expect(wrapper.find('.stack-vlans').text()).toContain('VLAN 10')
    })

    it('у стека нет общих VLAN — подсказка, где их настроить', async () => {
      const { wrapper } = await mountView([CORE], coreMembers())

      await wrapper.find('.stack-toggle').trigger('click')
      await flushPromises()

      expect(wrapper.find('.stack-vlans').text()).toContain('Общие VLAN не заданы')
    })

    it('ошибка загрузки показывается в блоке, а «Повторить» запрашивает данные снова', async () => {
      const server = { 'stack-1': 'error' as const }
      const calls: string[] = []
      const { wrapper } = await mountView([CORE], coreMembers(), calls, server)
      await wrapper.find('.stack-toggle').trigger('click')
      await flushPromises()
      expect(wrapper.find('.stack-vlans').text()).toContain('Не удалось загрузить общие VLAN')

      // сервер «починился»: тот же объект, который читает заглушка
      ;(server as Record<string, unknown>)['stack-1'] = [sharedVlan()]
      await wrapper.find('.stack-vlans .btn').trigger('click')
      await flushPromises()

      expect(wrapper.find('.stack-vlans').text()).toContain('VLAN 10')
      expect(vlanCalls(calls)).toHaveLength(2)
    })

    it('«Развернуть все» запрашивает общие VLAN только стеков текущей страницы', async () => {
      const many = Array.from({ length: 12 }, (_, i): DeviceStack => ({ id: `s-${i + 1}`, name: `Стек ${i + 1}`, description: null }))
      const calls: string[] = []
      const { wrapper } = await mountView(many, [], calls)

      await wrapper
        .findAll('.filter-actions button')
        .find((b) => b.text() === 'Развернуть все')!
        .trigger('click')
      await flushPromises()
      expect(vlanCalls(calls)).toHaveLength(10)

      // на вторую страницу — раскрытые там строки догружаются
      await wrapper.find('.pager button[aria-label="Страница 2"]').trigger('click')
      await flushPromises()
      expect(vlanCalls(calls)).toHaveLength(12)
    })

    it('«Обновить» и закрытие окна стека сбрасывают кэш — общие VLAN раскрытых строк запрашиваются заново', async () => {
      const calls: string[] = []
      const { wrapper } = await mountView([CORE], coreMembers(), calls, { 'stack-1': [sharedVlan()] })
      await wrapper.find('.stack-toggle').trigger('click')
      await flushPromises()
      expect(vlanCalls(calls)).toHaveLength(1)

      await wrapper
        .findAll('.filter-actions button')
        .find((b) => b.text() === 'Обновить')!
        .trigger('click')
      await flushPromises()
      expect(vlanCalls(calls)).toHaveLength(2)

      await wrapper.find('.stack-row .btn-secondary').trigger('click')
      await flushPromises()
      // Редактор общих VLAN в самом окне стека тоже читает /vlans — к проверке это не относится: считаем запросы после закрытия.
      calls.length = 0
      await wrapper.find('.modal .icon-btn[aria-label="Закрыть"]').trigger('click')
      await flushPromises()
      expect(vlanCalls(calls)).toHaveLength(1)
    })
  })

  it('кнопка «Добавить стек» открывает форму создания', async () => {
    const { wrapper } = await mountView([])

    await wrapper
      .findAll('.filter-actions button')
      .find((b) => b.text().includes('Добавить стек'))!
      .trigger('click')

    expect(wrapper.find('.modal-head h2').text()).toBe('Добавить стек устройств')
  })

  it('роль без права записи не видит «Добавить стек» и удаление, но открыть стек может', async () => {
    // Аутентификация включена, вошёл пользователь с ролью viewer — писать он не может (auth.canWrite = false).
    const auth = useAuthStore()
    auth.enabled = true
    auth.user = {
      id: 'u1',
      username: 'viewer',
      role: 'viewer',
      is_active: true,
      last_login_at: null,
      locked: false,
      created_at: '2026-01-01T00:00:00',
    } as never
    const { wrapper } = await mountView([CORE], coreMembers())

    expect(wrapper.findAll('.filter-actions button').some((b) => b.text().includes('Добавить стек'))).toBe(false)
    expect(wrapper.find('.icon-btn.danger').exists()).toBe(false)
    expect(wrapper.find('.stack-row .btn-secondary').exists()).toBe(true)
  })

  it('кнопка «Открыть» открывает форму редактирования выбранного стека', async () => {
    const { wrapper } = await mountView([CORE])

    await wrapper.find('.stack-row .btn-secondary').trigger('click')
    await flushPromises()

    expect(wrapper.find('.modal-head h2').text()).toBe('Редактировать стек устройств')
  })

  it('удаляет стек после подтверждения', async () => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    )
    const calls: string[] = []
    const { wrapper } = await mountView([CORE], [], calls)

    await wrapper.find('.stack-row .icon-btn.danger').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.startsWith('DELETE') && c.includes('/resources/device-stacks/stack-1'))).toBe(true)
  })

  it('отмена подтверждения не отправляет запрос на удаление', async () => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    )
    const calls: string[] = []
    const { wrapper } = await mountView([CORE], [], calls)

    await wrapper.find('.stack-row .icon-btn.danger').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.startsWith('DELETE'))).toBe(false)
  })
})
