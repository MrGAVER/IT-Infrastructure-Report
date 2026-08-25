import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceFormModal from '../DeviceFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
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

    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ detail: { code: 'DUPLICATE_SYSTEM_NAME', message: 'Уже используется.' } }),
          { status: 409 },
        ),
    )
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('confirm', vi.fn(() => false))

    await wrapper.find('select').setValue('dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-3')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(1)
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
    await wrapper.find('select.col-asset').setValue('sa-ad')

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
})
