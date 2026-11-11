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
import { reloadPinia } from '../../stores/__tests__/preferencesApi'

const TOTAL = 100
const DEFAULT_SIZE = 10 // F-09: у всех списков одна шкала 10 / 25 / 50 / 100
const range = (n: number) => Array.from({ length: n }, (_, i) => i)

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))),
  )
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
    name: 'устройства',
    component: DevicesView,
    seed: () => {
      useDevicesStore().all = range(TOTAL).map((i) => ({
        id: `d${i}`,
        device_type_id: 'dt-1',
        system_name: `dev-${i}`,
        serial_number: `SN-${i}`,
        stack_id: null,
        management_ips: '',
        siem_enabled: false, // YesNoStatus требует boolean: без поля Vue предупреждает о типе пропса на каждой строке (B-07)
      })) as never
    },
  },
  {
    name: 'виртуальные машины',
    component: VMsView,
    seed: () => {
      useVMsStore().all = range(TOTAL).map((i) => ({ id: `v${i}`, name: `vm-${i}` })) as never
    },
  },
  {
    name: 'контейнеры',
    component: ContainersView,
    seed: () => {
      useContainersStore().all = range(TOTAL).map((i) => ({ id: `c${i}`, name: `ct-${i}`, virtual_machine_id: null, physical_device_id: null })) as never
    },
  },
  {
    name: 'информационные системы',
    component: InformationSystemsView,
    seed: () => {
      useInformationSystemsStore().all = range(TOTAL).map((i) => ({
        id: `s${i}`,
        name: `is-${i}`,
        siem_enabled: false,
        crypto_protection_enabled: false,
      })) as never
    },
  },
]

describe.each(LISTS)('$name — выбор количества строк', ({ component, seed }) => {
  async function mountList() {
    seed()
    const wrapper = mount(component)
    await flushPromises()
    return wrapper
  }

  const dataRows = (wrapper: Awaited<ReturnType<typeof mountList>>) => wrapper.findAll('tbody tr')
  const select = (wrapper: Awaited<ReturnType<typeof mountList>>) => wrapper.find('.table-foot select')

  it('в подвале таблицы есть поле выбора; по умолчанию 10 строк, варианты — 10 / 25 / 50 / 100', async () => {
    const wrapper = await mountList()

    expect(select(wrapper).exists()).toBe(true)
    expect((select(wrapper).element as HTMLSelectElement).value).toBe(String(DEFAULT_SIZE))
    expect(
      select(wrapper)
        .findAll('option')
        .map((o) => Number(o.text())),
    ).toEqual([10, 25, 50, 100])
    expect(dataRows(wrapper)).toHaveLength(DEFAULT_SIZE)
  })

  it('выбор другого значения меняет число строк, диапазон «Показано» и число страниц', async () => {
    const wrapper = await mountList()
    const size = 50

    await select(wrapper).setValue(String(size))

    expect(dataRows(wrapper)).toHaveLength(size)
    expect(wrapper.find('.table-foot').text()).toContain(`Показано 1–${size} из ${TOTAL}`)
    expect(wrapper.findAll('.pager button').filter((b) => /^\d+$/.test(b.text()))).toHaveLength(Math.ceil(TOTAL / size))
  })

  it('на второй странице диапазон считается от выбранного размера, а не от прежнего', async () => {
    const wrapper = await mountList()
    const size = 25
    await select(wrapper).setValue(String(size))

    await wrapper
      .findAll('.pager button')
      .find((b) => b.text() === '2')!
      .trigger('click')

    expect(wrapper.find('.table-foot').text()).toContain(`Показано ${size + 1}–${size * 2} из ${TOTAL}`)
  })

  it('выбор запоминается: после повторного открытия страницы применяется сразу', async () => {
    const first = await mountList()
    await select(first).setValue('25')
    first.unmount()

    reloadPinia() // «перезагрузка»: сторы создаются заново, настройки подтянуты с сервера
    for (const store of [useDevicesStore(), useVMsStore(), useContainersStore(), useInformationSystemsStore()]) store.loaded = true
    useCatalogsStore().loaded = true
    useCatalogsStore().items['device-types'] = [{ id: 'dt-1', name: 'Коммутатор' }]
    useVLANsStore().loaded = true
    const second = await mountList()

    expect((select(second).element as HTMLSelectElement).value).toBe('25')
    expect(dataRows(second)).toHaveLength(25)
  })
})
