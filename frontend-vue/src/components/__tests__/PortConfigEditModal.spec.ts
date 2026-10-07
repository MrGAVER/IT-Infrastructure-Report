import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PortConfigEditModal from '../PortConfigEditModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useVLANsStore } from '../../stores/vlans'
import { useToast } from '../../composables/useToast'
import type { Connection, VLANDefinition } from '../../api/types'
import { groupChange, makePlan, portChange } from '../../utils/__tests__/cascadePlanFixture'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

// Окно телепортируется в document.body — ищем там (тот же приём, что в DevicePortsModal.spec.ts).
function body(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

function definition(number: number): VLANDefinition {
  return { id: `v${number}`, vlan_id: number, name: `net${number}`, description: '', domain_id: null, domain_name: '', devices: [] }
}

function connection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: 'c-1',
    source_interface_id: 'if-1',
    destination_interface_id: 'if-2',
    connection_type_id: 'ct-1',
    is_active: true,
    description: null,
    source_device_name: 'sw-01',
    source_interface_name: 'Gi0/1',
    destination_device_name: 'sw-02',
    destination_interface_name: 'Gi0/2',
    connection_type_name: 'Оптика',
    source_port_role: 'data',
    destination_port_role: 'data',
    source_vlan_mode: 'trunk',
    destination_vlan_mode: 'trunk',
    source_vlans: [10, 20],
    destination_vlans: [10, 20],
    port_config_diff: [],
    port_config_status: 'ok',
    ...overrides,
  }
}

interface Call { url: string; method: string; body?: Record<string, unknown> }
interface Server {
  iface: Record<string, unknown>
  linkedVlanIds: string[]
  groups: Array<Record<string, unknown>>
  plan: ReturnType<typeof makePlan>
  putResponse: () => Response
}

let calls: Call[]
let server: Server

function resetServer(): Server {
  return {
    iface: { id: 'if-1', name: 'Gi0/1', physical_device_id: 'dev-1', is_management: false, is_data_transfer: true, vlan_mode: 'trunk', group_id: null },
    linkedVlanIds: ['v10', 'v20'],
    groups: [],
    plan: makePlan({ target_mode: 'access', start_interface_id: 'if-1', ports: [portChange({ id: 'if-2', device_id: 'dev-2' })] }),
    putResponse: () => jsonResponse(server.iface),
  }
}

const path = (url: string) => url.replace(/^.*\/api\/v1/, '').split('?')[0]

function stubApi() {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
      const p = path(url)
      if (method === 'GET' && p === '/resources/interfaces/if-1') return jsonResponse(server.iface)
      if (method === 'GET' && p === '/resources/devices/dev-1') return jsonResponse({ id: 'dev-1', device_type_id: 'dt-1', name: 'sw-01' })
      if (method === 'GET' && p === '/resources/interface-vlans') {
        const items = server.linkedVlanIds.map((vlan_id) => ({ id: `l-${vlan_id}`, interface_id: 'if-1', vlan_id, mode: server.iface.vlan_mode }))
        return jsonResponse({ items, total: items.length, offset: 0, limit: 1000 })
      }
      if (method === 'GET' && p === '/resources/device-type-vlans') {
        const items = ['v10', 'v20', 'v30'].map((vlan_id) => ({ id: `t-${vlan_id}`, device_type_id: 'dt-1', vlan_id }))
        return jsonResponse({ items, total: items.length, offset: 0, limit: 1000 })
      }
      if (method === 'GET' && p === '/devices/dev-1/interface-groups') return jsonResponse({ items: server.groups })
      if (method === 'PUT' && p === '/interfaces/if-1/port-config') return server.putResponse()
      if (method === 'POST' && p === '/interfaces/if-1/vlan-mode-cascade/preview') return jsonResponse(server.plan)
      if (method === 'POST' && p === '/interfaces/if-1/vlan-mode-cascade') {
        return jsonResponse({ plan: server.plan, applied: { ports: server.plan.totals.ports, groups: server.plan.totals.groups, devices: server.plan.totals.devices }, interfaces: [] })
      }
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000, summary: { total: 0, active: 0, inactive: 0, mismatch: 0, approved: 0 } })
    }),
  )
}

const callsTo = (method: string, p: string) => calls.filter((c) => c.method === method && path(c.url) === p)
const putCalls = () => callsTo('PUT', '/interfaces/if-1/port-config')

async function openModal(conn: Connection = connection(), side: 'source' | 'destination' = 'source') {
  const wrapper = mount(PortConfigEditModal, { props: { connection: conn, side } })
  await flushPromises()
  return wrapper
}

const checkbox = (id: string) => body().find<HTMLInputElement>(`[data-vlan="${id}"]`)
const checkedVlans = () => body().findAll<HTMLInputElement>('[data-vlan]').filter((i) => i.element.checked).map((i) => i.attributes('data-vlan'))
const saveButton = () => body().find<HTMLButtonElement>('[data-action="save"]')

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  useToast().toasts.splice(0)
  server = resetServer()
  // Справочник VLAN уже «загружен»: окно не должно ходить за /vlan-dashboard.
  useVLANsStore().$patch({ groups: [10, 20, 30].map((n) => ({ vlan_id: n, definitions: [definition(n)] })), loaded: true })
  useCatalogsStore().$patch({ loaded: true })
  stubApi()
})

describe('PortConfigEditModal.vue', () => {
  it('грузит текущее состояние порта с сервера (а не из строки таблицы) и показывает VLAN чекбоксами', async () => {
    await openModal()

    expect(body().text()).toContain('Порт «Gi0/1» · sw-01')
    expect(body().find<HTMLSelectElement>('[data-field="role"]').element.value).toBe('data')
    expect(body().find('[data-field="mode-trunk"]').attributes('aria-pressed')).toBe('true')
    expect(body().findAll('[data-vlan]')).toHaveLength(3)
    expect(checkbox('v10').attributes('type')).toBe('checkbox')
    expect(checkedVlans()).toEqual(['v10', 'v20'])
    expect(body().find('[data-count]').text()).toBe('Выбрано: 2 из 3')
    expect(body().find('[data-compare]').text()).toContain('совпадёт с соседним портом')
    expect(saveButton().attributes('disabled')).toBeDefined() // менять нечего
  })

  it('смена роли отправляет в PUT port-config только роль и режим-проверку, обновляет кэш и таблицу', async () => {
    server.putResponse = () => jsonResponse({ ...server.iface, is_management: true, is_data_transfer: true })
    const wrapper = await openModal()

    await body().find('[data-field="role"]').setValue('management_data')
    await saveButton().trigger('click')
    await flushPromises()

    expect(putCalls()).toHaveLength(1)
    expect(putCalls()[0].body).toEqual({ role: 'management_data', mode: 'trunk' }) // VLAN не менялись — не отправляем
    expect(callsTo('POST', '/interfaces/if-1/vlan-mode-cascade/preview')).toHaveLength(0)
    expect(calls.some((c) => c.method === 'GET' && /\/api\/v1\/connections\?/.test(c.url))).toBe(true) // дашборд перечитан
    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(useToast().toasts.some((t) => t.type === 'success')).toBe(true)
  })

  it('trunk: набор VLAN отправляется целиком, а расхождение с соседом показывается до сохранения', async () => {
    await openModal()

    await checkbox('v30').setValue(true)
    await checkbox('v10').setValue(false)

    expect(body().find('[data-compare]').text()).toContain('будет отличаться')
    expect(body().find('[data-compare]').text()).toContain('VLAN')

    await saveButton().trigger('click')
    await flushPromises()

    expect(putCalls()[0].body).toEqual({ vlan_ids: ['v20', 'v30'], mode: 'trunk' })
  })

  it('«Все VLAN» и «Снять все» работают с полным набором доступных устройству VLAN', async () => {
    await openModal()

    await body().find('[data-action="select-all"]').trigger('click')
    expect(checkedVlans()).toEqual(['v10', 'v20', 'v30'])

    await body().find('[data-action="clear"]').trigger('click')
    expect(checkedVlans()).toEqual([])
    expect(body().find('[data-count]').text()).toBe('Выбрано: 0 из 3')
  })

  it('«Задать как у соседа» переносит роль, режим и VLAN по номеру; VLAN, которых нет у устройства, не назначает и сообщает об этом', async () => {
    server.iface = { ...server.iface, is_data_transfer: false, is_management: true }
    server.linkedVlanIds = []
    await openModal(connection({ destination_port_role: 'data', destination_vlan_mode: 'trunk', destination_vlans: [10, 20, 99] }))

    await body().find('[data-action="copy-neighbor"]').trigger('click')

    expect(body().find<HTMLSelectElement>('[data-field="role"]').element.value).toBe('data')
    expect(checkedVlans()).toEqual(['v10', 'v20'])
    expect(body().find('[data-notice]').text()).toContain('99')
  })

  it('access: один VLAN радиокнопкой; при переходе trunk → access остаётся VLAN с наименьшим номером', async () => {
    await openModal()

    await body().find('[data-field="mode-access"]').trigger('click')

    expect(body().find('[data-hint="cascade"]').exists()).toBe(true)
    expect(checkbox('v10').attributes('type')).toBe('radio')
    expect(checkedVlans()).toEqual(['v10'])
    expect(body().find('[data-notice]').text()).toContain('наименьшим номером')

    await checkbox('v30').setValue(true) // в access выбор заменяет, а не дополняет
    expect(checkedVlans()).toEqual(['v30'])
    expect(saveButton().text()).toContain('Далее')
  })

  it('смена режима идёт каскадом: предпросмотр → применение → затем роль и VLAN одним PUT уже в новом режиме', async () => {
    await openModal()

    await body().find('[data-field="mode-access"]').trigger('click')
    await body().find('[data-field="role"]').setValue('management')
    await saveButton().trigger('click')
    await flushPromises()

    // Тривиальный план (один порт соседа) применяется сразу, без окна подтверждения.
    expect(calls.findIndex((c) => path(c.url) === '/interfaces/if-1/vlan-mode-cascade/preview')).toBeGreaterThan(-1)
    const apply = callsTo('POST', '/interfaces/if-1/vlan-mode-cascade')
    expect(apply).toHaveLength(1)
    expect(apply[0].body).toMatchObject({ mode: 'access', plan_hash: 'hash-1', confirm: true })
    expect(putCalls()).toHaveLength(1)
    expect(putCalls()[0].body).toEqual({ role: 'management', vlan_ids: ['v10'], mode: 'access' })
    expect(calls.indexOf(putCalls()[0])).toBeGreaterThan(calls.indexOf(apply[0])) // сначала режим, потом остальное
  })

  it('нетривиальный план каскада ждёт подтверждения в окне; пока не подтверждён, ничего не записывается', async () => {
    server.plan = makePlan({
      target_mode: 'access',
      start_interface_id: 'if-1',
      groups: [groupChange()],
      totals: { ports: 3, devices: 1, groups: 1, deferred_ports: 0, immediate_ports: 3, immediate_devices: 1, dropped_vlans: 0 },
    })
    const wrapper = await openModal()

    await body().find('[data-field="mode-access"]').trigger('click')
    await saveButton().trigger('click')
    await flushPromises()

    expect(body().text()).toContain('Сменить режим порта на')
    expect(callsTo('POST', '/interfaces/if-1/vlan-mode-cascade')).toHaveLength(0)
    expect(putCalls()).toHaveLength(0)

    await body().find<HTMLInputElement>('.cascade-ack input').setValue(true)
    await body().find('.cascade-actions .btn-primary').trigger('click')
    await flushPromises()

    expect(callsTo('POST', '/interfaces/if-1/vlan-mode-cascade')).toHaveLength(1)
    expect(putCalls()).toHaveLength(1)
    expect(putCalls()[0].body).toEqual({ vlan_ids: ['v10'], mode: 'access' })
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })

  it('отмена в окне каскада не пишет ничего и оставляет окно правки открытым', async () => {
    server.plan = makePlan({
      target_mode: 'access',
      start_interface_id: 'if-1',
      groups: [groupChange()],
      totals: { ports: 3, devices: 1, groups: 1, deferred_ports: 0, immediate_ports: 3, immediate_devices: 1, dropped_vlans: 0 },
    })
    const wrapper = await openModal()

    await body().find('[data-field="mode-access"]').trigger('click')
    await saveButton().trigger('click')
    await flushPromises()
    await body().find('.cascade-actions .btn-secondary').trigger('click')
    await flushPromises()

    expect(body().text()).not.toContain('Сменить режим порта на')
    expect(body().find('[data-modal="port-config-edit"]').exists()).toBe(true)
    expect(callsTo('POST', '/interfaces/if-1/vlan-mode-cascade')).toHaveLength(0)
    expect(putCalls()).toHaveLength(0)
    expect(wrapper.emitted('saved')).toBeUndefined()
  })

  it('если после каскада сохранить роль и VLAN не удалось, говорит, что режим уже изменён, и перечитывает порт, не теряя ввод', async () => {
    server.putResponse = () => jsonResponse({ detail: 'Один или несколько VLAN не разрешены для типа данного устройства' }, 422)
    const wrapper = await openModal()

    await body().find('[data-field="mode-access"]').trigger('click')
    await body().find('[data-field="role"]').setValue('management')
    await saveButton().trigger('click')
    await flushPromises()

    expect(body().find('[data-error]').text()).toContain('Режим порта изменён, но роль и VLAN сохранить не удалось')
    expect(body().find('[data-error]').text()).toContain('не разрешены')
    expect(wrapper.emitted('saved')).toBeUndefined()
    expect(body().find<HTMLSelectElement>('[data-field="role"]').element.value).toBe('management') // ввод сохранён
    expect(callsTo('GET', '/resources/interfaces/if-1').length).toBeGreaterThanOrEqual(2) // состояние порта перечитано
  })

  it('ошибка обычного сохранения показывается в окне, окно не закрывается', async () => {
    server.putResponse = () => jsonResponse({ detail: 'Порт входит в группу «Магистрали», которая задаёт режим и VLAN, — измените группу' }, 409)
    const wrapper = await openModal()

    await body().find('[data-field="role"]').setValue('none')
    await saveButton().trigger('click')
    await flushPromises()

    expect(body().find('[data-error]').text()).toContain('Магистрали')
    expect(body().find('[data-error]').text()).not.toContain('Режим порта изменён')
    expect(wrapper.emitted('saved')).toBeUndefined()
  })

  it('порт в группе, задающей режим и VLAN: набор VLAN не правится и не отправляется, роль менять можно', async () => {
    server.iface = { ...server.iface, group_id: 'g-1' }
    server.groups = [{ id: 'g-1', physical_device_id: 'dev-1', name: 'Магистрали', vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], ip_address: null, prefix_length: null, manage_open_ports: false, open_ports: [] }]
    const wrapper = await openModal()

    expect(body().find('[data-hint="group-locked"]').text()).toContain('Магистрали')
    expect(body().find('[data-vlan-list]').exists()).toBe(false)

    await body().find('[data-field="role"]').setValue('management')
    await saveButton().trigger('click')
    await flushPromises()

    expect(putCalls()[0].body).toEqual({ role: 'management', mode: 'trunk' })
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })

  it('«Открыть порты устройства» для порта в группе просит родителя открыть окно портов', async () => {
    server.iface = { ...server.iface, group_id: 'g-1' }
    server.groups = [{ id: 'g-1', physical_device_id: 'dev-1', name: 'Магистрали', vlan_mode: 'trunk', vlan_ids: [], ip_address: null, prefix_length: null, manage_open_ports: false, open_ports: [] }]
    const wrapper = await openModal()

    await body().find('[data-action="manage-group"]').trigger('click')

    expect(wrapper.emitted('manage-ports')).toEqual([[{ interfaceId: 'if-1', deviceLabel: 'sw-01' }]])
  })

  it('у устройства нет доступных VLAN — подсказка вместо списка', async () => {
    useVLANsStore().$patch({ groups: [], loaded: true })
    await openModal()

    expect(body().find('[data-hint="no-vlans"]').exists()).toBe(true)
    expect(body().find('[data-vlan-list]').exists()).toBe(false)
  })

  it('для стороны destination редактируется порт назначения, а сосед — источник', async () => {
    server.iface = { ...server.iface, id: 'if-2', name: 'Gi0/2' }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        const p = path(url)
        if (p === '/resources/interfaces/if-2') return jsonResponse(server.iface)
        if (p === '/resources/devices/dev-1') return jsonResponse({ id: 'dev-1', device_type_id: 'dt-1' })
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    await openModal(connection({ source_port_role: 'management', source_vlan_mode: 'access', source_vlans: [10] }), 'destination')

    expect(body().text()).toContain('Порт «Gi0/2» · sw-02')
    expect(body().find('[data-neighbor]').text()).toContain('«Gi0/1» (sw-01)')
    expect(body().find('[data-neighbor]').text()).toContain('Управление активами')
    expect(body().find('[data-neighbor]').text()).toContain('режим access')
  })

  it('ошибка загрузки порта показывается в окне, сохранить нельзя', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Порт не найден' }, 404)))

    await openModal()

    expect(body().find('[data-error]').text()).toContain('Порт не найден')
    expect(saveButton().attributes('disabled')).toBeDefined()
  })
})
