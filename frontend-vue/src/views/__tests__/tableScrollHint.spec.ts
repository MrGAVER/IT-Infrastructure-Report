// F-05 (код-ревью main): подсказка о горизонтальной прокрутке (затухание у края) была у трёх таблиц из восьми — остальные на
// телефоне прокручивались вбок без всякого признака, а кнопки «Изменить» и «Удалить» лежат в последней колонке, за краем экрана.
// Теперь все перечисленные в ревью таблицы стоят в ScrollableTableWrap. jsdom не считает раскладку, поэтому переполнение
// подменяется размерами корня обёртки, а «нет собственного overflow-x» проверяется по исходнику стилей экрана.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AuditLogView from '../AuditLogView.vue'
import ReportTemplatesView from '../ReportTemplatesView.vue'
import OtherCatalogsView from '../OtherCatalogsView.vue'
import VMsView from '../VMsView.vue'
import ContainersView from '../ContainersView.vue'
import ScrollableTableWrap from '../../components/ScrollableTableWrap.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useContainersStore } from '../../stores/containers'
import { useDevicesStore } from '../../stores/devices'
import { useVMsStore } from '../../stores/vms'
import { auditJournal, auditServer } from '../../stores/__tests__/fixtures'
import { readStyles } from '../../__tests__/cssSource'
import type { Container, VirtualMachine } from '../../api/types'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })

interface Case {
  name: string
  file: string
  label: string
  mountWithRows: () => Promise<VueWrapper>
}

const cases: Case[] = [
  {
    name: 'журнал аудита',
    file: 'src/views/AuditLogView.vue',
    label: 'Журнал аудита',
    async mountWithRows() {
      const server = auditServer(auditJournal(3))
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => json(server(url))),
      )
      useCatalogsStore().loaded = true
      const wrapper = mount(AuditLogView)
      await flushPromises()
      return wrapper
    },
  },
  {
    name: 'шаблоны отчётов',
    file: 'src/views/ReportTemplatesView.vue',
    label: 'Шаблоны отчётов',
    async mountWithRows() {
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => json([{ id: 't-1', name: 'Реестр устройств', description: null, format: 'xlsx', config: {}, created_at: null, updated_at: null }])),
      )
      const wrapper = mount(ReportTemplatesView)
      await flushPromises()
      return wrapper
    },
  },
  {
    name: 'другие справочники',
    file: 'src/views/OtherCatalogsView.vue',
    label: 'Записи справочника «Тип устройства»',
    async mountWithRows() {
      const catalogs = useCatalogsStore()
      catalogs.items['device-types'] = [{ id: 'dt-1', name: 'Сервер' }]
      catalogs.loaded = true
      useDevicesStore().loaded = true
      const wrapper = mount(OtherCatalogsView)
      await flushPromises()
      return wrapper
    },
  },
  {
    name: 'виртуальные машины',
    file: 'src/views/VMsView.vue',
    label: 'Список виртуальных машин',
    async mountWithRows() {
      const store = useVMsStore()
      store.all = [
        {
          id: 'vm-1',
          name: 'app-01',
          operating_system_id: null,
          physical_device_id: null,
          hypervisor_os_id: null,
          purpose: null,
          description: null,
        } as VirtualMachine,
      ]
      store.total = 1
      store.loaded = true
      useCatalogsStore().loaded = true
      useDevicesStore().loaded = true
      const wrapper = mount(VMsView)
      await flushPromises()
      return wrapper
    },
  },
  {
    name: 'контейнеры',
    file: 'src/views/ContainersView.vue',
    label: 'Список контейнеров',
    async mountWithRows() {
      const store = useContainersStore()
      store.all = [
        { id: 'ct-1', name: 'nginx', virtual_machine_id: null, physical_device_id: null, runtime: null, runtime_version: null, purpose: null } as Container,
      ]
      store.loaded = true
      useDevicesStore().loaded = true
      useVMsStore().loaded = true
      const wrapper = mount(ContainersView)
      await flushPromises()
      return wrapper
    },
  },
]

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json({ items: [], total: 0, offset: 0, limit: 1000 })),
  )
})

describe.each(cases)('подсказка прокрутки таблицы — $name (F-05)', (c) => {
  it('таблица стоит в ScrollableTableWrap — регионе с понятным названием; голого .table-wrap рядом нет', async () => {
    const wrapper = await c.mountWithRows()

    const wraps = wrapper.findAllComponents(ScrollableTableWrap)
    expect(wraps).toHaveLength(1)
    expect(wraps[0].find('table').exists()).toBe(true)
    expect(wraps[0].attributes('role')).toBe('region')
    expect(wraps[0].attributes('aria-label')).toBe(c.label)
    expect(wrapper.findAll('.table-wrap')).toHaveLength(1)
  })

  it('таблица шире окна — край затухает и контейнер попадает в порядок фокуса; помещается — подсказки нет', async () => {
    const wrapper = await c.mountWithRows()
    const wrap = wrapper.getComponent(ScrollableTableWrap)

    // 390 px: таблица 780 px не помещается (так у журнала аудита в ревью).
    for (const [name, value] of Object.entries({ scrollWidth: 780, clientWidth: 348, scrollLeft: 0 })) {
      Object.defineProperty(wrap.element, name, { value, configurable: true, writable: true })
    }
    await wrap.trigger('scroll')
    expect(wrap.classes()).toContain('shade-right')
    expect(wrap.attributes('tabindex')).toBe('0')

    // Десктоп: таблица помещается целиком.
    Object.defineProperty(wrap.element, 'clientWidth', { value: 780, configurable: true, writable: true })
    await wrap.trigger('scroll')
    expect(wrap.classes()).not.toContain('shade-right')
    expect(wrap.attributes('tabindex')).toBeUndefined()
  })

  it('у экрана нет собственного правила .table-wrap: overflow-x уже есть в обёртке', () => {
    expect(readStyles(c.file)).not.toMatch(/\.table-wrap\s*\{/)
  })
})
