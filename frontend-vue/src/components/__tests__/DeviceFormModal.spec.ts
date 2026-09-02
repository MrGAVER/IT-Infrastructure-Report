import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceFormModal from '../DeviceFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useVLANsStore } from '../../stores/vlans'
import { deviceTypesFixture } from '../../stores/__tests__/fixtures'

function stubCatalogsFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/resources/device-types')) return new Response(JSON.stringify(deviceTypesFixture))
      if (/\/resources$/.test(url)) return new Response(JSON.stringify([]))
      return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
    }),
  )
}

// Каждый тест сам грузит справочники под своим стабом fetch, а затем ПОДМЕНЯЕТ
// стаб на выделенный мок для create/update-запроса. unstubGlobals: true в
// vitest.config.ts откатывает vi.stubGlobal между тестами автоматически — важно
// не полагаться на то, какой стаб "утёк" из предыдущего теста (наступили на это
// при живой разработке), а всегда переустанавливать явно внутри каждого it().
beforeEach(() => {
  setActivePinia(createPinia())
})

async function mountWithLoadedCatalogs() {
  stubCatalogsFetch()
  const catalogs = useCatalogsStore()
  await catalogs.ensureLoaded()
  return mount(DeviceFormModal, { props: { device: null } })
}

describe('DeviceFormModal.vue', () => {
  it('не отправляет запрос и показывает ошибку без обязательных полей', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('Укажите тип устройства')
    expect(wrapper.emitted('saved')).toBeFalsy()
  })

  it('успешно создаёт устройство и эмитит saved', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    const postMock = vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'POST' && url.includes('/resources/devices')) {
        return new Response(JSON.stringify({ id: 'new-1', serial_number: 'SN-1' }), { status: 201 })
      }
      return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
    })
    vi.stubGlobal('fetch', postMock)

    await wrapper.find('select').setValue('type:dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-1')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(postMock).toHaveBeenCalledWith(expect.stringContaining('/resources/devices'), expect.objectContaining({ method: 'POST' }))
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('при 409 DUPLICATE_SYSTEM_NAME спрашивает подтверждение и повторяет запрос с флагом', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    // Отдельный счётчик именно для POST /resources/devices — GET-запросы
    // persistOpenPorts() (см. DeviceFormModal.vue) на других URL не должны на него влиять.
    let devicePostCalls = 0
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') !== 'POST' || !url.includes('/resources/devices')) {
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }
      devicePostCalls += 1
      if (devicePostCalls === 1) {
        return new Response(
          JSON.stringify({ detail: { code: 'DUPLICATE_SYSTEM_NAME', message: 'Уже используется. Сохранить дубликат?' } }),
          { status: 409 },
        )
      }
      const body = JSON.parse(init!.body as string)
      expect(body.confirm_system_name_duplicate).toBe(true)
      return new Response(JSON.stringify({ id: 'new-2', serial_number: 'SN-2' }), { status: 201 })
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('confirm', vi.fn(() => true))

    await wrapper.find('select').setValue('type:dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-2')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirm).toHaveBeenCalled()
    expect(devicePostCalls).toBe(2)
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('при отказе от подтверждения дубликата запрос не повторяется', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    // Как и в соседнем тесте выше — считаем только запросы на создание устройства. GET-запросы
    // (в т.ч. загрузка допустимых VLAN типа устройства при выборе select'а ниже, см.
    // DeviceFormModal.vue:watch(form.device_type_id)) не должны влиять на этот счётчик.
    let devicePostCalls = 0
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') !== 'POST' || !url.includes('/resources/devices')) {
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }
      devicePostCalls += 1
      return new Response(JSON.stringify({ detail: { code: 'DUPLICATE_SYSTEM_NAME', message: 'Уже используется.' } }), { status: 409 })
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('confirm', vi.fn(() => false))

    await wrapper.find('select').setValue('type:dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-3')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(devicePostCalls).toBe(1)
    expect(wrapper.emitted('saved')).toBeFalsy()
    expect(wrapper.text()).toContain('Уже используется')
  })

  it('emits close при отмене', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    await wrapper.find('.modal-foot button.btn-secondary').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('при редактировании подгружает существующие открытые порты устройства', async () => {
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()

    const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-9' } as never
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/resources/open-ports')) {
          return new Response(
            JSON.stringify({
              items: [{ id: 'op-1', owner_type: 'physical_device', owner_id: 'dev-1', transport_protocol: 'TCP', port: 22, protocol: 'SSH', protocol_catalog_id: null, ip_address: null, description: null }],
              total: 1,
              offset: 0,
              limit: 1000,
            }),
          )
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()

    expect(wrapper.find('input.col-port').element).toHaveProperty('value', '22')
  })

  it('сохраняет добавленный открытый порт под id нового устройства и не отправляет пустые строки', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    await wrapper.find('button.add-btn').trigger('click') // + Открытый порт, оставляем пустым
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.includes('/resources/devices')) {
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-4' }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    await wrapper.find('select').setValue('type:dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-4')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(calls.some((c) => c.method === 'POST' && c.url.includes('/resources/open-ports'))).toBe(false)
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('сохраняет добавленный программный актив под id нового устройства', async () => {
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()
    catalogs.items['software-assets'] = [{ id: 'sa-ad', name: 'Active Directory' }]
    const wrapper = mount(DeviceFormModal, { props: { device: null } })

    const addButtons = wrapper.findAll('button.add-btn')
    await addButtons[1].trigger('click') // + Программный актив (открытые порты — первая кнопка)
    await wrapper.find('.col-asset select').setValue('sa-ad')

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.includes('/resources/devices')) {
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-5' }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    await wrapper.find('select').setValue('type:dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-5')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const softwareCreate = calls.find((c) => c.method === 'POST' && c.url.includes('/resources/device-software'))
    expect(softwareCreate?.body).toMatchObject({ physical_device_id: 'dev-new', software_asset_id: 'sa-ad' })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('при редактировании подгружает существующие интерфейсы устройства с их IP', async () => {
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()

    const device = { id: 'dev-2', device_type_id: 'dt-server', serial_number: 'SN-10' } as never
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/resources/interfaces')) {
          return new Response(
            JSON.stringify({
              items: [{ id: 'if-1', physical_device_id: 'dev-2', name: 'eth0', interface_type_id: null, mac_address: null, speed_id: null, is_management: false, is_data_transfer: true, description: null }],
              total: 1,
              offset: 0,
              limit: 1000,
            }),
          )
        }
        if (url.includes('/resources/interface-ips')) {
          return new Response(
            JSON.stringify({ items: [{ id: 'ip-1', interface_id: 'if-1', ip_address: '192.168.1.1', prefix_length: 24, purpose: null, is_management: false }], total: 1, offset: 0, limit: 1000 }),
          )
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()

    expect(wrapper.find('.iface-table input.cell-input').element).toHaveProperty('value', 'eth0')
    await wrapper.find('.expand-toggle').trigger('click') // IP-адреса скрыты под toggle (п.3.4)
    expect(wrapper.find('.ip-row input').element).toHaveProperty('value', '192.168.1.1')
  })

  it('сохраняет добавленный интерфейс через PUT /devices/{id}/interfaces', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    await wrapper.find('.empty button.btn-secondary').trigger('click') // + Интерфейс (список пуст)
    await wrapper.find('.iface-table input.cell-input').setValue('eth0')

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.includes('/resources/devices')) {
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-6' }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    await wrapper.find('select').setValue('type:dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-6')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const ifaceCall = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-new/interfaces'))
    expect(ifaceCall?.body).toMatchObject({ interfaces: [{ name: 'eth0', vlan_ids: [], ips: [] }] })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('не стирает VLAN интерфейса, назначенные через /legacy, при сохранении без их редактирования', async () => {
    // Регрессия: backend/app/services/crud.py:_sync_single_interface полностью пересоздаёт
    // InterfaceVLAN из payload['vlan_ids'] при каждом PUT — отправка [] стёрла бы VLAN,
    // назначенные через /legacy, хотя редактор их даже не показывает (см. InterfaceDraftRow
    // в api/types.ts). Загруженные vlan_ids должны уйти обратно без изменений.
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()

    const device = { id: 'dev-3', device_type_id: 'dt-server', serial_number: 'SN-11' } as never
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.includes('/resources/interfaces')) {
          return new Response(
            JSON.stringify({
              items: [{ id: 'if-1', physical_device_id: 'dev-3', name: 'eth0', interface_type_id: null, mac_address: null, speed_id: null, is_management: false, is_data_transfer: false, description: null }],
              total: 1,
              offset: 0,
              limit: 1000,
            }),
          )
        }
        if (url.includes('/resources/interface-vlans')) {
          return new Response(JSON.stringify({ items: [{ id: 'iv-1', interface_id: 'if-1', vlan_id: 'vlan-legacy', mode: 'access' }], total: 1, offset: 0, limit: 1000 }))
        }
        if (method === 'PUT' && url.includes('/resources/devices/dev-3')) {
          return new Response(JSON.stringify(device))
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const ifaceCall = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-3/interfaces'))
    expect(ifaceCall?.body).toMatchObject({ interfaces: [{ id: 'if-1', vlan_ids: ['vlan-legacy'] }] })
  })

  it('чекбоксы "VLAN на порту" показывают только VLAN, разрешённые типом устройства или уже назначенные ему', async () => {
    const vlans = useVLANsStore()
    vlans.groups = [
      { vlan_id: 10, definitions: [{ id: 'v-type', vlan_id: 10, name: 'Каталожный', description: '', domain_id: null, domain_name: '', devices: [] }] },
      { vlan_id: 20, definitions: [{ id: 'v-assigned', vlan_id: 20, name: 'Назначенный', description: '', domain_id: null, domain_name: '', devices: [] }] },
      { vlan_id: 30, definitions: [{ id: 'v-other', vlan_id: 30, name: 'Посторонний', description: '', domain_id: null, domain_name: '', devices: [] }] },
    ]
    vlans.loaded = true
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()

    const device = { id: 'dev-5', device_type_id: 'dt-server', serial_number: 'SN-14' } as never
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/resources/interfaces')) {
          return new Response(
            JSON.stringify({
              items: [{ id: 'if-1', physical_device_id: 'dev-5', name: 'eth0', interface_type_id: null, mac_address: null, speed_id: null, is_management: false, is_data_transfer: false, description: null }],
              total: 1,
              offset: 0,
              limit: 1000,
            }),
          )
        }
        if (url.includes('/resources/device-type-vlans')) {
          return new Response(JSON.stringify({ items: [{ id: 'l-1', device_type_id: 'dt-server', vlan_id: 'v-type' }], total: 1, offset: 0, limit: 1000 }))
        }
        if (url.includes('/resources/device-vlans')) {
          return new Response(
            JSON.stringify({ items: [{ id: 'dv-1', physical_device_id: 'dev-5', vlan_id: 'v-assigned', ip_address: null, prefix_length: null, is_management: false, description: null }], total: 1, offset: 0, limit: 1000 }),
          )
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()
    await wrapper.find('.expand-toggle').trigger('click') // VLAN на порту скрыты под toggle (п.3.4)

    // .iface-detail — иначе подхватились бы ещё и чекбоксы из панели "Массовое редактирование"
    // (тот же vlanOptions используется и там, см. DeviceInterfacesEditor.vue).
    const labels = wrapper.findAll('.iface-detail .vlan-check').map((l) => l.text())
    expect(labels).toEqual(['10 — Каталожный', '20 — Назначенный'])
    expect(labels.some((t) => t.includes('Посторонний'))).toBe(false)
  })

  it('снятие VLAN устройства убирает его из vlan_ids уже заведённого порта при сохранении', async () => {
    // Регрессия для watch(portVlanOptions) в DeviceFormModal.vue: важно сравнивать НОВЫЙ список
    // опций со СТАРЫМ (а не просто фильтровать по текущему), иначе первая же загрузка стёрла бы
    // vlan_ids из /legacy (см. предыдущий тест) — здесь же проверяем, что реальное удаление VLAN
    // устройства ПОСЛЕ загрузки корректно убирает его и из уже заведённого порта.
    const vlans = useVLANsStore()
    vlans.groups = [{ vlan_id: 20, definitions: [{ id: 'v-assigned', vlan_id: 20, name: 'Назначенный', description: '', domain_id: null, domain_name: '', devices: [] }] }]
    vlans.loaded = true
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()

    const device = { id: 'dev-6', device_type_id: 'dt-server', serial_number: 'SN-15' } as never
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.includes('/resources/interfaces') && method === 'GET') {
          return new Response(
            JSON.stringify({
              items: [{ id: 'if-1', physical_device_id: 'dev-6', name: 'eth0', interface_type_id: null, mac_address: null, speed_id: null, is_management: false, is_data_transfer: false, description: null }],
              total: 1,
              offset: 0,
              limit: 1000,
            }),
          )
        }
        if (url.includes('/resources/interface-vlans')) {
          return new Response(JSON.stringify({ items: [{ id: 'iv-1', interface_id: 'if-1', vlan_id: 'v-assigned', mode: null }], total: 1, offset: 0, limit: 1000 }))
        }
        if (url.includes('/resources/device-vlans') && method === 'GET') {
          return new Response(
            JSON.stringify({ items: [{ id: 'dv-1', physical_device_id: 'dev-6', vlan_id: 'v-assigned', ip_address: null, prefix_length: null, is_management: false, description: null }], total: 1, offset: 0, limit: 1000 }),
          )
        }
        if (method === 'PUT' && url.includes('/resources/devices/dev-6')) {
          return new Response(JSON.stringify(device))
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()
    await wrapper.find('.expand-toggle').trigger('click') // VLAN на порту скрыты под toggle (п.3.4)
    expect((wrapper.find('.iface-detail .vlan-check input').element as HTMLInputElement).checked).toBe(true)

    await wrapper.find('.nested-row .icon-btn.danger').trigger('click') // убрать единственный VLAN устройства
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const ifaceCall = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-6/interfaces'))
    expect(ifaceCall?.body).toMatchObject({ interfaces: [{ id: 'if-1', vlan_ids: [] }] })
  })

  it('сохраняет "VLAN устройства" раньше интерфейсов — вновь добавленный VLAN уже в БД к моменту проверки vlan_ids порта', async () => {
    const vlans = useVLANsStore()
    vlans.groups = [{ vlan_id: 10, definitions: [{ id: 'v-new', vlan_id: 10, name: 'Новый', description: '', domain_id: null, domain_name: '', devices: [] }] }]
    vlans.loaded = true
    const wrapper = await mountWithLoadedCatalogs()
    await wrapper.find('.nested-editor:last-of-type button.add-btn').trigger('click') // + VLAN устройства
    await wrapper.find('.col-vlan select').setValue('v-new')

    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        if (method === 'POST' && url.includes('/resources/devices')) {
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-16' }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    await wrapper.find('select').setValue('type:dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-16')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const vlanCreateIndex = calls.findIndex((c) => c.method === 'POST' && c.url.includes('/resources/device-vlans'))
    const interfacesSyncIndex = calls.findIndex((c) => c.method === 'PUT' && c.url.includes('/devices/dev-new/interfaces'))
    expect(vlanCreateIndex).toBeGreaterThanOrEqual(0)
    expect(interfacesSyncIndex).toBeGreaterThan(vlanCreateIndex)
  })

  it('доменный VLAN доступен для выбора только если устройство состоит в этом домене', async () => {
    const vlans = useVLANsStore()
    vlans.groups = [
      { vlan_id: 10, definitions: [{ id: 'v-10', vlan_id: 10, name: 'Мониторинг', description: '', domain_id: null, domain_name: '', devices: [] }] },
      { vlan_id: 20, definitions: [{ id: 'v-20', vlan_id: 20, name: 'Управление', description: '', domain_id: 'dom-1', domain_name: 'Ядро сети', devices: [] }] },
    ]
    vlans.loaded = true

    const device = { id: 'dev-4', device_type_id: 'dt-server', serial_number: 'SN-12' } as never
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        // Устройство НЕ состоит в домене dom-1 — vlan-domain-devices пуст.
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()
    await wrapper.find('.nested-editor:last-of-type button.add-btn').trigger('click') // + VLAN — последний редактор в форме

    const options = wrapper.find('.col-vlan select').findAll('option')
    const texts = options.map((o) => o.text())
    expect(texts.some((t) => t.includes('Мониторинг'))).toBe(true) // без домена — доступен всем
    expect(texts.some((t) => t.includes('Управление'))).toBe(false) // доменный, не участник — скрыт
  })

  it('сохраняет добавленный VLAN устройства под id нового устройства', async () => {
    const vlans = useVLANsStore()
    vlans.groups = [{ vlan_id: 10, definitions: [{ id: 'v-10', vlan_id: 10, name: 'Мониторинг', description: '', domain_id: null, domain_name: '', devices: [] }] }]
    vlans.loaded = true

    const wrapper = await mountWithLoadedCatalogs()
    await wrapper.find('.nested-editor:last-of-type button.add-btn').trigger('click') // + VLAN — последний редактор в форме
    await wrapper.find('.col-vlan select').setValue('v-10')

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.includes('/resources/devices')) {
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-13' }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    await wrapper.find('select').setValue('type:dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-13')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const vlanCreate = calls.find((c) => c.method === 'POST' && c.url.includes('/resources/device-vlans'))
    expect(vlanCreate?.body).toMatchObject({ physical_device_id: 'dev-new', vlan_id: 'v-10' })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('объединённое поле типа/производителя/модели: группа "без модели" не завязана на конкретную модель', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    const select = wrapper.find('.form-grid .lookup-row select')

    const optgroups = select.findAll('optgroup')
    expect(optgroups[0].attributes('label')).toBe('Тип устройства (без конкретной модели)')

    await select.setValue('type:dt-server')
    expect((select.element as HTMLSelectElement).value).toBe('type:dt-server')
  })

  it('быстрое добавление модели устройства синхронизирует тип и производителя формы', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    const catalogs = useCatalogsStore()
    catalogs.items['manufacturers'] = [{ id: 'mf-1', name: 'Dell' }]

    await wrapper.find('.form-grid .lookup-row button').trigger('click') // единственная "+" объединённого поля

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        if (method === 'POST' && url.endsWith('/resources/device-models')) {
          return new Response(JSON.stringify({ id: 'dm-new', device_type_id: 'dt-net', manufacturer_id: 'mf-1', model: 'PowerVault' }), { status: 201 })
        }
        if (method === 'POST' && url.includes('/resources/devices')) {
          return new Response(JSON.stringify({ id: 'new-dev', serial_number: 'SN-77' }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const body = new DOMWrapper(document.body)
    const overlaySelects = body.findAll('.overlay select')
    await overlaySelects[0].setValue('dt-net') // Тип устройства в квик-модалке
    await overlaySelects[1].setValue('mf-1') // Производитель в квик-модалке
    await body.find('.overlay input[type="text"]').setValue('PowerVault')
    await body.find('.overlay form').trigger('submit')
    await flushPromises()

    // Объединённое поле отражает выбранную модель, а не "сырой" device_type_id.
    expect((wrapper.find('.form-grid .lookup-row select').element as HTMLSelectElement).value).toBe('model:dm-new')

    // А device_type_id/manufacturer_id формы реально синхронизированы — проверяем по факту
    // отправленного payload'а, а не по DOM-значению другого select'а (которого больше нет).
    const postMock = fetch as unknown as ReturnType<typeof vi.fn>
    await wrapper.find('input[type="text"]').setValue('SN-77')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const deviceCall = postMock.mock.calls.find(([url, init]) => (init?.method ?? 'GET') === 'POST' && String(url).includes('/resources/devices'))
    const sentBody = JSON.parse(String(deviceCall![1].body))
    expect(sentBody.device_type_id).toBe('dt-net')
    expect(sentBody.manufacturer_id).toBe('mf-1')
    expect(sentBody.model_id).toBe('dm-new')
  })

  it('быстрое добавление здания подставляет его в форму', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/buildings')) {
          return new Response(JSON.stringify({ id: 'b-new', name: 'Корпус Б' }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const buildingRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Здание')!
    await buildingRow.find('button').trigger('click')
    const body = new DOMWrapper(document.body)
    await body.find('.overlay input[type="text"]').setValue('Корпус Б')
    await body.find('.overlay form').trigger('submit')
    await flushPromises()

    expect((buildingRow.find('select').element as HTMLSelectElement).value).toBe('b-new')
  })

  it('быстрое добавление помещения синхронизирует здание формы (п.3.1)', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    const catalogs = useCatalogsStore()
    catalogs.items['buildings'] = [{ id: 'b-1', name: 'Корпус А' }]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/rooms')) {
          return new Response(JSON.stringify({ id: 'room-new', building_id: 'b-1', name: '204' }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const roomRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Помещение')!
    await roomRow.find('button').trigger('click')
    const body = new DOMWrapper(document.body)
    await body.find('.overlay select').setValue('b-1') // Здание в квик-модалке (обязательное fk-поле)
    await body.find('.overlay input[type="text"]').setValue('204')
    await body.find('.overlay form').trigger('submit')
    await flushPromises()

    const buildingRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Здание')!
    expect((buildingRow.find('select').element as HTMLSelectElement).value).toBe('b-1')
    expect((roomRow.find('select').element as HTMLSelectElement).value).toBe('room-new')
  })

  it('быстрое добавление стойки синхронизирует помещение и здание формы (п.3.1)', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    const catalogs = useCatalogsStore()
    catalogs.items['buildings'] = [{ id: 'b-1', name: 'Корпус А' }]
    catalogs.items['rooms'] = [{ id: 'room-1', building_id: 'b-1', name: '204' }]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/racks')) {
          return new Response(JSON.stringify({ id: 'rack-new', room_id: 'room-1', name: 'R-1', height_u: 42 }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const rackRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Стойка')!
    await rackRow.find('button').trigger('click')
    const body = new DOMWrapper(document.body)
    await body.find('.overlay select').setValue('room-1') // Помещение в квик-модалке (обязательное fk-поле)
    await body.find('.overlay input[type="text"]').setValue('R-1')
    await body.find('.overlay form').trigger('submit')
    await flushPromises()

    const buildingRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Здание')!
    const roomRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Помещение')!
    expect((buildingRow.find('select').element as HTMLSelectElement).value).toBe('b-1')
    expect((roomRow.find('select').element as HTMLSelectElement).value).toBe('room-1')
    expect((rackRow.find('select').element as HTMLSelectElement).value).toBe('rack-new')
  })

  // п.3.8: наивный @click.self на подложке закрывал форму при попытке выделить текст внутри
  // карточки, если mouseup (а значит и click) заканчивался за пределами карточки.
  describe('закрытие по клику на подложку (п.3.8)', () => {
    it('закрывает форму по обычному клику на подложку', async () => {
      const wrapper = await mountWithLoadedCatalogs()
      await wrapper.find('.overlay').trigger('mousedown')
      await wrapper.find('.overlay').trigger('click')
      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('НЕ закрывает форму, если mousedown начался внутри карточки (типичная попытка выделить текст)', async () => {
      const wrapper = await mountWithLoadedCatalogs()
      await wrapper.find('.modal-head h2').trigger('mousedown') // mousedown на заголовке ВНУТРИ карточки
      await wrapper.find('.overlay').trigger('click') // click "долетел" до подложки (mouseup был за пределами карточки)
      expect(wrapper.emitted('close')).toBeFalsy()
    })

    it('НЕ закрывает форму по клику внутри самой карточки', async () => {
      const wrapper = await mountWithLoadedCatalogs()
      await wrapper.find('.modal').trigger('mousedown')
      await wrapper.find('.modal').trigger('click')
      expect(wrapper.emitted('close')).toBeFalsy()
    })
  })

  it('быстрое добавление записи протокола/порта автозаполняет строку открытого порта', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    await wrapper.find('button.add-btn').trigger('click') // + Открытый порт — первый add-btn в форме
    await wrapper.find('.col-catalog button').trigger('click') // "+" рядом со справочником в самой строке

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/protocol-port-catalog')) {
          return new Response(JSON.stringify({ id: 'cat-new', port: 3389, protocol_type: 'RDP', description: null }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const body = new DOMWrapper(document.body)
    await body.find('input[type="number"]').setValue('3389')
    await body.find('input[type="text"]').setValue('RDP')
    await body.find('form').trigger('submit')
    await flushPromises()

    expect((wrapper.find('input.col-port').element as HTMLInputElement).value).toBe('3389')
    expect((wrapper.find('input.col-protocol').element as HTMLInputElement).value).toBe('RDP')
  })
})
