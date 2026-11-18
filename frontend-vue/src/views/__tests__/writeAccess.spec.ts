// B-04: роль «только чтение» (viewer) в интерфейсе. Сервер отвечает 403 на любую запись, кроме формирования отчётов
// (backend/app/services/auth/gate.py: READ_ONLY_POST_PATHS), поэтому клиент не показывает viewer'у кнопки записи.
//
// Для каждого экрана из тикета проверяются три сценария:
//   • аутентификация включена, роль viewer — кнопок записи нет, а кнопки чтения («Просмотр», «Обновить», …) остались;
//   • аутентификация включена, роль admin — кнопки записи есть;
//   • аутентификация выключена (однопользовательский режим) — кнопки записи есть.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import DevicesView from '../DevicesView.vue'
import VMsView from '../VMsView.vue'
import ContainersView from '../ContainersView.vue'
import ConnectionsView from '../ConnectionsView.vue'
import DeviceStacksView from '../DeviceStacksView.vue'
import InformationSystemsView from '../InformationSystemsView.vue'
import VLANsView from '../VLANsView.vue'
import BuildingsView from '../BuildingsView.vue'
import StructuralUnitsView from '../StructuralUnitsView.vue'
import OtherCatalogsView from '../OtherCatalogsView.vue'
import PortSyncRulesView from '../PortSyncRulesView.vue'
import ReportTemplatesView from '../ReportTemplatesView.vue'
import DiagramListView from '../DiagramListView.vue'
import DiagramView from '../DiagramView.vue'
import VLANDomainsPanel from '../../components/VLANDomainsPanel.vue'

import { useAuthStore } from '../../stores/auth'
import { useCatalogsStore } from '../../stores/catalogs'
import { useDevicesStore } from '../../stores/devices'
import { useVMsStore } from '../../stores/vms'
import { useContainersStore } from '../../stores/containers'
import { useVLANsStore } from '../../stores/vlans'
import { useVLANDomainsStore } from '../../stores/vlanDomains'
import { useDiagramStore } from '../../stores/diagram'
import type { AuthUser, Connection, Container, Device, DeviceStack, InformationSystem, PortSyncRule, ReportTemplate, VirtualMachine } from '../../api/types'

// ---------- роли ----------

type Role = 'viewer' | 'admin' | 'auth-off'

function setRole(role: Role) {
  const auth = useAuthStore()
  if (role === 'auth-off') {
    auth.enabled = false
    auth.user = null
    return
  }
  auth.enabled = true
  auth.user = { id: 'u1', username: role, role, is_active: true, last_login_at: null, locked: false, created_at: '2026-01-01T00:00:00' } as AuthUser
}

// ---------- заготовки данных ----------

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
const emptyPage = { items: [], total: 0, offset: 0, limit: 1000 }

const device = (): Device =>
  ({
    id: 'dev-1',
    device_type_id: 'dt-1',
    manufacturer_id: null,
    model_id: null,
    serial_number: 'SN-1',
    system_name: 'srv-01',
    operating_system_id: null,
    embedded_os_id: null,
    siem_enabled: false,
    building_id: null,
    room_id: null,
    rack_id: null,
    rack_position: null,
    status: null,
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
  }) as Device

const vm = (): VirtualMachine =>
  ({
    id: 'vm-1',
    name: 'VM-01',
    operating_system_id: null,
    physical_device_id: null,
    hypervisor_os_id: null,
    purpose: null,
    status: 'active',
    description: null,
  }) as VirtualMachine

const container = (): Container => ({
  id: 'c-1',
  name: 'nginx',
  virtual_machine_id: null,
  physical_device_id: null,
  runtime: null,
  runtime_version: null,
  purpose: null,
})

const connection = (): Connection =>
  ({
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
    source_vlan_mode: 'trunk',
    destination_vlan_mode: 'trunk',
    source_vlans: [],
    destination_vlans: [],
    port_config_diff: [],
  }) as Connection

const stack = (): DeviceStack => ({ id: 'st-1', name: 'Стек-1', members: [] }) as unknown as DeviceStack

const system = (): InformationSystem =>
  ({
    id: 'is-1',
    number: null,
    name: 'ИС-1',
    type: 'ИС',
    description: null,
    purpose: null,
    localization: null,
    support_organization_id: null,
    support_method_id: null,
    process_description: null,
    siem_enabled: false,
    crypto_protection_enabled: false,
    crypto_protection_description_id: null,
    status: 'active',
  }) as InformationSystem

const syncRule = (id: string, overrides: Partial<PortSyncRule> = {}): PortSyncRule =>
  ({
    id,
    code: null,
    builtin: false,
    modified: false,
    name: `Правило ${id}`,
    description: '',
    enabled: true,
    priority: 10,
    action: 'auto',
    target: { role: 'any', mode: 'any', vlans: 'any' },
    source: { role: 'any', mode: 'any', vlans: 'any' },
    relation: { role: 'any', mode: 'any', vlans: 'any' },
    apply: { role: true, mode: false, vlans: 'keep' },
    ...overrides,
  }) as PortSyncRule

const template = (): ReportTemplate =>
  ({ id: 't-1', name: 'Реестр устройств', description: null, format: 'xlsx', config: {}, created_at: null, updated_at: null }) as ReportTemplate

const diagramSummary = {
  id: 'd1',
  name: 'Диаграмма 1',
  description: null,
  scope_filter: {},
  group_by: 'building',
  collapse_threshold: 20,
  last_export_format: null,
  created_at: null,
  updated_at: null,
}

// ---------- описание экранов ----------

/** Селектор CSS либо `text:<подстрока текста кнопки>`. */
type Matcher = string

interface Screen {
  name: string
  /** Монтирует экран с данными, у которых есть строки с кнопками действий. */
  mount: () => Promise<VueWrapper>
  /** Кнопки записи: у viewer их нет, у admin и при выключенной аутентификации есть. */
  write: Matcher[]
  /** Кнопки чтения: остаются у всех, в том числе у viewer. */
  read: Matcher[]
}

function present(wrapper: VueWrapper, matcher: Matcher): boolean {
  if (matcher.startsWith('text:')) {
    const text = matcher.slice('text:'.length)
    return wrapper.findAll('button').some((b) => b.text().includes(text))
  }
  return wrapper.find(matcher).exists()
}

let router: Router

async function mountWithRouter(component: object, path: string, props: Record<string, unknown> = {}, stubs: Record<string, boolean> = {}) {
  await router.push(path)
  const wrapper = mount(component, { props, global: { plugins: [router], stubs } })
  await flushPromises()
  return wrapper
}

const SCREENS: Screen[] = [
  {
    name: 'DevicesView (список устройств)',
    async mount() {
      const store = useDevicesStore()
      store.all = [device()]
      store.total = 1
      store.loaded = true
      useCatalogsStore().items['device-types'] = [{ id: 'dt-1', name: 'Коммутатор' }]
      useCatalogsStore().loaded = true
      useVLANsStore().loaded = true
      const wrapper = mount(DevicesView)
      await flushPromises()
      return wrapper
    },
    write: ['text:Добавить устройство', 'text:Стек', '[aria-label="Редактировать"]', '[aria-label="Копировать"]', '[aria-label="Удалить"]'],
    read: ['[aria-label="Просмотр"]', 'text:Обновить'],
  },
  {
    name: 'VMsView (виртуальные машины)',
    async mount() {
      const store = useVMsStore()
      store.all = [vm()]
      store.total = 1
      store.loaded = true
      useCatalogsStore().loaded = true
      useDevicesStore().loaded = true
      const wrapper = mount(VMsView)
      await flushPromises()
      return wrapper
    },
    write: ['text:Добавить ВМ', '[aria-label="Редактировать"]', '[aria-label="Копировать"]', '[aria-label="Удалить"]'],
    read: ['[aria-label="Просмотр"]', 'text:Обновить'],
  },
  {
    name: 'ContainersView (контейнеры)',
    async mount() {
      const store = useContainersStore()
      store.all = [container()]
      store.loaded = true
      const devices = useDevicesStore()
      devices.all = [{ id: 'dev-1', system_name: 'srv-01', serial_number: 'SN-1' } as never]
      devices.loaded = true
      const vms = useVMsStore()
      vms.all = [{ id: 'vm-1', name: 'app-vm-1' } as never]
      vms.loaded = true
      const wrapper = mount(ContainersView)
      await flushPromises()
      return wrapper
    },
    write: ['text:Добавить контейнер', '[aria-label="Редактировать"]', '[aria-label="Копировать"]', '[aria-label="Удалить"]'],
    read: ['[aria-label="Просмотр"]', 'text:Обновить'],
  },
  {
    name: 'ConnectionsView (подключения)',
    async mount() {
      const summary = { total: 1, active: 1, inactive: 0, mismatch: 0, approved: 0 }
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) =>
          /\/api\/v1\/connections\?/.test(url) ? json({ items: [connection()], total: 1, offset: 0, limit: 12, summary }) : json(emptyPage),
        ),
      )
      const catalogs = useCatalogsStore()
      catalogs.loaded = true
      catalogs.items['interfaces'] = []
      useDevicesStore().loaded = true
      const wrapper = mount(ConnectionsView)
      await flushPromises()
      return wrapper
    },
    write: [
      'text:Добавить подключение',
      '[aria-label="Редактировать"]',
      '[aria-label="Удалить"]',
      '[data-action="edit-port-source"]',
      '[data-action="edit-port-destination"]',
      '[aria-label="Управлять портами исходного устройства"]',
      '[aria-label="Управлять портами конечного устройства"]',
    ],
    read: ['[aria-label="Просмотр"]', 'text:Визуальный режим'],
  },
  {
    name: 'DeviceStacksView (стеки)',
    async mount() {
      // Экран перечитывает стеки при открытии — список должен прийти с «сервера», а не из заранее заполненного стора.
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => json(url.includes('/resources/device-stacks') ? { items: [stack()], total: 1, offset: 0, limit: 1000 } : emptyPage)),
      )
      const wrapper = mount(DeviceStacksView)
      await flushPromises()
      return wrapper
    },
    write: ['text:Добавить стек', '[aria-label="Удалить стек"]'],
    read: ['text:Открыть'],
  },
  {
    name: 'InformationSystemsView (информационные системы)',
    async mount() {
      useCatalogsStore().loaded = true
      useDevicesStore().loaded = true
      useVMsStore().loaded = true
      useContainersStore().loaded = true
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => (url.endsWith('/information-systems') ? json([system()]) : json(emptyPage))),
      )
      const wrapper = mount(InformationSystemsView)
      await flushPromises()
      return wrapper
    },
    write: ['text:Добавить ИС', '[aria-label="Редактировать"]', '[aria-label="Копировать"]', '[aria-label="Удалить"]'],
    read: ['[aria-label="Просмотр"]', 'text:Обновить'],
  },
  {
    name: 'VLANsView (VLAN)',
    async mount() {
      const vlans = useVLANsStore()
      vlans.groups = [
        { vlan_id: 10, definitions: [{ id: 'v-10', vlan_id: 10, name: 'Мониторинг', description: '', domain_id: null, domain_name: '', devices: [] }] },
      ] as never
      vlans.loaded = true
      const devices = useDevicesStore()
      devices.all = [device()]
      devices.loaded = true
      useCatalogsStore().loaded = true
      const wrapper = mount(VLANsView, { global: { stubs: { DeviceFormModal: true } } })
      await flushPromises()
      return wrapper
    },
    write: ['text:Массовое назначение VLAN', 'text:Добавить VLAN', '[aria-label="Редактировать"]', '[aria-label="Удалить"]'],
    read: ['[aria-label="Просмотр"]', 'text:Домены VLAN', 'text:Обновить'],
  },
  {
    name: 'BuildingsView (здания, помещения, стойки)',
    async mount() {
      const catalogs = useCatalogsStore()
      catalogs.items['buildings'] = [{ id: 'b-1', name: 'Корпус А' }]
      catalogs.items['rooms'] = [{ id: 'r-1', name: 'Серверная', building_id: 'b-1' }]
      catalogs.items['racks'] = [{ id: 'k-1', name: 'Стойка 1', room_id: 'r-1' }]
      catalogs.loaded = true
      const wrapper = mount(BuildingsView)
      await flushPromises()
      // раскрываем здание, затем помещение — чтобы в разметке появились кнопки помещений и стоек
      await wrapper.find('.expand-btn').trigger('click')
      await wrapper.findAll('.expand-btn')[1].trigger('click')
      return wrapper
    },
    write: [
      'text:Добавить здание',
      '[aria-label="Добавить помещение"]',
      '[aria-label="Добавить стойку"]',
      '[aria-label="Редактировать"]',
      '[aria-label="Удалить"]',
    ],
    read: ['[aria-label="Просмотр"]'],
  },
  {
    name: 'StructuralUnitsView (структурные единицы)',
    async mount() {
      const catalogs = useCatalogsStore()
      catalogs.items['structural-units'] = [{ id: 'su-1', name: 'Отдел ИБ', parent_id: null, description: null }]
      catalogs.loaded = true
      const wrapper = mount(StructuralUnitsView)
      await flushPromises()
      return wrapper
    },
    write: ['text:Добавить корневую единицу', '[aria-label="Добавить дочернюю единицу"]', '[aria-label="Редактировать"]', '[aria-label="Удалить"]'],
    read: ['[aria-label="Просмотр"]'],
  },
  {
    name: 'OtherCatalogsView (другие справочники)',
    async mount() {
      const catalogs = useCatalogsStore()
      catalogs.items['device-types'] = [{ id: 'dt-1', name: 'Сервер' }]
      catalogs.loaded = true
      useDevicesStore().loaded = true
      const wrapper = mount(OtherCatalogsView)
      await flushPromises()
      return wrapper
    },
    write: ['text:Добавить', '[aria-label="Редактировать"]'],
    read: ['[aria-label="Просмотр"]'],
  },
  {
    name: 'PortSyncRulesView (правила согласования портов)',
    async mount() {
      const rules = [syncRule('a'), syncRule('b', { builtin: true, code: 'std', modified: true, priority: 20 })]
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => json({ items: rules, total: rules.length })),
      )
      const wrapper = mount(PortSyncRulesView)
      await flushPromises()
      return wrapper
    },
    write: ['[data-action="create"]', '[data-action="up"]', '[data-action="down"]', '[data-action="reset"]', '[data-action="delete"]'],
    // предпросмотр плана согласования ничего не записывает (POST /port-sync/preview разрешён viewer'у, A-23); применить план он не может
    read: ['[data-action="edit"]', '[data-action="plan-all"]', '[data-action="preview"]'],
  },
  {
    name: 'ReportTemplatesView (шаблоны отчётов)',
    async mount() {
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => json([template()])),
      )
      return mountWithRouter(ReportTemplatesView, '/report-templates')
    },
    write: [
      'text:Новый шаблон',
      '[aria-label="Открыть в конструкторе"]',
      '[aria-label="Дублировать"]',
      '[aria-label="Переименовать"]',
      '[aria-label="Удалить"]',
    ],
    // формирование отчёта и история версий доступны viewer'у (POST /report-templates/{id}/generate разрешён сервером)
    read: ['[aria-label="Сформировать"]', '[aria-label="История версий"]', '[aria-label="Просмотр"]'],
  },
  {
    name: 'DiagramListView (список диаграмм)',
    async mount() {
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => json([diagramSummary])),
      )
      return mountWithRouter(DiagramListView, '/diagrams')
    },
    write: ['text:Новая диаграмма', 'text:Дублировать', '[aria-label="Удалить"]'],
    read: ['text:Открыть', 'text:Обновить'],
  },
  {
    name: 'DiagramView (диаграмма)',
    async mount() {
      const store = useDiagramStore()
      vi.spyOn(store, 'load').mockResolvedValue(undefined as never)
      store.diagram = { ...diagramSummary, nodes: [], edges: [], viewport: null } as never
      return mountWithRouter(DiagramView, '/diagrams/d1', {}, { VueFlow: true, DiagramDetailPanel: true, DiagramExportPanel: true })
    },
    write: ['[aria-label="Переименовать диаграмму"]', 'text:Пересобрать', 'text:Дублировать', 'text:Удалить'],
    read: ['text:К списку'],
  },
]

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  document.body.innerHTML = ''
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json(emptyPage)),
  )
  vi.stubGlobal(
    'confirm',
    vi.fn(() => true),
  )
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/diagrams', name: 'diagrams', component: { template: '<div/>' } },
      { path: '/diagrams/:id', name: 'diagram-detail', component: { template: '<div/>' } },
      { path: '/report-templates', name: 'report-templates', component: { template: '<div/>' } },
      { path: '/report-templates/:id/editor', name: 'report-template-editor', component: { template: '<div/>' } },
      { path: '/report-templates/:id/editor-docx', name: 'report-template-editor-docx', component: { template: '<div/>' } },
    ],
  })
})

describe.each(SCREENS)('B-04: $name', (screen) => {
  it('viewer: кнопок записи нет, кнопки чтения остались', async () => {
    setRole('viewer')
    const wrapper = await screen.mount()

    // страховка от ложного прохождения: экран действительно смонтирован и показывает данные
    expect(wrapper.html().length).toBeGreaterThan(200)
    for (const matcher of screen.write) expect(present(wrapper, matcher), `у viewer не должно быть: ${matcher}`).toBe(false)
    for (const matcher of screen.read) expect(present(wrapper, matcher), `у viewer должно остаться: ${matcher}`).toBe(true)
  })

  it.each<Role>(['admin', 'auth-off'])('%s: все кнопки записи на месте', async (role) => {
    setRole(role)
    const wrapper = await screen.mount()

    for (const matcher of screen.write) expect(present(wrapper, matcher), `${role}: должно быть ${matcher}`).toBe(true)
  })
})

describe('B-04: DiagramView — раскладку нельзя двигать без права записи', () => {
  it.each<[Role, string]>([
    ['viewer', 'false'],
    ['admin', 'true'],
    ['auth-off', 'true'],
  ])('%s: nodes-draggable=%s', async (role, expected) => {
    setRole(role)
    const screen = SCREENS.find((s) => s.name.startsWith('DiagramView'))!
    const wrapper = await screen.mount()

    // стаб VueFlow выводит проп атрибутом без дефиса: nodesdraggable="true|false"
    expect(wrapper.find('vue-flow-stub').attributes('nodesdraggable')).toBe(expected)
  })
})

describe('B-04: VLANDomainsPanel (домены VLAN)', () => {
  function mountPanel() {
    const domains = useVLANDomainsStore()
    domains.all = [{ id: 'dom-1', name: 'Кампус', description: null, source_device_id: 'dev-1', auto_sync: false }] as never
    domains.loaded = true
    const devices = useDevicesStore()
    devices.all = [device()]
    devices.loaded = true
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json(emptyPage)),
    )
    return mount(VLANDomainsPanel)
  }

  it('viewer: нет «Домен», «Синхронизировать» и удаления; «Изменить» превращается в «Просмотр»', async () => {
    setRole('viewer')
    const wrapper = mountPanel()
    await flushPromises()

    expect(present(wrapper, 'text:Домен')).toBe(false)
    expect(present(wrapper, 'text:Синхронизировать')).toBe(false)
    expect(present(wrapper, '[aria-label="Удалить домен"]')).toBe(false)
    expect(present(wrapper, 'text:Изменить')).toBe(false)
    expect(present(wrapper, 'text:Просмотр')).toBe(true)
  })

  it.each<Role>(['admin', 'auth-off'])('%s: все действия на месте', async (role) => {
    setRole(role)
    const wrapper = mountPanel()
    await flushPromises()

    expect(present(wrapper, 'text:Домен')).toBe(true)
    expect(present(wrapper, 'text:Синхронизировать')).toBe(true)
    expect(present(wrapper, '[aria-label="Удалить домен"]')).toBe(true)
    expect(present(wrapper, 'text:Изменить')).toBe(true)
  })
})
