// Поле «Показывать по N» на страницах со списками: устройства, ВМ, контейнеры, информационные
// системы. Подключения и журнал аудита (серверные страницы) — в ConnectionsView.spec.ts и
// AuditLogView.spec.ts.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DevicesView from '../DevicesView.vue'
import VMsView from '../VMsView.vue'
import ContainersView from '../ContainersView.vue'
import InformationSystemsView from '../InformationSystemsView.vue'
import { useDevicesStore } from '../../stores/devices'
import { useVMsStore } from '../../stores/vms'
import { useContainersStore } from '../../stores/containers'
import { useInformationSystemsStore } from '../../stores/informationSystems'
import { useCatalogsStore } from '../../stores/catalogs'
import { useVLANsStore } from '../../stores/vlans'

const TOTAL = 100
const range = (n: number) => Array.from({ length: n }, (_, i) => i)

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))))
  const catalogs = useCatalogsStore()
  catalogs.loaded = true
  catalogs.items['device-types'] = [{ id: 'dt-1', name: 'Коммутатор' }]
  useVLANsStore().loaded = true
  for (const store of [useDevicesStore(), useVMsStore(), useContainersStore(), useInformationSystemsStore()]) {
    store.loaded = true
  }
})

const LISTS = [
  {
    name: 'устройства', component: DevicesView, defaultSize: 6,
    seed: () => { useDevicesStore().all = range(TOTAL).map((i) => ({ id: `d${i}`, device_type_id: 'dt-1', system_name: `dev-${i}`, serial_number: `SN-${i}`, stack_id: null, management_ips: '' })) as never },
  },
  {
    name: 'виртуальные машины', component: VMsView, defaultSize: 8,
    seed: () => { useVMsStore().all = range(TOTAL).map((i) => ({ id: `v${i}`, name: `vm-${i}` })) as never },
  },
  {
    name: 'контейнеры', component: ContainersView, defaultSize: 8,
    seed: () => { useContainersStore().all = range(TOTAL).map((i) => ({ id: `c${i}`, name: `ct-${i}`, virtual_machine_id: null, physical_device_id: null })) as never },
  },
  {
    name: 'информационные системы', component: InformationSystemsView, defaultSize: 8,
    seed: () => { useInformationSystemsStore().all = range(TOTAL).map((i) => ({ id: `s${i}`, name: `is-${i}` })) as never },
  },
]

describe.each(LISTS)('$name — выбор количества строк', ({ component, defaultSize, seed }) => {
  async function mountList() {
    seed()
    const wrapper = mount(component)
    await flushPromises()
    return wrapper
  }

  const dataRows = (wrapper: Awaited<ReturnType<typeof mountList>>) => wrapper.findAll('tbody tr')
  const select = (wrapper: Awaited<ReturnType<typeof mountList>>) => wrapper.find('.table-foot select')

  it('в подвале таблицы есть поле выбора; по умолчанию прежний размер страницы и варианты x1..x8', async () => {
    const wrapper = await mountList()

    expect(select(wrapper).exists()).toBe(true)
    expect((select(wrapper).element as HTMLSelectElement).value).toBe(String(defaultSize))
    expect(select(wrapper).findAll('option').map((o) => Number(o.text()))).toEqual([1, 2, 4, 8].map((m) => defaultSize * m))
    expect(dataRows(wrapper)).toHaveLength(defaultSize)
  })

  it('выбор другого значения меняет число строк, диапазон «Показано» и число страниц', async () => {
    const wrapper = await mountList()
    const size = defaultSize * 4

    await select(wrapper).setValue(String(size))

    expect(dataRows(wrapper)).toHaveLength(size)
    expect(wrapper.find('.table-foot').text()).toContain(`Показано 1–${size} из ${TOTAL}`)
    expect(wrapper.findAll('.pager button').filter((b) => /^\d+$/.test(b.text()))).toHaveLength(Math.ceil(TOTAL / size))
  })

  it('на второй странице диапазон считается от выбранного размера, а не от прежнего', async () => {
    const wrapper = await mountList()
    const size = defaultSize * 2
    await select(wrapper).setValue(String(size))

    await wrapper.findAll('.pager button').find((b) => b.text() === '2')!.trigger('click')

    expect(wrapper.find('.table-foot').text()).toContain(`Показано ${size + 1}–${size * 2} из ${TOTAL}`)
  })

  it('выбор запоминается: после повторного открытия страницы применяется сразу', async () => {
    const first = await mountList()
    await select(first).setValue(String(defaultSize * 2))
    first.unmount()

    setActivePinia(createPinia()) // «перезагрузка»: сторы создаются заново и читают localStorage
    for (const store of [useDevicesStore(), useVMsStore(), useContainersStore(), useInformationSystemsStore()]) store.loaded = true
    useCatalogsStore().loaded = true
    useCatalogsStore().items['device-types'] = [{ id: 'dt-1', name: 'Коммутатор' }]
    useVLANsStore().loaded = true
    const second = await mountList()

    expect((select(second).element as HTMLSelectElement).value).toBe(String(defaultSize * 2))
    expect(dataRows(second)).toHaveLength(defaultSize * 2)
  })
})
