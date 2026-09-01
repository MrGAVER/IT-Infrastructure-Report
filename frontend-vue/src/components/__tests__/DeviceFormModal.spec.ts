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

    await wrapper.find('select').setValue('dt-server')
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

    await wrapper.find('select').setValue('dt-server')
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

    await wrapper.find('select').setValue('dt-server')
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

    await wrapper.find('select').setValue('dt-server')
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

    await wrapper.find('select').setValue('dt-server')
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

    expect(wrapper.find('.iface-card input[type="text"]').element).toHaveProperty('value', 'eth0')
    expect(wrapper.find('.ip-row input').element).toHaveProperty('value', '192.168.1.1')
  })

  it('сохраняет добавленный интерфейс через PUT /devices/{id}/interfaces', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    await wrapper.find('.generator').findAll('button.btn-secondary')[1].trigger('click') // + Интерфейс
    await wrapper.find('.iface-card input[type="text"]').setValue('eth0')

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

    await wrapper.find('select').setValue('dt-server')
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

    // .iface-card — иначе подхватились бы ещё и чекбоксы из панели "Массовое редактирование"
    // (тот же vlanOptions используется и там, см. DeviceInterfacesEditor.vue).
    const labels = wrapper.findAll('.iface-card .vlan-check').map((l) => l.text())
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
    expect((wrapper.find('.iface-card .vlan-check input').element as HTMLInputElement).checked).toBe(true)

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

    await wrapper.find('select').setValue('dt-server')
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

    await wrapper.find('select').setValue('dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-13')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const vlanCreate = calls.find((c) => c.method === 'POST' && c.url.includes('/resources/device-vlans'))
    expect(vlanCreate?.body).toMatchObject({ physical_device_id: 'dev-new', vlan_id: 'v-10' })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('быстрое добавление типа устройства подставляет его в форму', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/device-types')) {
          return new Response(JSON.stringify({ id: 'dt-new', name: 'Маршрутизатор' }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    await wrapper.find('.lookup-row button').trigger('click') // "+" рядом с типом устройства — первое поле формы
    // QuickAddModal.vue телепортируется в document.body (иначе <form> внутри <form> — HTML не
    // допускает вложенные формы), поэтому wrapper.find() его не видит — ищем через DOMWrapper.
    const body = new DOMWrapper(document.body)
    await body.find('.overlay input[type="text"]').setValue('Маршрутизатор')
    await body.find('.overlay form').trigger('submit')
    await flushPromises()

    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('dt-new')
  })

  it('быстрое добавление модели устройства синхронизирует тип устройства формы', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    const catalogs = useCatalogsStore()
    catalogs.items['manufacturers'] = [{ id: 'mf-1', name: 'Dell' }]

    const lookupRows = wrapper.findAll('.lookup-row')
    await lookupRows[2].find('button').trigger('click') // 0=тип, 1=производитель, 2=модель

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/device-models')) {
          return new Response(JSON.stringify({ id: 'dm-new', device_type_id: 'dt-net', manufacturer_id: 'mf-1', model: 'PowerVault' }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const body = new DOMWrapper(document.body)
    const overlaySelects = body.findAll('.overlay select')
    await overlaySelects[0].setValue('dt-net') // Тип устройства в квик-модалке — отличается от dt-server, уже выбранного в основной форме
    await overlaySelects[1].setValue('mf-1') // Производитель
    await body.find('.overlay input[type="text"]').setValue('PowerVault')
    await body.find('.overlay form').trigger('submit')
    await flushPromises()

    const selects = wrapper.findAll('select')
    expect((selects[0].element as HTMLSelectElement).value).toBe('dt-net') // Тип устройства формы синхронизирован
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
