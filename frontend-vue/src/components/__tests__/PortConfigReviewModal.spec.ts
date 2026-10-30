import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PortConfigReviewModal from '../PortConfigReviewModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useToast } from '../../composables/useToast'
import type { Connection } from '../../api/types'
import type { VlanModeCascadePlan } from '../../api/vlanModeCascade'
import { groupChange, makePlan, portChange } from '../../utils/__tests__/cascadePlanFixture'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function connection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: 'c-1',
    source_interface_id: 'if-srv',
    destination_interface_id: 'if-sw',
    connection_type_id: 'ct-1',
    is_active: true,
    description: null,
    source_device_name: 'srv-01',
    source_interface_name: 'idrac',
    destination_device_name: 'sw-01',
    destination_interface_name: 'Gi0/5',
    connection_type_name: 'Медь',
    source_port_role: 'management',
    destination_port_role: 'data',
    source_vlan_mode: 'trunk',
    destination_vlan_mode: 'trunk',
    source_vlans: [],
    destination_vlans: [],
    port_config_diff: ['role'],
    port_config_status: 'mismatch',
    ...overrides,
  }
}

interface Call {
  url: string
  method: string
  body?: Record<string, unknown>
}
let calls: Call[]

function stubApi(handler: (call: Call) => Response | undefined = () => undefined) {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const call: Call = { url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body as string) : undefined }
      calls.push(call)
      return (
        handler(call) ?? jsonResponse({ items: [], total: 0, offset: 0, limit: 1000, summary: { total: 0, active: 0, inactive: 0, mismatch: 0, approved: 0 } })
      )
    }),
  )
}

function mountModal(conn: Connection) {
  return mount(PortConfigReviewModal, { props: { connection: conn } })
}

// Страница дашборда (/api/v1/connections?…) и общий кэш (/api/v1/resources/connections?…) — разные запросы.
const pageRequests = () => calls.filter((c) => c.method === 'GET' && /\/api\/v1\/connections\?/.test(c.url))
const cacheRequests = () => calls.filter((c) => c.method === 'GET' && c.url.includes('/resources/connections'))

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  useToast().toasts.splice(0)
  stubApi()
})

describe('PortConfigReviewModal.vue', () => {
  it('показывает обе стороны подключения с ролями портов и предупреждением о расхождении', () => {
    const wrapper = mountModal(connection())

    expect(wrapper.text()).toContain('srv-01')
    expect(wrapper.text()).toContain('idrac')
    expect(wrapper.find('[data-side="source"]').text()).toBe('Управление активами')
    expect(wrapper.find('[data-side="destination"]').text()).toBe('Передача данных')
    expect(wrapper.find('.status.warn').exists()).toBe(true)
  })

  it('при расхождении предлагает одобрить или выровнять любой из портов, но не отзывать', () => {
    const wrapper = mountModal(connection())

    expect(wrapper.find('[data-action="approve"]').exists()).toBe(true)
    expect(wrapper.find('[data-action="keep-source"]').text()).toContain('Порту «Gi0/5» задать роль как у «idrac»')
    expect(wrapper.find('[data-action="keep-destination"]').text()).toContain('Порту «idrac» задать роль как у «Gi0/5»')
    expect(wrapper.find('[data-action="revoke"]').exists()).toBe(false)
  })

  it('«Одобрить» отправляет id подключения, перечитывает страницу и кэш и закрывает модалку', async () => {
    stubApi((call) =>
      call.url.endsWith('/connections/port-config/approve')
        ? jsonResponse({ items: [connection({ port_config_status: 'approved' })], skipped_ids: [], approved_count: 1 })
        : undefined,
    )
    const wrapper = mountModal(connection())

    await wrapper.find('[data-action="approve"]').trigger('click')
    await flushPromises()

    expect(calls.find((c) => c.url.endsWith('/connections/port-config/approve'))!.body).toEqual({ connection_ids: ['c-1'] })
    expect(pageRequests()).toHaveLength(1)
    expect(cacheRequests()).toHaveLength(1)
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(useToast().toasts.some((t) => t.type === 'success')).toBe(true)
  })

  it('для одобренного расхождения показывает «Отозвать одобрение»; после отзыва снова предлагает одобрить (даже если строки уже нет на странице)', async () => {
    stubApi((call) => (call.method === 'DELETE' ? jsonResponse(connection({ port_config_status: 'mismatch' })) : undefined))
    const wrapper = mountModal(connection({ port_config_status: 'approved' }))

    expect(wrapper.find('.status.approved').exists()).toBe(true)
    expect(wrapper.find('[data-action="approve"]').exists()).toBe(false)

    await wrapper.find('[data-action="revoke"]').trigger('click')
    await flushPromises()

    expect(calls.find((c) => c.method === 'DELETE')!.url).toContain('/connections/c-1/port-config/approval')
    // Страница после отзыва перечитана пустой (строка не подходит под фильтр), но окно показывает
    // актуальную запись из ответа сервера, а не стёртую строку.
    expect(pageRequests()).toHaveLength(1)
    expect(wrapper.emitted('close')).toBeUndefined() // модалка остаётся открытой, статус обновился
    expect(wrapper.find('[data-action="approve"]').exists()).toBe(true)
  })

  it('«Порту назначения задать роль как у источника» меняет порт назначения, обновляет кэш и перечитывает подключения', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = [{ id: 'if-sw', name: 'Gi0/5', physical_device_id: 'dev-sw', is_management: false, is_data_transfer: true }]
    stubApi((call) => {
      if (call.method === 'PUT' && call.url.includes('/interfaces/if-sw/port-role')) {
        return jsonResponse({ id: 'if-sw', name: 'Gi0/5', physical_device_id: 'dev-sw', is_management: true, is_data_transfer: false })
      }
      return undefined
    })
    const wrapper = mountModal(connection())

    await wrapper.find('[data-action="keep-source"]').trigger('click')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT')!
    expect(put.body).toEqual({ is_management: true, is_data_transfer: false })
    expect(catalogs.items['interfaces'][0]).toMatchObject({ is_management: true, is_data_transfer: false })
    expect(pageRequests()).toHaveLength(1)
    expect(cacheRequests()).toHaveLength(1)
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('«Порту источника задать роль как у назначения» меняет порт источника', async () => {
    stubApi((call) =>
      call.method === 'PUT'
        ? jsonResponse({ id: 'if-srv', name: 'idrac', physical_device_id: 'dev-srv', is_management: false, is_data_transfer: true })
        : undefined,
    )
    const wrapper = mountModal(connection())

    await wrapper.find('[data-action="keep-destination"]').trigger('click')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT')!
    expect(put.url).toContain('/interfaces/if-srv/port-role')
    expect(put.body).toEqual({ is_management: false, is_data_transfer: true })
  })

  it('ошибка API показывается в модалке, модалка остаётся открытой, кнопки снова доступны', async () => {
    stubApi((call) => (call.url.endsWith('/connections/port-config/approve') ? jsonResponse({ detail: 'Подключение не найдено: c-1' }, 404) : undefined))
    const wrapper = mountModal(connection())

    await wrapper.find('[data-action="approve"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('.form-error').text()).toContain('Подключение не найдено')
    expect(wrapper.emitted('close')).toBeUndefined()
    expect((wrapper.find('[data-action="approve"]').element as HTMLButtonElement).disabled).toBe(false)
  })

  it('если конфигурации уже совпадают, действий по расхождению нет — только сообщение', () => {
    const wrapper = mountModal(connection({ destination_port_role: 'management', port_config_status: 'ok', port_config_diff: [] }))

    expect(wrapper.text()).toContain('Конфигурации портов совпадают')
    expect(wrapper.find('[data-action]').exists()).toBe(false)
  })

  it('расхождение режима и VLAN: подсвечивает различающиеся значения и предлагает настроить порты, а не выравнивать роль', () => {
    const wrapper = mountModal(
      connection({
        source_port_role: 'data',
        destination_port_role: 'data',
        source_vlan_mode: 'trunk',
        destination_vlan_mode: 'access',
        source_vlans: [10, 11, 12, 20],
        destination_vlans: [10],
        port_config_diff: ['mode', 'vlans'],
      }),
    )

    expect(wrapper.find('[data-mode-side="source"]').text()).toBe('Режим: trunk')
    expect(wrapper.find('[data-mode-side="destination"]').text()).toBe('Режим: access')
    expect(wrapper.find('[data-vlans-side="source"]').text()).toBe('VLAN: 10–12, 20')
    expect(wrapper.find('[data-vlans-side="destination"]').text()).toBe('VLAN: 10')
    expect(wrapper.find('[data-mode-side="source"]').classes()).toContain('diff')
    expect(wrapper.find('[data-vlans-side="destination"]').classes()).toContain('diff')
    expect(wrapper.find('[data-side="source"]').classes()).not.toContain('diff') // роли совпадают
    expect(wrapper.find('.status.warn').text()).toContain('режим, VLAN')
    // Роль выравнивать нечего; режим выравнивается каскадом, VLAN правятся в окне портов устройства.
    expect(wrapper.find('[data-action="keep-source"]').exists()).toBe(false)
    expect(wrapper.find('[data-action="mode-to-source"]').exists()).toBe(true)
    expect(wrapper.find('[data-action="mode-to-destination"]').exists()).toBe(true)
    expect(wrapper.find('[data-action="manage-source"]').exists()).toBe(true)
    expect(wrapper.find('[data-action="manage-destination"]').exists()).toBe(true)
    expect(wrapper.find('[data-action="approve"]').exists()).toBe(true)
  })

  it('«Настроить VLAN» просит родителя открыть порты нужного устройства', async () => {
    const wrapper = mountModal(connection({ source_vlan_mode: 'trunk', destination_vlan_mode: 'trunk', port_config_diff: ['vlans'], source_port_role: 'data' }))

    await wrapper.find('[data-action="manage-destination"]').trigger('click')

    expect(wrapper.emitted('manage-ports')).toEqual([[{ interfaceId: 'if-sw', deviceLabel: 'sw-01' }]])
  })

  it('«Изменить порт…» просит родителя открыть правку нужной стороны — для расхождения и для одобренного расхождения', async () => {
    const wrapper = mountModal(connection())

    expect(wrapper.find('[data-action="edit-source"]').text()).toContain('Изменить порт «idrac» (srv-01)')
    await wrapper.find('[data-action="edit-source"]').trigger('click')
    await wrapper.find('[data-action="edit-destination"]').trigger('click')

    expect(wrapper.emitted('edit-port')).toEqual([['source'], ['destination']])

    const approved = mountModal(connection({ port_config_status: 'approved' }))
    expect(approved.find('[data-action="edit-destination"]').exists()).toBe(true)
  })

  it('когда конфигурации совпадают, править порт из этого окна не предлагается', () => {
    const wrapper = mountModal(connection({ destination_port_role: 'management', port_config_status: 'ok', port_config_diff: [] }))

    expect(wrapper.find('[data-action="edit-source"]').exists()).toBe(false)
    expect(wrapper.find('[data-action="edit-destination"]').exists()).toBe(false)
  })

  it('различие только в режиме: режим выравнивается каскадом, а окно портов (VLAN) не предлагается', () => {
    const wrapper = mountModal(connection({ source_vlan_mode: 'trunk', destination_vlan_mode: 'access', port_config_diff: ['mode'], source_port_role: 'data' }))

    expect(wrapper.find('[data-action="mode-to-destination"]').text()).toContain('Порту «Gi0/5» задать режим как у «idrac» (trunk)')
    expect(wrapper.find('[data-action="mode-to-source"]').text()).toContain('Порту «idrac» задать режим как у «Gi0/5» (access)')
    expect(wrapper.find('[data-action="manage-source"]').exists()).toBe(false)
    expect(wrapper.find('[data-action="manage-destination"]').exists()).toBe(false)
  })

  // --- Режим порта: каскад вместо окна портов ---
  describe('выравнивание режима каскадом', () => {
    const CASCADE_URL = '/vlan-mode-cascade'
    const modeMismatch = () => connection({ source_vlan_mode: 'trunk', destination_vlan_mode: 'access', port_config_diff: ['mode'], source_port_role: 'data' })

    function cascadeApi(
      plan: VlanModeCascadePlan,
      apply: () => Response = () =>
        jsonResponse({
          plan,
          applied: { ports: 1, groups: 0, devices: 1 },
          interfaces: [{ id: 'if-sw', name: 'Gi0/5', physical_device_id: 'dev-sw', vlan_mode: plan.target_mode }],
        }),
    ) {
      stubApi((call) => {
        if (!call.url.includes(CASCADE_URL)) return undefined
        return call.url.endsWith('/preview') ? jsonResponse(plan) : apply()
      })
    }
    const cascadeCalls = () => calls.filter((c) => c.url.includes(CASCADE_URL))
    const groupPlan = () =>
      makePlan({
        target_mode: 'trunk',
        start_interface_id: 'if-sw',
        groups: [
          groupChange({
            id: 'g9',
            name: 'Магистраль',
            device_id: 'dev-sw',
            device_name: 'sw-01',
            from_mode: 'access',
            to_mode: 'trunk',
            ports: [
              { id: 'if-sw', name: 'Gi0/5' },
              { id: 'if-sw2', name: 'Gi0/6' },
            ],
          }),
        ],
        ports: [portChange({ id: 'if-x', name: 'Gi0/1', device_id: 'dev-x', device_name: 'sw-02', from_mode: 'access', to_mode: 'trunk' })],
        devices: [
          { id: 'dev-sw', name: 'sw-01', deferred: false, port_count: 2, group_count: 1 },
          { id: 'dev-x', name: 'sw-02', deferred: false, port_count: 1, group_count: 0 },
        ],
        totals: { ports: 3, devices: 2, groups: 1, deferred_ports: 0, immediate_ports: 3, immediate_devices: 2, dropped_vlans: 0 },
        hash: 'hash-dash',
      })

    it('простой случай: предпросмотр без формы (edited: null), затем сразу применение; таблица перечитывается, окно закрывается', async () => {
      const plan = makePlan({
        target_mode: 'trunk',
        start_interface_id: 'if-sw',
        ports: [portChange({ id: 'if-sw', name: 'Gi0/5', device_name: 'sw-01', from_mode: 'access', to_mode: 'trunk' })],
      })
      cascadeApi(plan)
      const catalogs = useCatalogsStore()
      catalogs.items['interfaces'] = [{ id: 'if-sw', name: 'Gi0/5', physical_device_id: 'dev-sw', vlan_mode: 'access' }]
      const wrapper = mountModal(modeMismatch())

      await wrapper.find('[data-action="mode-to-destination"]').trigger('click')
      await flushPromises()

      const [preview, apply] = cascadeCalls()
      expect(preview).toMatchObject({ method: 'POST', body: { mode: 'trunk', edited: null } })
      expect(preview.url).toContain('/interfaces/if-sw/vlan-mode-cascade/preview')
      expect(apply).toMatchObject({ method: 'POST', body: { mode: 'trunk', edited: null, plan_hash: 'hash-1', confirm: true } })
      expect(catalogs.items['interfaces'][0]).toMatchObject({ vlan_mode: 'trunk' }) // кэш портов обновлён
      expect(pageRequests().length).toBeGreaterThan(0) // таблица перечитана: статус сверки считает сервер
      expect(wrapper.emitted('close')).toHaveLength(1)
      expect(wrapper.find('.cascade-modal').exists()).toBe(false)
    })

    it('«как у соседа» в обратную сторону: целевой порт — источник, режим — назначения', async () => {
      const plan = makePlan({ target_mode: 'access', start_interface_id: 'if-srv' })
      cascadeApi(plan)
      const wrapper = mountModal(modeMismatch())

      await wrapper.find('[data-action="mode-to-source"]').trigger('click')
      await flushPromises()

      expect(cascadeCalls()[0].url).toContain('/interfaces/if-srv/vlan-mode-cascade/preview')
      expect(cascadeCalls()[0].body).toMatchObject({ mode: 'access', edited: null })
    })

    it('группа и связанные порты: окно последствий; без подтверждения ничего не записывается, подтверждение применяет и закрывает', async () => {
      cascadeApi(groupPlan())
      const wrapper = mountModal(modeMismatch())

      await wrapper.find('[data-action="mode-to-destination"]').trigger('click')
      await flushPromises()

      expect(wrapper.find('.cascade-modal').exists()).toBe(true)
      expect(wrapper.find('.cascade-item-title').text()).toContain('Группа «Магистраль»')
      expect(wrapper.find('.cascade-desc').text()).toContain('«Gi0/5» (sw-01)') // изменяемый порт — сторона назначения
      expect(cascadeCalls().filter((c) => !c.url.endsWith('/preview'))).toHaveLength(0)
      expect(wrapper.emitted('close')).toBeUndefined()

      await wrapper.find('.cascade-ack input').setValue(true)
      await wrapper.find('.cascade-actions .btn-primary').trigger('click')
      await flushPromises()

      expect(cascadeCalls().filter((c) => !c.url.endsWith('/preview'))).toHaveLength(1)
      expect(wrapper.find('.cascade-modal').exists()).toBe(false)
      expect(wrapper.emitted('close')).toHaveLength(1)
    })

    it('«Отмена» в окне последствий: ничего не записано, окно проверки остаётся открытым', async () => {
      cascadeApi(groupPlan())
      const wrapper = mountModal(modeMismatch())
      await wrapper.find('[data-action="mode-to-destination"]').trigger('click')
      await flushPromises()

      await wrapper.find('.cascade-actions .btn-secondary').trigger('click')

      expect(wrapper.find('.cascade-modal').exists()).toBe(false)
      expect(cascadeCalls().filter((c) => !c.url.endsWith('/preview'))).toHaveLength(0)
      expect(wrapper.emitted('close')).toBeUndefined()
    })

    it('режим уже совпадает (пустой план): сообщение, таблица перечитывается, окно закрывается', async () => {
      cascadeApi(makePlan({ empty: true, groups: [], ports: [], devices: [], totals: { ...makePlan().totals, ports: 0 } }))
      const wrapper = mountModal(modeMismatch())

      await wrapper.find('[data-action="mode-to-destination"]').trigger('click')
      await flushPromises()

      expect(cascadeCalls()).toHaveLength(1)
      expect(useToast().toasts.at(-1)).toMatchObject({ type: 'info' })
      expect(wrapper.emitted('close')).toHaveLength(1)
    })

    it('ошибка предпросмотра (например, слишком большая область) показывается в окне проверки, кнопки снова доступны', async () => {
      stubApi((call) => (call.url.includes(CASCADE_URL) ? jsonResponse({ detail: 'Область изменения превышает 1000 портов' }, 422) : undefined))
      const wrapper = mountModal(modeMismatch())

      await wrapper.find('[data-action="mode-to-destination"]').trigger('click')
      await flushPromises()

      expect(wrapper.find('.form-error').text()).toContain('Область изменения превышает 1000 портов')
      expect(wrapper.emitted('close')).toBeUndefined()
      expect((wrapper.find('[data-action="mode-to-destination"]').element as HTMLButtonElement).disabled).toBe(false)
    })
  })

  it('различие только в роли не предлагает настраивать режим и VLAN', () => {
    const wrapper = mountModal(connection())

    expect(wrapper.find('[data-action="manage-source"]').exists()).toBe(false)
    expect(wrapper.find('[data-action="mode-to-source"]').exists()).toBe(false)
    expect(wrapper.find('[data-side="source"]').classes()).toContain('diff')
    expect(wrapper.find('[data-mode-side="source"]').classes()).not.toContain('diff')
  })
})

// --- рекомендация по правилам согласования ---------------------------------------------------------

const syncPreviewCalls = () => calls.filter((c) => c.method === 'POST' && c.url.endsWith('/port-sync/preview'))

function planFor(item: Record<string, unknown> | null, summary: Record<string, unknown> = {}) {
  const base = {
    connection_id: 'c-1',
    outcome: 'auto',
    reason: null,
    target: 'source',
    warnings: [],
    options: [],
    rule: { id: 'r-1', code: 'empty_trunk_takes_neighbor_vlans', name: 'Пустой trunk получает VLAN соседа', action: 'auto' },
    source: { interface_id: 'if-srv', name: 'idrac', device_id: 'dev-1', device_name: 'srv-01', role: 'management', mode: 'trunk', vlans: [] },
    destination: { interface_id: 'if-sw', name: 'Gi0/5', device_id: 'dev-2', device_name: 'sw-01', role: 'data', mode: 'trunk', vlans: [10, 20] },
    changes: { role: null, mode: null, vlans: { from: [], to: [10, 20], skipped: [] } },
  }
  return {
    items: item ? [{ ...base, ...item }] : [],
    summary: { connections: 1, applicable: 1, shown: 1, total_items: 1, auto: 1, blocked: 0, manual: 0, ignored: 0, none: 0, skipped: 0, ...summary },
    plan_hash: 'hash-1',
  }
}

function stubWithPlan(plan: unknown, extra: (call: Call) => Response | undefined = () => undefined) {
  stubApi((call) => {
    if (call.method === 'POST' && call.url.endsWith('/port-sync/preview')) return jsonResponse(plan)
    return extra(call)
  })
}

describe('PortConfigReviewModal.vue — рекомендация по правилам согласования', () => {
  it('для расхождения запрашивает у сервера план по этому подключению и показывает, что сделает правило', async () => {
    stubWithPlan(planFor({}))
    const wrapper = mountModal(connection())
    await flushPromises()

    expect(syncPreviewCalls()).toHaveLength(1)
    expect(syncPreviewCalls()[0].body).toEqual({ connection_ids: ['c-1'] })
    const block = wrapper.find('[data-recommendation]')
    expect(block.text()).toContain('«Пустой trunk получает VLAN соседа»')
    expect(block.text()).toContain('Порту «idrac» (srv-01) будет применено')
    expect(block.text()).toContain('VLAN: нет → 10, 20')
    expect(block.find('[data-action="plan"]').exists()).toBe(true)
  })

  it('для подключения без расхождения рекомендацию не запрашивает', async () => {
    stubWithPlan(planFor({}))
    const wrapper = mountModal(connection({ port_config_status: 'ok', destination_port_role: 'management', port_config_diff: [] }))
    await flushPromises()

    expect(syncPreviewCalls()).toEqual([])
    expect(wrapper.find('[data-recommendation]').exists()).toBe(false)
  })

  it('заблокированное правило показывает причину и не предлагает применить', async () => {
    stubWithPlan(
      planFor(
        { outcome: 'blocked', reason: 'Порт входит в группу «Серверные», которая задаёт режим и VLAN — измените группу' },
        { applicable: 0, blocked: 1, auto: 0 },
      ),
    )
    const wrapper = mountModal(connection())
    await flushPromises()

    expect(wrapper.find('[data-recommendation-reason]').text()).toContain('Серверные')
    expect(wrapper.find('[data-action="plan"]').exists()).toBe(false)
  })

  it('ручное правило: решает человек, варианты перечислены, применить автоматически нельзя', async () => {
    stubWithPlan(
      planFor(
        {
          outcome: 'manual',
          target: null,
          changes: null,
          rule: { id: 'r-2', code: 'role_match', name: 'Роль порта совпадает с ролью соседа', action: 'manual' },
          options: [{ target: 'source', changes: { role: 'data', mode: null, vlans: null } }],
        },
        { applicable: 0, manual: 1, auto: 0 },
      ),
    )
    const wrapper = mountModal(connection())
    await flushPromises()

    const block = wrapper.find('[data-recommendation]')
    expect(block.text()).toContain('Роль порта совпадает с ролью соседа')
    expect(block.text()).toContain('решает человек')
    expect(block.text()).toContain('«idrac» (srv-01): роль → Передача данных')
    expect(block.find('[data-action="plan"]').exists()).toBe(false)
  })

  it('предупреждения правила показываются рядом с рекомендацией', async () => {
    stubWithPlan(planFor({ warnings: ['Не назначены VLAN, которых нет у устройства порта: 30'] }))
    const wrapper = mountModal(connection())
    await flushPromises()

    expect(wrapper.find('[data-recommendation-warning]').text()).toContain('30')
  })

  it('правило «объединить»: рекомендация перечисляет изменения каждого из двух портов', async () => {
    const both = {
      target: 'both',
      changes: null,
      rule: { id: 'r-3', code: 'trunk_vlans_union', name: 'Trunk: наборы VLAN на концах линии объединяются', action: 'auto' },
      source: { interface_id: 'if-srv', name: 'idrac', device_id: 'dev-1', device_name: 'srv-01', role: 'data', mode: 'trunk', vlans: [10, 20] },
      destination: { interface_id: 'if-sw', name: 'Gi0/5', device_id: 'dev-2', device_name: 'sw-01', role: 'data', mode: 'trunk', vlans: [10, 30] },
      targets: [
        { target: 'source', changes: { role: null, mode: null, vlans: { from: [10, 20], to: [10, 20, 30], skipped: [] } }, blocked: null },
        { target: 'destination', changes: { role: null, mode: null, vlans: { from: [10, 30], to: [10, 20, 30], skipped: [] } }, blocked: null },
      ],
    }
    stubWithPlan(planFor(both, { applicable: 2 }))
    const wrapper = mountModal(connection({ source_port_role: 'data', port_config_diff: ['vlans'] }))
    await flushPromises()

    const block = wrapper.find('[data-recommendation]')
    const targets = block.findAll('[data-recommendation-target]')
    expect(targets.map((t) => t.text())).toEqual(['Порту «idrac» (srv-01) будет применено:', 'Порту «Gi0/5» (sw-01) будет применено:'])
    expect(block.text()).toContain('VLAN: 10, 20 → 10, 20, 30')
    expect(block.text()).toContain('VLAN: 10, 30 → 10, 20, 30')
    expect(block.find('[data-action="plan"]').exists()).toBe(true)
  })

  it('правило «объединить»: порт, которому изменение не применится, показан с причиной, а второй порт применим', async () => {
    const half = {
      target: 'both',
      changes: null,
      rule: { id: 'r-3', code: 'trunk_vlans_union', name: 'Trunk: наборы VLAN на концах линии объединяются', action: 'auto' },
      source: { interface_id: 'if-srv', name: 'idrac', device_id: 'dev-1', device_name: 'srv-01', role: 'data', mode: 'trunk', vlans: [10, 20] },
      destination: { interface_id: 'if-sw', name: 'Gi0/5', device_id: 'dev-2', device_name: 'sw-01', role: 'data', mode: 'trunk', vlans: [10, 30] },
      targets: [
        { target: 'source', changes: { role: null, mode: null, vlans: { from: [10, 20], to: [10, 20, 30], skipped: [] } }, blocked: null },
        { target: 'destination', changes: null, blocked: 'Порт входит в группу «Серверные», которая задаёт режим и VLAN — измените группу' },
      ],
    }
    stubWithPlan(planFor(half))
    const wrapper = mountModal(connection({ port_config_diff: ['vlans'] }))
    await flushPromises()

    expect(wrapper.findAll('[data-recommendation-target]')).toHaveLength(1)
    expect(wrapper.find('[data-recommendation-target-blocked]').text()).toContain('«Gi0/5» (sw-01) не изменится: Порт входит в группу «Серверные»')
    expect(wrapper.find('[data-action="plan"]').exists()).toBe(true)
  })

  it('если подходящего правила нет, блок не показывается', async () => {
    stubWithPlan(planFor({ outcome: 'none', rule: null, target: null, changes: null }, { applicable: 0, none: 1, auto: 0 }))
    const wrapper = mountModal(connection())
    await flushPromises()

    expect(wrapper.find('[data-recommendation]').exists()).toBe(false)
  })

  it('сбой запроса рекомендации не мешает окну проверки: действия доступны, блока нет', async () => {
    stubApi((call) => (call.url.endsWith('/port-sync/preview') ? jsonResponse({ detail: 'Сервер недоступен' }, 500) : undefined))
    const wrapper = mountModal(connection())
    await flushPromises()

    expect(wrapper.find('[data-recommendation]').exists()).toBe(false)
    expect(wrapper.find('[data-action="approve"]').exists()).toBe(true)
  })

  it('«Согласовать по правилу…» открывает план по этому подключению; применение перечитывает дашборд и закрывает окно проверки', async () => {
    stubWithPlan(planFor({}), (call) => {
      if (call.method === 'POST' && call.url.endsWith('/port-sync/apply')) {
        return jsonResponse({ applied: { ports: 1, connections: 1 }, connection_ids: ['c-1'], summary: planFor(null).summary })
      }
      return undefined
    })
    const wrapper = mountModal(connection())
    await flushPromises()

    await wrapper.find('[data-action="plan"]').trigger('click')
    await flushPromises()
    expect(syncPreviewCalls()).toHaveLength(2) // рекомендация + окно плана
    expect(syncPreviewCalls()[1].body).toEqual({ connection_ids: ['c-1'] })
    expect(wrapper.text()).toContain('Согласование портов по правилу')

    await wrapper.find('[data-field="confirm"]').setValue(true)
    await wrapper.find('[data-action="apply"]').trigger('click')
    await flushPromises()

    expect(calls.find((c) => c.url.endsWith('/port-sync/apply'))!.body).toEqual({ connection_ids: ['c-1'], plan_hash: 'hash-1', confirm: true })
    expect(pageRequests()).toHaveLength(1)
    expect(wrapper.emitted('close')).toBeTruthy()
  })
})
