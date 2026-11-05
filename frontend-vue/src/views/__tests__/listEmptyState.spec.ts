// F-04 (код-ревью main): на пустом реестре все списки писали «Ничего не найдено по заданным фильтрам», хотя фильтров нет и
// искать нечего — новый пользователь не получал подсказки, что делать. Теперь два случая разведены:
//   • реестр пуст — «пока нет» и кнопка создания записи (если есть право записи), про фильтры ни слова;
//   • записи есть, но поиск/фильтры ничего не оставили — «не найдено по заданным фильтрам» и кнопка «Сбросить фильтры».
// Один сценарий прогоняется по всем пяти спискам: устройства, подключения, ИС, ВМ, контейнеры.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { Component } from 'vue'
import DevicesView from '../DevicesView.vue'
import ConnectionsView from '../ConnectionsView.vue'
import InformationSystemsView from '../InformationSystemsView.vue'
import VMsView from '../VMsView.vue'
import ContainersView from '../ContainersView.vue'
import DeviceFormModal from '../../components/DeviceFormModal.vue'
import ConnectionFormModal from '../../components/ConnectionFormModal.vue'
import InformationSystemFormModal from '../../components/InformationSystemFormModal.vue'
import VMFormModal from '../../components/VMFormModal.vue'
import ContainerFormModal from '../../components/ContainerFormModal.vue'
import { useAuthStore } from '../../stores/auth'
import { useCatalogsStore } from '../../stores/catalogs'
import { useConnectionsDashboardStore } from '../../stores/connectionsDashboard'
import { useContainersStore } from '../../stores/containers'
import { useDevicesStore } from '../../stores/devices'
import { useInformationSystemsStore } from '../../stores/informationSystems'
import { useVLANsStore } from '../../stores/vlans'
import { useVMsStore } from '../../stores/vms'
import type { AuthUser, Connection, Container, Device, InformationSystem, VirtualMachine } from '../../api/types'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
const emptyPage = { items: [], total: 0, offset: 0, limit: 1000 }

function device(id: string, name: string): Device {
  return {
    id,
    device_type_id: 'dt-1',
    manufacturer_id: null,
    model_id: null,
    serial_number: `SN-${id}`,
    system_name: name,
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
  }
}

const vm = (id: string, name: string): VirtualMachine => ({
  id,
  name,
  operating_system_id: null,
  physical_device_id: null,
  hypervisor_os_id: null,
  purpose: null,
  description: null,
})

const container = (id: string, name: string): Container =>
  ({ id, name, virtual_machine_id: null, physical_device_id: null, runtime: null, runtime_version: null, purpose: null }) as Container

const system = (id: string, name: string): InformationSystem => ({
  id,
  number: null,
  name,
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
})

const connection: Connection = {
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
}

interface ListCase {
  name: string
  emptyText: string
  createLabel: string
  modal: Component
  /** Реестр пуст. */
  mountEmpty: () => Promise<VueWrapper>
  /** В реестре записи есть, но условия отбора ничего не оставили. */
  mountFilteredOut: () => Promise<VueWrapper>
  /** Сколько строк таблицы вернулось после сброса фильтров. */
  rowsAfterReset: number
  /** Поиск и фильтры вернулись к исходным значениям. */
  expectFiltersCleared: () => void
}

const cases: ListCase[] = [
  {
    name: 'устройства',
    emptyText: 'Устройств пока нет.',
    createLabel: 'Добавить устройство',
    modal: DeviceFormModal,
    rowsAfterReset: 2,
    async mountEmpty() {
      return mountDevices([])
    },
    async mountFilteredOut() {
      const wrapper = await mountDevices([device('d1', 'core-sw-01'), device('d2', 'edge-sw-02')])
      const store = useDevicesStore()
      store.search = 'нет такого'
      store.siemFilter = 'yes'
      store.deviceTypeId = 'dt-1'
      await flushPromises()
      return wrapper
    },
    expectFiltersCleared() {
      const store = useDevicesStore()
      expect([store.search, store.buildingId, store.deviceTypeId, store.siemFilter, store.structuralUnitIds]).toEqual(['', '', '', 'all', []])
    },
  },
  {
    name: 'подключения',
    emptyText: 'Подключений пока нет.',
    createLabel: 'Добавить подключение',
    modal: ConnectionFormModal,
    rowsAfterReset: 1,
    async mountEmpty() {
      return mountConnections(false)
    },
    async mountFilteredOut() {
      const wrapper = await mountConnections(true)
      const store = useConnectionsDashboardStore()
      store.activeFilter = 'no'
      store.portConfigFilter = 'mismatch'
      await flushPromises()
      return wrapper
    },
    expectFiltersCleared() {
      const store = useConnectionsDashboardStore()
      expect([store.search, store.activeFilter, store.portConfigFilter]).toEqual(['', 'all', 'all'])
    },
  },
  {
    name: 'информационные системы',
    emptyText: 'Информационных систем пока нет.',
    createLabel: 'Добавить ИС',
    modal: InformationSystemFormModal,
    rowsAfterReset: 2,
    async mountEmpty() {
      return mountSystems([])
    },
    async mountFilteredOut() {
      const wrapper = await mountSystems([system('s1', 'Альфа'), system('s2', 'Бета')])
      const store = useInformationSystemsStore()
      store.search = 'нет такой'
      store.siemFilter = 'yes'
      await flushPromises()
      return wrapper
    },
    expectFiltersCleared() {
      const store = useInformationSystemsStore()
      expect([store.search, store.siemFilter]).toEqual(['', 'all'])
    },
  },
  {
    name: 'виртуальные машины',
    emptyText: 'Виртуальных машин пока нет.',
    createLabel: 'Добавить ВМ',
    modal: VMFormModal,
    rowsAfterReset: 2,
    async mountEmpty() {
      return mountVMs([])
    },
    async mountFilteredOut() {
      const wrapper = await mountVMs([vm('v1', 'app-01'), vm('v2', 'db-01')])
      useVMsStore().search = 'нет такой'
      await flushPromises()
      return wrapper
    },
    expectFiltersCleared() {
      expect(useVMsStore().search).toBe('')
    },
  },
  {
    name: 'контейнеры',
    emptyText: 'Контейнеров пока нет.',
    createLabel: 'Добавить контейнер',
    modal: ContainerFormModal,
    rowsAfterReset: 2,
    async mountEmpty() {
      return mountContainers([])
    },
    async mountFilteredOut() {
      const wrapper = await mountContainers([container('c1', 'nginx'), container('c2', 'redis')])
      useContainersStore().search = 'нет такого'
      await flushPromises()
      return wrapper
    },
    expectFiltersCleared() {
      expect(useContainersStore().search).toBe('')
    },
  },
]

async function mountDevices(devices: Device[]) {
  const store = useDevicesStore()
  store.all = devices
  store.total = devices.length
  store.loaded = true
  useCatalogsStore().items['device-types'] = [{ id: 'dt-1', name: 'Коммутатор' }]
  useCatalogsStore().loaded = true
  useVLANsStore().loaded = true
  const wrapper = mount(DevicesView)
  await flushPromises()
  return wrapper
}

async function mountVMs(vms: VirtualMachine[]) {
  const store = useVMsStore()
  store.all = vms
  store.total = vms.length
  store.loaded = true
  useCatalogsStore().loaded = true
  useDevicesStore().loaded = true
  const wrapper = mount(VMsView)
  await flushPromises()
  return wrapper
}

async function mountContainers(containers: Container[]) {
  const store = useContainersStore()
  store.all = containers
  store.loaded = true
  useDevicesStore().loaded = true
  useVMsStore().loaded = true
  const wrapper = mount(ContainersView)
  await flushPromises()
  return wrapper
}

async function mountSystems(systems: InformationSystem[]) {
  useCatalogsStore().loaded = true
  useDevicesStore().loaded = true
  useVMsStore().loaded = true
  useContainersStore().loaded = true
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => (url.endsWith('/information-systems') ? json(systems) : json(emptyPage))),
  )
  const wrapper = mount(InformationSystemsView)
  await flushPromises()
  return wrapper
}

/** Сервер подключений: в реестре одно подключение (hasRecords) или ни одного; любой поиск и фильтр даёт пустую страницу,
 * а итоги по всему реестру (summary) от условий не зависят — как у настоящего сервера. */
async function mountConnections(hasRecords: boolean) {
  const catalogs = useCatalogsStore()
  catalogs.loaded = true
  if (!catalogs.items['interfaces']) catalogs.items['interfaces'] = []
  useDevicesStore().loaded = true
  const summary = { total: hasRecords ? 1 : 0, active: hasRecords ? 1 : 0, inactive: 0, mismatch: 0, approved: 0 }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (/\/api\/v1\/connections\?/.test(url)) {
        const params = new URL(url, 'http://x').searchParams
        const filtered = ['q', 'is_active', 'port_config_status'].some((name) => params.has(name))
        const items = hasRecords && !filtered ? [connection] : []
        return json({ items, total: items.length, offset: 0, limit: 8, summary })
      }
      return json(emptyPage)
    }),
  )
  const wrapper = mount(ConnectionsView)
  await flushPromises()
  return wrapper
}

function asViewer() {
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
  } as AuthUser
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json(emptyPage)),
  )
})

describe.each(cases)('пустой список — $name (F-04)', (c) => {
  it('реестр пуст: «пока нет» и кнопка создания, про фильтры ничего не сказано', async () => {
    const wrapper = await c.mountEmpty()

    const cell = wrapper.get('td.empty-row')
    expect(cell.text()).toContain(c.emptyText)
    expect(cell.text()).not.toContain('Ничего не найдено')
    expect(cell.text()).not.toContain('фильтр')
    expect(cell.find('[data-action="reset-filters"]').exists()).toBe(false)
    expect(cell.get('[data-action="create"]').text()).toBe(c.createLabel)
  })

  it('кнопка создания в пустой таблице открывает форму новой записи', async () => {
    const wrapper = await c.mountEmpty()
    expect(wrapper.findComponent(c.modal).exists()).toBe(false)

    await wrapper.get('td.empty-row [data-action="create"]').trigger('click')

    expect(wrapper.findComponent(c.modal).exists()).toBe(true)
  })

  it('пустой реестр у пользователя без права записи: пояснение есть, кнопки создания нет', async () => {
    asViewer()
    const wrapper = await c.mountEmpty()

    const cell = wrapper.get('td.empty-row')
    expect(cell.text()).toContain(c.emptyText)
    expect(cell.find('[data-action="create"]').exists()).toBe(false)
  })

  it('записи есть, фильтр ничего не оставил: «не найдено по фильтрам» и «Сбросить фильтры», без «пока нет» и без создания', async () => {
    const wrapper = await c.mountFilteredOut()

    const cell = wrapper.get('td.empty-row')
    expect(cell.text()).toContain('Ничего не найдено по заданным фильтрам.')
    expect(cell.text()).not.toContain('пока нет')
    expect(cell.find('[data-action="create"]').exists()).toBe(false)
    expect(cell.get('[data-action="reset-filters"]').text()).toBe('Сбросить фильтры')
  })

  it('«Сбросить фильтры» снимает поиск и все фильтры списка, записи возвращаются', async () => {
    const wrapper = await c.mountFilteredOut()

    await wrapper.get('td.empty-row [data-action="reset-filters"]').trigger('click')
    await flushPromises()

    c.expectFiltersCleared()
    expect(wrapper.find('td.empty-row').exists()).toBe(false)
    expect(wrapper.findAll('tbody tr')).toHaveLength(c.rowsAfterReset)
  })

  it('строка занимает все столбцы таблицы', async () => {
    const wrapper = await c.mountEmpty()

    const columns = wrapper.findAll('thead th').length
    expect(wrapper.get('td.empty-row').attributes('colspan')).toBe(String(columns))
  })
})
