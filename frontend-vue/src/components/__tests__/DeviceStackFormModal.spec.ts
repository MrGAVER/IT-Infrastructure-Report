import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceStackFormModal from '../DeviceStackFormModal.vue'
import ConnectionFormModal from '../ConnectionFormModal.vue'
import DeviceStackVlanIpEditor from '../DeviceStackVlanIpEditor.vue'
import ScrollableTableWrap from '../ScrollableTableWrap.vue'
import { declaration, readStyles, ruleBody } from '../../__tests__/cssSource'
import { useDevicesStore } from '../../stores/devices'
import { useCatalogsStore } from '../../stores/catalogs'
import { useConnectionsStore } from '../../stores/connections'
import type { DeviceStack, DeviceStackDetail } from '../../api/types'

const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 1000 }

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function seedDevices() {
  const devices = useDevicesStore()
  devices.all = [
    { id: 'dev-1', system_name: 'core-sw-01', serial_number: 'SN-1', device_type_id: 'dt-1' } as never,
    { id: 'dev-2', system_name: 'core-sw-02', serial_number: 'SN-2', device_type_id: 'dt-1' } as never,
  ]
  devices.loaded = true
  const catalogs = useCatalogsStore()
  catalogs.items['device-types'] = [{ id: 'dt-1', name: 'Коммутатор' }]
}

function detailResponse(overrides?: Partial<DeviceStackDetail>): DeviceStackDetail {
  return {
    stack: { id: 'stack-1', name: 'Стек ядра', description: null },
    members: [],
    connections: [],
    ...overrides,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => jsonResponse(EMPTY_PAGE)),
  )
})

describe('DeviceStackFormModal.vue', () => {
  it('при создании нового стека скрывает управление составом и топологией', async () => {
    seedDevices()
    const wrapper = mount(DeviceStackFormModal, { props: { stack: null } })
    await flushPromises()

    expect(wrapper.text()).toContain('Состав и топологию стека можно настроить после первого сохранения')
    expect(wrapper.find('.nested-editor').exists()).toBe(false)
  })

  it('не сохраняет стек без наименования', async () => {
    seedDevices()
    const wrapper = mount(DeviceStackFormModal, { props: { stack: null } })
    await wrapper.find('form').trigger('submit')

    expect(wrapper.text()).toContain('Укажите наименование стека')
  })

  it('создаёт стек с указанными наименованием и описанием', async () => {
    seedDevices()
    const wrapper = mount(DeviceStackFormModal, { props: { stack: null } })

    await wrapper.find('input[type="text"]').setValue('Стек ядра')
    await wrapper.find('textarea').setValue('2 коммутатора')

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/device-stacks')) return jsonResponse({ id: 'stack-new' }, 201)
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const create = calls.find((c) => c.method === 'POST' && c.url.endsWith('/resources/device-stacks'))
    expect(create?.body).toEqual({ name: 'Стек ядра', description: '2 коммутатора' })
    // Возвращает родителю именно сохранённую запись (а не просто факт "сохранено") —
    // DevicesView.vue использует её, чтобы после создания сразу переключить эту же модалку в
    // режим редактирования.
    expect(wrapper.emitted('saved')?.[0]).toEqual([{ id: 'stack-new' }])
  })

  it('при редактировании загружает и отображает участников по позиции, с типом устройства', async () => {
    seedDevices()
    const stack: DeviceStack = { id: 'stack-1', name: 'Стек ядра', description: null }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/device-stacks/stack-1/detail')) {
          return jsonResponse(
            detailResponse({
              members: [
                { id: 'dev-1', system_name: 'core-sw-01', serial_number: 'SN-1', device_type_id: 'dt-1', stack_member_id: 'sm-1', stack_position: 1 } as never,
              ],
            }),
          )
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(DeviceStackFormModal, { props: { stack } })
    await flushPromises()

    const row = wrapper.find('.member-table tbody tr')
    expect(row.text()).toContain('core-sw-01')
    expect(row.text()).toContain('Коммутатор')
    expect(row.find('.col-pos').text()).toBe('1')
  })

  // Регресс: у <th>/<td> столбца кнопок стоял display: flex, и у пустого заголовка нижняя граница съезжала вверх
  // относительно соседних заголовков. Ячейки должны оставаться табличными, а кнопки лежать во вложенном контейнере.
  it('столбец кнопок: ячейки табличные, кнопки во вложенном .row-actions, у пустого заголовка есть скрытая подпись', async () => {
    seedDevices()
    const stack: DeviceStack = { id: 'stack-1', name: 'Стек ядра', description: null }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/device-stacks/stack-1/detail')) {
          return jsonResponse(
            detailResponse({
              members: [
                { id: 'dev-1', system_name: 'core-sw-01', serial_number: 'SN-1', device_type_id: 'dt-1', stack_member_id: 'sm-1', stack_position: 1 } as never,
              ],
            }),
          )
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(DeviceStackFormModal, { props: { stack } })
    await flushPromises()

    const head = wrapper.find('.member-table thead th.col-actions')
    expect(head.exists()).toBe(true)
    expect(head.find('.sr-only').text()).toBe('Действия')

    const cell = wrapper.find('.member-table tbody td.col-actions')
    expect(cell.find('.row-actions').exists()).toBe(true)
    expect(cell.findAll('.row-actions > button')).toHaveLength(2)
  })

  it('добавляет устройство в стек через POST .../members и перезагружает состав', async () => {
    seedDevices()
    const stack: DeviceStack = { id: 'stack-1', name: 'Стек ядра', description: null }
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    let added = false
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.includes('/device-stacks/stack-1/detail')) {
          return jsonResponse(
            detailResponse({
              members: added
                ? [
                    {
                      id: 'dev-1',
                      system_name: 'core-sw-01',
                      serial_number: 'SN-1',
                      device_type_id: 'dt-1',
                      stack_member_id: 'sm-1',
                      stack_position: 1,
                    } as never,
                  ]
                : [],
            }),
          )
        }
        if (method === 'POST' && url.includes('/device-stacks/stack-1/members')) {
          added = true
          return jsonResponse({ id: 'sm-1', stack_id: 'stack-1', physical_device_id: 'dev-1', position: 1 }, 201)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(DeviceStackFormModal, { props: { stack } })
    await flushPromises()
    await wrapper.find('.add-member-row .searchable-select input').trigger('focus')
    await wrapper.find('.add-member-row .ss-option').trigger('mousedown') // первая опция в списке — core-sw-01 (оба устройства пока свободны)
    await wrapper.find('.add-member-row > button.btn-secondary').trigger('click')
    await flushPromises()

    const call = calls.find((c) => c.method === 'POST' && c.url.includes('/members'))
    expect(call?.body).toEqual({ physical_device_id: 'dev-1', position: 1 })
    expect(wrapper.find('.member-table tbody tr').text()).toContain('core-sw-01')
  })

  it('показывает понятную ошибку, если устройство уже состоит в другом стеке', async () => {
    seedDevices()
    const stack: DeviceStack = { id: 'stack-2', name: 'Стек Б', description: null }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        if (url.includes('/device-stacks/stack-2/detail')) return jsonResponse(detailResponse({ stack: { id: 'stack-2', name: 'Стек Б', description: null } }))
        if (method === 'POST' && url.includes('/device-stacks/stack-2/members')) {
          return jsonResponse({ detail: 'Устройство уже состоит в стеке «Стек А»' }, 409)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(DeviceStackFormModal, { props: { stack } })
    await flushPromises()
    await wrapper.find('.add-member-row .searchable-select input').trigger('focus')
    await wrapper.find('.add-member-row .ss-option').trigger('mousedown')
    await wrapper.find('.add-member-row > button.btn-secondary').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Устройство уже состоит в стеке «Стек А»')
  })

  it('убирает устройство из стека через DELETE /resources/device-stack-members/{id}', async () => {
    seedDevices()
    const stack: DeviceStack = { id: 'stack-1', name: 'Стек ядра', description: null }
    const calls: Array<{ url: string; method: string }> = []
    let removed = false
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        if (url.includes('/device-stacks/stack-1/detail')) {
          return jsonResponse(
            detailResponse({
              members: removed
                ? []
                : [
                    {
                      id: 'dev-1',
                      system_name: 'core-sw-01',
                      serial_number: 'SN-1',
                      device_type_id: 'dt-1',
                      stack_member_id: 'sm-1',
                      stack_position: 1,
                    } as never,
                  ],
            }),
          )
        }
        if (method === 'DELETE' && url.includes('/resources/device-stack-members/sm-1')) {
          removed = true
          return jsonResponse({ status: 'deleted', id: 'sm-1' })
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(DeviceStackFormModal, { props: { stack } })
    await flushPromises()
    await wrapper.find('.member-table .icon-btn.danger').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/resources/device-stack-members/sm-1'))).toBe(true)
    expect(wrapper.find('.member-table').exists()).toBe(false)
  })

  it('отображает межстековые подключения в разделе "Топология стека"', async () => {
    seedDevices()
    const stack: DeviceStack = { id: 'stack-1', name: 'Стек ядра', description: null }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/device-stacks/stack-1/detail')) {
          return jsonResponse(
            detailResponse({
              members: [
                { id: 'dev-1', system_name: 'core-sw-01', serial_number: 'SN-1', device_type_id: 'dt-1', stack_member_id: 'sm-1', stack_position: 1 } as never,
                { id: 'dev-2', system_name: 'core-sw-02', serial_number: 'SN-2', device_type_id: 'dt-1', stack_member_id: 'sm-2', stack_position: 2 } as never,
              ],
              connections: [
                {
                  id: 'conn-1',
                  source_interface_id: 'if-1',
                  destination_interface_id: 'if-2',
                  connection_type_id: 'ct-1',
                  is_active: true,
                  description: null,
                  source_device_name: 'core-sw-01',
                  source_interface_name: 'stack-link',
                  destination_device_name: 'core-sw-02',
                  destination_interface_name: 'stack-link',
                  connection_type_name: 'Стековый кабель',
                  source_port_role: 'data' as const,
                  destination_port_role: 'data' as const,
                  port_config_status: 'ok' as const,
                  source_vlan_mode: 'trunk' as const,
                  destination_vlan_mode: 'trunk' as const,
                  source_vlans: [],
                  destination_vlans: [],
                  port_config_diff: [],
                },
              ],
            }),
          )
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(DeviceStackFormModal, { props: { stack } })
    await flushPromises()

    expect(wrapper.text()).toContain('core-sw-01 · stack-link')
    expect(wrapper.text()).toContain('core-sw-02 · stack-link')
    expect(wrapper.text()).toContain('Стековый кабель')
  })

  it('при открытии формы для существующего стека подгружает connectionsStore (фикс п.1)', async () => {
    // Раньше эта форма вообще не трогала connectionsStore — список занятых портов в
    // ConnectionFormModal.vue (interfacesFor → occupiedInterfaceIds) строился из пустого стора
    // при первом же открытии "Соединение" в сессии, если пользователь ещё не заходил на
    // отдельный дашборд "Подключения".
    seedDevices()
    const connectionsStore = useConnectionsStore()
    expect(connectionsStore.loaded).toBe(false)
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/device-stacks/stack-1/detail')) return jsonResponse(detailResponse())
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const stack: DeviceStack = { id: 'stack-1', name: 'Стек ядра', description: null }
    mount(DeviceStackFormModal, { props: { stack } })
    await flushPromises()

    expect(connectionsStore.loaded).toBe(true)
  })

  it('после сохранения подключения через "Соединение" перезагружает connectionsStore и топологию стека (фикс п.1)', async () => {
    seedDevices()
    const connectionsStore = useConnectionsStore()
    const reloadSpy = vi.spyOn(connectionsStore, 'reload')
    let detailFetchCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/device-stacks/stack-1/detail')) {
          detailFetchCount += 1
          return jsonResponse(
            detailResponse({
              members: [
                { id: 'dev-1', system_name: 'core-sw-01', serial_number: 'SN-1', device_type_id: 'dt-1', stack_member_id: 'sm-1', stack_position: 1 } as never,
                { id: 'dev-2', system_name: 'core-sw-02', serial_number: 'SN-2', device_type_id: 'dt-1', stack_member_id: 'sm-2', stack_position: 2 } as never,
              ],
            }),
          )
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const stack: DeviceStack = { id: 'stack-1', name: 'Стек ядра', description: null }
    const wrapper = mount(DeviceStackFormModal, { props: { stack } })
    await flushPromises()
    reloadSpy.mockClear() // сбрасываем счётчик после начального ensureLoaded() при открытии формы

    const connectionButton = wrapper.findAll('button').find((b) => b.text().includes('Соединение'))!
    await connectionButton.trigger('click')
    const connectionFormModal = wrapper.findComponent(ConnectionFormModal)
    expect(connectionFormModal.exists()).toBe(true)

    const detailFetchCountBeforeSave = detailFetchCount
    await connectionFormModal.vm.$emit('saved', { id: 'conn-new' })
    await flushPromises()

    expect(reloadSpy).toHaveBeenCalledTimes(1)
    expect(detailFetchCount).toBe(detailFetchCountBeforeSave + 1) // топология стека тоже перечитана
    expect(wrapper.findComponent(ConnectionFormModal).exists()).toBe(false) // модалка закрылась
  })

  it('кнопка "Просмотреть" открывает DeviceFormModal для отдельного устройства-участника', async () => {
    seedDevices()
    const stack: DeviceStack = { id: 'stack-1', name: 'Стек ядра', description: null }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/device-stacks/stack-1/detail')) {
          return jsonResponse(
            detailResponse({
              members: [
                { id: 'dev-1', system_name: 'core-sw-01', serial_number: 'SN-1', device_type_id: 'dt-1', stack_member_id: 'sm-1', stack_position: 1 } as never,
              ],
            }),
          )
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(DeviceStackFormModal, { props: { stack } })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'DeviceFormModal' }).exists()).toBe(false)

    await wrapper.find('.member-table .btn-sm').trigger('click')
    await flushPromises()

    expect(wrapper.findAllComponents({ name: 'DeviceFormModal' }).length).toBeGreaterThan(0)
  })

  // F-10 (код-ревью main): таблицы состава и топологии стека — 4 и 3 колонки; на телефоне (320–360 px) они раздвигали окно за край
  // экрана. Теперь листаются внутри ScrollableTableWrap (затухание у края подсказывает прокрутку), а элемент сетки формы может
  // сжиматься (min-width: 0) — без этого обёртке нечему было ограничивать ширину.
  describe('F-10: таблицы окна на телефоне', () => {
    it('обе таблицы (состав и топология) лежат в ScrollableTableWrap с доступными именами', async () => {
      seedDevices()
      const stack: DeviceStack = { id: 'stack-1', name: 'Стек ядра', description: null }
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          if (url.includes('/device-stacks/stack-1/detail')) {
            return jsonResponse(
              detailResponse({
                members: [
                  {
                    id: 'dev-1',
                    system_name: 'core-sw-01',
                    serial_number: 'SN-1',
                    device_type_id: 'dt-1',
                    stack_member_id: 'sm-1',
                    stack_position: 1,
                  } as never,
                ],
                connections: [
                  {
                    id: 'conn-1',
                    source_device_name: 'core-sw-01',
                    source_interface_name: 'Te1/0/1',
                    destination_device_name: 'core-sw-02',
                    destination_interface_name: 'Te1/0/2',
                    connection_type_name: 'Оптика',
                  } as never,
                ],
              }),
            )
          }
          return jsonResponse(EMPTY_PAGE)
        }),
      )

      const wrapper = mount(DeviceStackFormModal, { props: { stack } })
      await flushPromises()

      const wraps = wrapper.findAllComponents(ScrollableTableWrap)
      expect(wraps.map((wrap) => wrap.attributes('aria-label'))).toEqual(['Устройства в стеке', 'Соединения стека'])
      for (const wrap of wraps) expect(wrap.find('table.member-table').exists()).toBe(true)
    })

    it('пустые состав и топология таблиц не рисуют — обёртки нет', async () => {
      seedDevices()
      const stack: DeviceStack = { id: 'stack-1', name: 'Стек ядра', description: null }
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => (url.includes('/device-stacks/stack-1/detail') ? jsonResponse(detailResponse()) : jsonResponse(EMPTY_PAGE))),
      )

      const wrapper = mount(DeviceStackFormModal, { props: { stack } })
      await flushPromises()

      expect(wrapper.findAllComponents(ScrollableTableWrap)).toHaveLength(0)
      expect(wrapper.text()).toContain('Устройства не добавлены')
    })

    it('блок со вложенной таблицей может сжиматься в сетке формы: .nested-editor { min-width: 0 }', () => {
      const body = ruleBody(readStyles('src/components/DeviceStackFormModal.vue'), '.nested-editor')
      expect(declaration(body, 'min-width')).toBe('0')
    })
  })

  describe('подтверждение добавления в стек при заданных общих настройках VLAN', () => {
    const stack: DeviceStack = { id: 'stack-1', name: 'Стек ядра', description: null }
    const member = {
      id: 'dev-1',
      system_name: 'core-sw-01',
      serial_number: 'SN-1',
      device_type_id: 'dt-1',
      stack_member_id: 'sm-1',
      stack_position: 1,
    } as never
    const PREVIEW = {
      stack_name: 'Стек ядра',
      device_name: 'core-sw-02',
      already_member: false,
      unchanged_count: 0,
      changes: [
        {
          vlan_id: 'v-10',
          vlan_number: 10,
          vlan_name: 'mgmt',
          action: 'add',
          before: null,
          after: { ip_address: '10.0.10.1', prefix_length: 24, is_management: true },
        },
      ],
    }

    function stubApi(calls: Array<{ url: string; method: string }>, preview: unknown | Response) {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          calls.push({ url, method })
          if (url.includes('/device-stacks/stack-1/detail')) return jsonResponse(detailResponse({ members: [member] }))
          if (url.includes('/members/preview')) return preview instanceof Response ? preview : jsonResponse(preview)
          if (url.includes('/device-stacks/stack-1/vlans')) return jsonResponse({ stack_name: 'Стек ядра', member_count: 1, items: [], available: [] })
          if (method === 'POST' && url.includes('/device-stacks/stack-1/members')) return jsonResponse({ id: 'sm-2' }, 201)
          return jsonResponse(EMPTY_PAGE)
        }),
      )
    }

    async function pickDeviceAndAdd(wrapper: ReturnType<typeof mount>) {
      await wrapper.find('.add-member-row .searchable-select input').trigger('focus')
      await wrapper.find('.add-member-row .ss-option').trigger('mousedown')
      await wrapper.find('.add-member-row > button.btn-secondary').trigger('click')
      await flushPromises()
    }

    const byId = (id: string) => document.body.querySelector(`[data-testid="${id}"]`) as HTMLElement | null
    afterEach(() => {
      document.body.innerHTML = ''
    })

    it('если данные устройства изменятся — показывает окно и НЕ добавляет, пока не подтверждено', async () => {
      seedDevices()
      const calls: Array<{ url: string; method: string }> = []
      stubApi(calls, PREVIEW)
      const wrapper = mount(DeviceStackFormModal, { props: { stack } })
      await flushPromises()

      await pickDeviceAndAdd(wrapper)

      expect(byId('stack-member-confirm')).not.toBeNull()
      expect(byId('stack-member-confirm')?.textContent).toContain('Будет назначен VLAN: 10.0.10.1/24, «Управление»')
      expect(calls.some((c) => c.method === 'POST' && c.url.includes('/members') && !c.url.includes('preview'))).toBe(false)
    })

    it('«Добавить в стек» в окне выполняет POST и закрывает окно', async () => {
      seedDevices()
      const calls: Array<{ url: string; method: string }> = []
      stubApi(calls, PREVIEW)
      const wrapper = mount(DeviceStackFormModal, { props: { stack } })
      await flushPromises()
      await pickDeviceAndAdd(wrapper)

      byId('stack-member-accept')!.click()
      await flushPromises()

      expect(calls.filter((c) => c.method === 'POST' && c.url.includes('/device-stacks/stack-1/members'))).toHaveLength(1)
      expect(byId('stack-member-confirm')).toBeNull()
    })

    it('«Отказаться» закрывает окно, ничего не добавляя', async () => {
      seedDevices()
      const calls: Array<{ url: string; method: string }> = []
      stubApi(calls, PREVIEW)
      const wrapper = mount(DeviceStackFormModal, { props: { stack } })
      await flushPromises()
      await pickDeviceAndAdd(wrapper)

      byId('stack-member-cancel')!.click()
      await flushPromises()

      expect(byId('stack-member-confirm')).toBeNull()
      expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0)
    })

    it('если менять нечего — добавляет сразу, без окна', async () => {
      seedDevices()
      const calls: Array<{ url: string; method: string }> = []
      stubApi(calls, { ...PREVIEW, changes: [], unchanged_count: 2 })
      const wrapper = mount(DeviceStackFormModal, { props: { stack } })
      await flushPromises()

      await pickDeviceAndAdd(wrapper)

      expect(byId('stack-member-confirm')).toBeNull()
      expect(calls.filter((c) => c.method === 'POST' && c.url.includes('/device-stacks/stack-1/members'))).toHaveLength(1)
    })

    it('отказ предпросмотра (устройство в другом стеке / VLAN вне домена) показывается в форме, без окна и без POST', async () => {
      seedDevices()
      const calls: Array<{ url: string; method: string }> = []
      stubApi(calls, jsonResponse({ detail: 'Устройство не входит в домен VLAN: 70' }, 422))
      const wrapper = mount(DeviceStackFormModal, { props: { stack } })
      await flushPromises()

      await pickDeviceAndAdd(wrapper)

      expect(byId('stack-member-confirm')).toBeNull()
      expect(wrapper.text()).toContain('не входит в домен VLAN')
      expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0)
    })
  })

  describe('общие IP-адреса VLAN стека', () => {
    const stack: DeviceStack = { id: 'stack-1', name: 'Стек ядра', description: null }
    const member = {
      id: 'dev-1',
      system_name: 'core-sw-01',
      serial_number: 'SN-1',
      device_type_id: 'dt-1',
      stack_member_id: 'sm-1',
      stack_position: 1,
    } as never

    function stubStackApi(calls: string[]) {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          calls.push(url)
          if (url.includes('/device-stacks/stack-1/detail')) return jsonResponse(detailResponse({ members: [member] }))
          if (url.includes('/device-stacks/stack-1/vlans')) return jsonResponse({ items: [], available: [] })
          return jsonResponse(EMPTY_PAGE)
        }),
      )
    }

    it('при редактировании показывает блок и загружает VLAN стека; при создании блока нет', async () => {
      seedDevices()
      const calls: string[] = []
      stubStackApi(calls)

      const editing = mount(DeviceStackFormModal, { props: { stack } })
      await flushPromises()
      expect(editing.find('[data-testid="stack-vlan-ip-editor"]').exists()).toBe(true)
      expect(calls.some((u) => u.includes('/device-stacks/stack-1/vlans'))).toBe(true)

      const creating = mount(DeviceStackFormModal, { props: { stack: null } })
      await flushPromises()
      expect(creating.find('[data-testid="stack-vlan-ip-editor"]').exists()).toBe(false)
    })

    it('после добавления устройства в стек заново читает VLAN стека (новый участник мог не получить общий адрес)', async () => {
      seedDevices()
      const calls: Array<{ url: string; method: string }> = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          calls.push({ url, method })
          if (url.includes('/device-stacks/stack-1/detail')) return jsonResponse(detailResponse({ members: [member] }))
          if (url.includes('/device-stacks/stack-1/vlans')) return jsonResponse({ items: [], available: [] })
          if (method === 'POST' && url.includes('/device-stacks/stack-1/members')) return jsonResponse({ id: 'sm-2' }, 201)
          return jsonResponse(EMPTY_PAGE)
        }),
      )
      const wrapper = mount(DeviceStackFormModal, { props: { stack } })
      await flushPromises()
      const vlanReads = () => calls.filter((c) => c.method === 'GET' && c.url.includes('/device-stacks/stack-1/vlans')).length
      expect(vlanReads()).toBe(1)

      await wrapper.find('.add-member-row .searchable-select input').trigger('focus')
      await wrapper.find('.add-member-row .ss-option').trigger('mousedown')
      await wrapper.find('.add-member-row > button.btn-secondary').trigger('click')
      await flushPromises()

      expect(vlanReads()).toBe(2)
    })

    it('после применения общего адреса перезагружает список устройств (VLAN и управляющие адреса могли измениться)', async () => {
      seedDevices()
      const calls: string[] = []
      stubStackApi(calls)
      const wrapper = mount(DeviceStackFormModal, { props: { stack } })
      await flushPromises()
      const devicesBefore = calls.filter((u) => u.endsWith('/devices')).length

      wrapper.getComponent(DeviceStackVlanIpEditor).vm.$emit('applied')
      await flushPromises()

      expect(calls.filter((u) => u.endsWith('/devices')).length).toBe(devicesBefore + 1)
    })
  })
})
