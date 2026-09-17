import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceFormModal from '../DeviceFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useVLANsStore } from '../../stores/vlans'
import { useVLANDomainsStore } from '../../stores/vlanDomains'
import { useConnectionsStore } from '../../stores/connections'
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
  // QuickAddButton.vue телепортирует QuickAddModal.vue в document.body — без сброса между
  // тестами упавший на середине тест мог бы оставить в body осиротевшую модалку, которую
  // следующий тест ошибочно найдёт первой через document.body.querySelector (см. похожий
  // сброс в QuickAddModal.spec.ts и остальных спеках, тестирующих вложенные квик-модалки).
  document.body.innerHTML = ''
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

  it('при редактировании подгружает существующие открытые порты интерфейса устройства', async () => {
    // Фикс п.1.4 (батч4): открытые порты — свойство интерфейса, а не всего устройства (см.
    // InterfaceDraftRow.open_ports в types.ts) — блок раскрывается вместе с VLAN/IP интерфейса.
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()
    // Правка "убрать текстовые поля Порт/Протокол": подпись выбранной записи в SearchableSelect
    // резолвится по catalogs.protocolPortCatalog (см. OpenPortListEditor.vue:catalogOptions) —
    // stubCatalogsFetch() отдаёт пустой protocol-port-catalog, поэтому запись нужна отдельно.
    catalogs.protocolPortCatalog = [{ id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null }]

    const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-9' } as never
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/resources/interfaces')) {
          return new Response(
            JSON.stringify({
              items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'eth0', interface_type_id: null, mac_address: null, speed_id: null, is_management: false, is_data_transfer: false, description: null, vlan_mode: 'access' }],
              total: 1,
              offset: 0,
              limit: 1000,
            }),
          )
        }
        if (url.includes('/resources/open-ports')) {
          return new Response(
            JSON.stringify({
              items: [{ id: 'op-1', owner_type: 'device_interface', owner_id: 'if-1', transport_protocol: 'TCP', port: 22, protocol: 'SSH', protocol_catalog_id: 'cat-ssh', ip_address: null, description: null }],
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
    await wrapper.find('.expand-toggle').trigger('click') // открытые порты скрыты до раскрытия строки интерфейса

    expect(wrapper.find('.ports-block .searchable-select input').element).toHaveProperty('value', '22 / SSH')
  })

  it('сохраняет добавленный открытый порт интерфейса под id нового устройства и не отправляет пустые строки', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    await wrapper.find('.empty button.btn-secondary').trigger('click') // + Интерфейс (список пуст)
    await wrapper.find('.iface-table tbody tr.iface-row input.cell-input').setValue('eth0') // имя обязательно — иначе validateInterfaceDraftRows не даст сохранить
    await wrapper.find('.expand-toggle').trigger('click')
    await wrapper.find('.ports-block button.add-btn').trigger('click') // + Открытый порт, оставляем пустым

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

    const ifacesPut = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-new/interfaces'))
    expect((ifacesPut?.body as { interfaces: Array<{ open_ports: unknown[] }> })?.interfaces?.[0]?.open_ports).toEqual([])
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('сохраняет добавленный программный актив под id нового устройства', async () => {
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()
    catalogs.items['software-assets'] = [{ id: 'sa-ad', name: 'Active Directory' }]
    const wrapper = mount(DeviceFormModal, { props: { device: null } })

    const addButtons = wrapper.findAll('button.add-btn')
    await addButtons[0].trigger('click') // + Программный актив — единственная кнопка add-btn на пустой форме (открытые порты теперь внутри интерфейса, см. фикс п.1.4)
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

  it('п.3.1: после сохранения устройства catalogs.items[\'interfaces\'] обновляется — без этого поле "Порт" в форме подключения оставалось пустым до перезагрузки страницы', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = [] // как в реальности сразу после старта приложения — у нового устройства портов ещё не видел никто

    await wrapper.find('.empty button.btn-secondary').trigger('click') // + Интерфейс (список пуст)
    await wrapper.find('.iface-table input.cell-input').setValue('eth0')

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        if (method === 'POST' && url.includes('/resources/devices')) {
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-6' }), { status: 201 })
        }
        if (method === 'PUT' && url.includes('/devices/dev-new/interfaces')) {
          return new Response(JSON.stringify({ items: [{ id: 'if-new', physical_device_id: 'dev-new', name: 'eth0', vlan_mode: 'access' }] }))
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    await wrapper.find('select').setValue('type:dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-6')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(catalogs.items['interfaces']).toEqual([{ id: 'if-new', physical_device_id: 'dev-new', name: 'eth0', vlan_mode: 'access' }])
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
    // (тот же vlanOptions используется и там, см. DeviceInterfacesEditor.vue); :not(.vlan-check-all) —
    // исключает сводный чекбокс "Все VLAN" (п.1.4.3.2), это не отдельная опция каталога.
    const labels = wrapper.findAll('.iface-detail .vlan-check:not(.vlan-check-all)').map((l) => l.text())
    expect(labels).toEqual(['10 — Каталожный', '20 — Назначенный'])
    expect(labels.some((t) => t.includes('Посторонний'))).toBe(false)
  })

  it('п.1.3.8: VLAN нового домена, в котором устройство не состоит, остаётся выбираемым и не ломает сохранение', async () => {
    const vlans = useVLANsStore()
    vlans.groups = []
    vlans.loaded = true
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()
    catalogs.items['vlan-domains'] = [{ id: 'domain-x', name: 'Домен X' }]

    const device = { id: 'dev-8', device_type_id: 'dt-server', serial_number: 'SN-20' } as never
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        // Устройство пока НЕ состоит ни в одном домене VLAN — воспроизводит саму суть бага:
        // "в справочнике vlan устройство не добавлено в этот домен".
        if (url.includes('/resources/vlan-domain-devices') && method === 'GET') {
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }
        if (method === 'POST' && url.endsWith('/resources/vlans')) {
          return new Response(JSON.stringify({ id: 'v-new', vlan_id: 55, name: 'Гостевой-X', domain_id: 'domain-x' }), { status: 201 })
        }
        if (url.includes('/vlan-dashboard')) {
          // useVLANsStore().reload() — вызывается из onVlanCreated() в DeviceFormModal.vue сразу
          // после создания, иначе только что заведённый VLAN не попал бы в vlansStore.allDefinitions
          // (а значит и в availableVlans) до следующей полной перезагрузки стора.
          return new Response(
            JSON.stringify({
              items: [{ vlan_id: 55, definitions: [{ id: 'v-new', vlan_id: 55, name: 'Гостевой-X', description: '', domain_id: 'domain-x', domain_name: 'Домен X', devices: [] }] }],
            }),
          )
        }
        if (method === 'PUT' && url.includes('/resources/devices/dev-8')) {
          return new Response(JSON.stringify(device))
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()

    // .add-btn — общий класс у всех nested-editor'ов (Открытые порты/ПО/VLAN и т.п.), поэтому
    // ищем именно блок "VLAN устройства" по его собственному заголовку, а не просто первый попавшийся.
    const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
    await vlanEditor.find('.add-btn').trigger('click') // добавляет пустую строку VLAN устройства
    await vlanEditor.find('.col-vlan button').trigger('click') // "+" у неё — открывает "Добавить: VLAN"
    const body = new DOMWrapper(document.body)
    await body.find('input[type="number"]').setValue(55)
    await body.findAll('input[type="text"]')[0].setValue('Гостевой-X')
    await body.find('.fk-row .searchable-select input').trigger('focus')
    await body.find('.fk-row .ss-option').trigger('mousedown') // единственная опция — "Домен X"
    await body.find('.overlay form').trigger('submit')
    await flushPromises()

    // Фикс п.1.3.8, часть 1: VLAN не выпал из options сразу после создания — есть совпадающий
    // <option>, а не "висящий" vlan_id без него (что визуально выглядело бы как сброс выбора).
    expect(wrapper.find('option[value="v-new"]').exists()).toBe(true)

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // Фикс п.1.3.8, часть 2: устройство реально закреплено за доменом на бэкенде — иначе
    // backend/app/services/crud.py:_validate_physical_device_vlan откатил бы device-vlans
    // с 422 "Устройство не включено в домен этого VLAN".
    const membershipIdx = calls.findIndex((c) => c.method === 'POST' && c.url.endsWith('/resources/vlan-domain-devices'))
    const deviceVlanIdx = calls.findIndex((c) => c.method === 'POST' && c.url.endsWith('/resources/device-vlans'))
    expect(membershipIdx).toBeGreaterThanOrEqual(0)
    expect(calls[membershipIdx].body).toEqual({ physical_device_id: 'dev-8', domain_id: 'domain-x' })
    expect(deviceVlanIdx).toBeGreaterThan(membershipIdx) // порядок важен — см. комментарий в submit()
  })

  it('пункт 3 правки "создание физического устройства": домен VLAN, заведённый вложенным "+" при добавлении VLAN, получает устройство источником и включённую автосинхронизацию', async () => {
    const vlans = useVLANsStore()
    vlans.groups = []
    vlans.loaded = true
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()

    const device = { id: 'dev-9', device_type_id: 'dt-server', serial_number: 'SN-21' } as never
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/vlan-domains')) {
          return new Response(JSON.stringify({ id: 'domain-new', name: 'Домен для dev-9' }), { status: 201 })
        }
        if (method === 'POST' && url.endsWith('/resources/vlans')) {
          return new Response(JSON.stringify({ id: 'v-new', vlan_id: 66, name: 'Новый VLAN', domain_id: 'domain-new' }), { status: 201 })
        }
        if (url.includes('/resources/vlan-domain-devices') && method === 'GET') {
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }
        if (url.includes('/vlan-dashboard')) {
          return new Response(
            JSON.stringify({
              items: [{ vlan_id: 66, definitions: [{ id: 'v-new', vlan_id: 66, name: 'Новый VLAN', description: '', domain_id: 'domain-new', domain_name: 'Домен для dev-9', devices: [] }] }],
            }),
          )
        }
        if (method === 'PUT' && url.includes('/resources/devices/dev-9')) {
          return new Response(JSON.stringify(device))
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()

    const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
    await vlanEditor.find('.add-btn').trigger('click')
    await vlanEditor.find('.col-vlan button').trigger('click') // "+" у VLAN — открывает "Добавить: VLAN"

    const body = new DOMWrapper(document.body)
    // Вложенный "+" у поля "Домен VLAN" ВНУТРИ этой модалки — заводим НОВЫЙ домен, а не выбираем
    // существующий (тем и отличается от соседнего теста "п.1.3.8" выше, где домен уже есть).
    await body.find('button[aria-label="Добавить: Домен VLAN"]').trigger('click')
    const domainModal = body.findAll('.modal')[1]
    await domainModal.find('input[type="text"]').setValue('Домен для dev-9')
    await domainModal.find('form').trigger('submit')
    await flushPromises()

    await body.find('input[type="number"]').setValue(66)
    await body.findAll('input[type="text"]')[0].setValue('Новый VLAN')
    await body.find('.overlay form').trigger('submit')
    await flushPromises()

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // Правка п.3: PUT /resources/vlan-domains/domain-new, а не создание нового домена (тот уже
    // создан вложенным quick-add'ом выше) — частичное обновление source_device_id + auto_sync.
    const domainUpdate = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/resources/vlan-domains/domain-new'))
    expect(domainUpdate?.body).toEqual({ source_device_id: 'dev-9', auto_sync: true })
  })

  it('пункт 3 правки "домен VLAN": кнопка "Включить в домен" в блоке "VLAN устройства" добавляет устройство в существующий домен при сохранении формы', async () => {
    const vlans = useVLANsStore()
    vlans.groups = []
    vlans.loaded = true
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()
    const vlanDomains = useVLANDomainsStore()
    vlanDomains.all = [{ id: 'dom-existing', name: 'Ядро сети', description: null, source_device_id: null, auto_sync: false }]
    vlanDomains.loaded = true

    const device = { id: 'dev-10', device_type_id: 'dt-server', serial_number: 'SN-22' } as never
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.includes('/resources/vlan-domain-devices') && method === 'GET') {
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 })) // устройство пока ни в одном домене
        }
        if (method === 'POST' && url.endsWith('/resources/vlan-domain-devices')) {
          return new Response(JSON.stringify({ id: 'link-new', domain_id: 'dom-existing', physical_device_id: 'dev-10' }), { status: 201 })
        }
        if (method === 'PUT' && url.includes('/resources/devices/dev-10')) {
          return new Response(JSON.stringify(device))
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()

    const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
    await vlanEditor.find('.join-domain-row select').setValue('dom-existing')
    await vlanEditor.find('.join-domain-row button').trigger('click')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const membershipCreate = calls.find((c) => c.method === 'POST' && c.url.endsWith('/resources/vlan-domain-devices'))
    expect(membershipCreate?.body).toEqual({ physical_device_id: 'dev-10', domain_id: 'dom-existing' })
  })

  it('пункт 3: домен, в котором устройство уже состоит, не показывается повторно в списке "Включить в домен"', async () => {
    const vlans = useVLANsStore()
    vlans.groups = []
    vlans.loaded = true
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()
    const vlanDomains = useVLANDomainsStore()
    vlanDomains.all = [{ id: 'dom-a', name: 'Домен А', description: null, source_device_id: null, auto_sync: false }]
    vlanDomains.loaded = true

    const device = { id: 'dev-11', device_type_id: 'dt-server', serial_number: 'SN-23' } as never
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/resources/vlan-domain-devices')) {
          return new Response(JSON.stringify({ items: [{ id: 'link-1', domain_id: 'dom-a', physical_device_id: 'dev-11' }], total: 1, offset: 0, limit: 1000 }))
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()

    const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
    expect(vlanEditor.find('.join-domain-row').exists()).toBe(false)
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

  it('п.1.3.7: option модели показывает производителя целиком ("Cisco WS-C2960-48TD-L"), не только модель', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    const catalogs = useCatalogsStore()
    catalogs.items['manufacturers'] = [{ id: 'mf-cisco', name: 'Cisco' }]
    catalogs.items['device-models'] = [
      { id: 'dm-1', name: 'WS-C2960-48TD-L', manufacturer_id: 'mf-cisco', device_type_id: 'dt-net', model: 'WS-C2960-48TD-L' },
    ]
    await wrapper.vm.$nextTick()

    const select = wrapper.find('.form-grid .lookup-row select')
    const options = select.findAll('option')
    const modelOption = options.find((o) => (o.element as HTMLOptionElement).value === 'model:dm-1')
    expect(modelOption?.text()).toBe('Cisco WS-C2960-48TD-L')
    // Закрытый select после выбора показывает ТОЛЬКО текст option (заголовок optgroup не виден) —
    // это и есть тот сценарий, где раньше терялось "чьё это оборудование".
    await select.setValue('model:dm-1')
    expect(modelOption?.text()).toContain('Cisco')
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
    // п.4: device_type_id/manufacturer_id внутри вложенной квик-модалки — SearchableSelect, а не
    // нативный select; открываем каждый кликом по полю и выбираем нужный вариант из списка.
    const typeSearch = body.findAll('.overlay .searchable-select input')[0]
    await typeSearch.trigger('focus')
    const typeOptions = body.findAll('.overlay .searchable-select')[0].findAll('.ss-option')
    await typeOptions.find((o) => o.text() === 'Сетевое оборудование')!.trigger('mousedown') // dt-net — из deviceTypesFixture

    const mfSearch = body.findAll('.overlay .searchable-select input')[1]
    await mfSearch.trigger('focus')
    await body.findAll('.overlay .searchable-select')[1].find('.ss-option').trigger('mousedown') // Dell — единственный производитель в тесте

    // device-models: после двух SearchableSelect (Тип/Производитель) в DOM идёт обычный input
    // поля "Модель" — он последний среди input[type="text"], а не первый (первые два теперь
    // принадлежат поисковым полям SearchableSelect).
    const overlayTextInputs = body.findAll('.overlay input[type="text"]')
    await overlayTextInputs[overlayTextInputs.length - 1].setValue('PowerVault')
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

  it('п.1.1: поле "Помещение" — SearchableSelect, фильтруется вводом текста', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    const catalogs = useCatalogsStore()
    catalogs.items['buildings'] = [{ id: 'b-1', name: 'Корпус А' }]
    catalogs.items['rooms'] = [
      { id: 'room-1', building_id: 'b-1', name: 'Серверная 101' },
      { id: 'room-2', building_id: 'b-1', name: 'Архив 204' },
    ]
    await wrapper.vm.$nextTick()

    // "Помещение" disabled без выбранного здания — сперва выбираем здание тем же SearchableSelect.
    const buildingRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Здание')!
    await buildingRow.find('.searchable-select input').trigger('focus')
    await buildingRow.find('.ss-option').trigger('mousedown')

    const roomRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Помещение')!
    const roomInput = roomRow.find('.searchable-select input')
    expect(roomInput.attributes('disabled')).toBeUndefined() // разблокировалось после выбора здания
    await roomInput.trigger('focus')
    await roomInput.setValue('Архив')

    const options = roomRow.findAll('.ss-option')
    expect(options).toHaveLength(1)
    expect(options[0].text()).toBe('Архив 204')
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

    // Фикс п.1.1: поле теперь SearchableSelect, не нативный <select> — читаем отображённую
    // подпись выбранной опции через её input, как и везде в тестах SearchableSelect.
    expect((buildingRow.find('.searchable-select input').element as HTMLInputElement).value).toBe('Корпус Б')
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
    // rooms: [building_id (fk, SearchableSelect), name (text)] — Здание в квик-модалке; после
    // поискового поля SearchableSelect'а в DOM идёт обычный input поля "Наименование" — он
    // последний среди input[type="text"], не первый.
    await body.find('.overlay .searchable-select input').trigger('focus')
    await body.find('.overlay .ss-option').trigger('mousedown') // единственный вариант — b-1 "Корпус А"
    const roomTextInputs = body.findAll('.overlay input[type="text"]')
    await roomTextInputs[roomTextInputs.length - 1].setValue('204')
    await body.find('.overlay form').trigger('submit')
    await flushPromises()

    const buildingRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Здание')!
    expect((buildingRow.find('.searchable-select input').element as HTMLInputElement).value).toBe('Корпус А')
    expect((roomRow.find('.searchable-select input').element as HTMLInputElement).value).toBe('204')
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
    // racks: [room_id (fk, SearchableSelect), name (text), height_u (number)] — Помещение;
    // "Наименование" — последний среди input[type="text"], не первый (первый — поиск SearchableSelect).
    await body.find('.overlay .searchable-select input').trigger('focus')
    await body.find('.overlay .ss-option').trigger('mousedown') // единственный вариант — room-1 "204"
    const rackTextInputs = body.findAll('.overlay input[type="text"]')
    await rackTextInputs[rackTextInputs.length - 1].setValue('R-1')
    await body.find('.overlay form').trigger('submit')
    await flushPromises()

    const buildingRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Здание')!
    const roomRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Помещение')!
    expect((buildingRow.find('.searchable-select input').element as HTMLInputElement).value).toBe('Корпус А')
    expect((roomRow.find('.searchable-select input').element as HTMLInputElement).value).toBe('204')
    expect((rackRow.find('.searchable-select input').element as HTMLInputElement).value).toBe('R-1')
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

  it('быстрое добавление записи протокола/порта автозаполняет строку открытого порта интерфейса', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    await wrapper.find('.empty button.btn-secondary').trigger('click') // + Интерфейс (список пуст)
    await wrapper.find('.expand-toggle').trigger('click')
    await wrapper.find('.ports-block button.add-btn').trigger('click') // + Открытый порт
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

    // Правка "убрать текстовые поля Порт/Протокол": больше нет отдельных input'ов для порта и
    // протокола — быстрое добавление подставляет саму запись в SearchableSelect, порт/протокол
    // выведет сервер при сохранении.
    expect(wrapper.find('.ports-block .searchable-select input').element).toHaveProperty('value', '3389 / RDP')
  })

  it('п.3: длинное системное имя показывает подсказку через секунду наведения', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = mount(DeviceFormModal, { props: { device: null } })
      await flushPromises()
      const input = wrapper.find('input[maxlength="255"]:not([required])') // "Системное имя" (в отличие от "Серийный номер", не required)
      await input.setValue('srv-msk-dc-01-very-long-hostname-that-does-not-fit')
      Object.defineProperty(input.element, 'scrollWidth', { value: 300, configurable: true })
      Object.defineProperty(input.element, 'clientWidth', { value: 100, configurable: true })

      await input.trigger('mouseenter')
      vi.advanceTimersByTime(1000)
      expect(document.querySelector('.truncate-tooltip-popup')?.textContent).toBe('srv-msk-dc-01-very-long-hostname-that-does-not-fit')
    } finally {
      vi.useRealTimers()
    }
  })

  describe('фикс п.2: копирование устройства ("copyFrom")', () => {
    const sourceDevice = { id: 'dev-src', device_type_id: 'dt-server', serial_number: 'SN-ORIGINAL', system_name: 'srv-original' } as never

    it('аудит fix/usability-batch4 (находка №5): одновременная передача device и copyFrom — предупреждение в консоль, побеждает device (edit)', async () => {
      stubCatalogsFetch()
      const catalogs = useCatalogsStore()
      await catalogs.ensureLoaded()
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

      const editedDevice = { id: 'dev-edit', device_type_id: 'dt-server', serial_number: 'SN-EDIT', system_name: 'srv-edit' } as never
      const wrapper = mount(DeviceFormModal, { props: { device: editedDevice, copyFrom: sourceDevice } })
      await flushPromises()

      expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('используется device'))
      // device выигрывает как более безопасный исход — это по-прежнему редактирование, а не
      // создание копии с данными донора.
      expect(wrapper.find('h2').text()).toBe('Редактировать устройство')
      expect(wrapper.find('input[required][maxlength="255"]').element).toHaveProperty('value', 'SN-EDIT')
    })

    it('форма открывается в режиме СОЗДАНИЯ (не редактирования), поля донора подставлены, serial_number очищен', async () => {
      stubCatalogsFetch()
      const catalogs = useCatalogsStore()
      await catalogs.ensureLoaded()

      const wrapper = mount(DeviceFormModal, { props: { device: null, copyFrom: sourceDevice } })
      await flushPromises()

      expect(wrapper.find('h2').text()).toBe('Добавить устройство') // не "Редактировать" — это создание нового
      expect(wrapper.find('input[required][maxlength="255"]').element).toHaveProperty('value', '') // Серийный номер — уникален, копировать нельзя
      expect(wrapper.find('input[maxlength="255"]:not([required])').element).toHaveProperty('value', 'srv-original') // Системное имя — скопировано как есть
    })

    it('вложенные строки (порты интерфейса, ПО, интерфейсы, VLAN устройства) грузятся у донора, но сохраняются БЕЗ его id — иначе backend отклонит их как чужие', async () => {
      stubCatalogsFetch()
      const catalogs = useCatalogsStore()
      await catalogs.ensureLoaded()

      const calls: Array<{ url: string; method: string; body?: unknown }> = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
          // Фикс п.1.4 (батч4): открытый порт донора висит на его интерфейсе (owner_type=
          // 'device_interface', owner_id интерфейса), а не на самом устройстве.
          if (url.includes('/resources/open-ports') && method === 'GET') {
            return new Response(JSON.stringify({ items: [{ id: 'op-src', owner_type: 'device_interface', owner_id: 'if-src', transport_protocol: 'TCP', port: 22, protocol: 'SSH', protocol_catalog_id: 'cat-ssh', ip_address: null, description: null }], total: 1, offset: 0, limit: 1000 }))
          }
          if (url.includes('/resources/interfaces') && method === 'GET') {
            return new Response(JSON.stringify({ items: [{ id: 'if-src', physical_device_id: 'dev-src', name: 'eth0', interface_type_id: null, mac_address: null, speed_id: null, is_management: false, is_data_transfer: false, description: null, vlan_mode: 'access' }], total: 1, offset: 0, limit: 1000 }))
          }
          if (method === 'POST' && url.includes('/resources/devices')) {
            return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-NEW' }), { status: 201 })
          }
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )
      // Правка "убрать текстовые поля Порт/Протокол": подпись выбранной записи резолвится по
      // catalogs.protocolPortCatalog — stubCatalogsFetch() отдаёт её пустой.
      catalogs.protocolPortCatalog = [{ id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null }]

      const wrapper = mount(DeviceFormModal, { props: { device: null, copyFrom: sourceDevice } })
      await flushPromises()
      await wrapper.find('.expand-toggle').trigger('click') // порты скрыты до раскрытия строки интерфейса

      // Донор дал открытый порт 22/SSH на интерфейсе eth0 — оба должны были подгрузиться в форму.
      expect(wrapper.find('.ports-block .searchable-select input').element).toHaveProperty('value', '22 / SSH')

      await wrapper.find('input[required][maxlength="255"]').setValue('SN-NEW')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      // Открытые порты больше не PUT'ятся отдельным запросом на /resources/open-ports — они
      // едут атомарно вместе со своим интерфейсом внутри /devices/dev-new/interfaces (см.
      // api/deviceInterfaces.ts:persistDeviceInterfaces), поэтому здесь проверяется только он.
      const ifacesPut = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-new/interfaces'))
      const savedInterface = (ifacesPut?.body as { interfaces: Array<{ id?: string; open_ports: Array<{ id?: string }> }> })?.interfaces?.[0]
      expect(savedInterface?.id).toBeUndefined()
      expect(savedInterface?.open_ports?.[0]?.id).toBeUndefined()
    })

    it('членство донора в домене VLAN переносится как "предстоит создать", а не как уже подтверждённое', async () => {
      stubCatalogsFetch()
      const catalogs = useCatalogsStore()
      await catalogs.ensureLoaded()
      const vlans = useVLANsStore()
      vlans.groups = [{ vlan_id: 77, definitions: [{ id: 'v-domain', vlan_id: 77, name: 'Гостевой', description: '', domain_id: 'domain-x', domain_name: 'Домен X', devices: [] }] }]
      vlans.loaded = true

      const calls: Array<{ url: string; method: string; body?: unknown }> = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
          if (url.includes('/resources/vlan-domain-devices') && method === 'GET') {
            return new Response(JSON.stringify({ items: [{ id: 'link-src', domain_id: 'domain-x', physical_device_id: 'dev-src' }], total: 1, offset: 0, limit: 1000 }))
          }
          if (method === 'POST' && url.includes('/resources/devices')) {
            return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-NEW' }), { status: 201 })
          }
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )

      const wrapper = mount(DeviceFormModal, { props: { device: null, copyFrom: sourceDevice } })
      await flushPromises()

      // VLAN домена, участником которого была ТОЛЬКО донор-запись, уже виден в опциях нового
      // устройства — иначе пользователь не смог бы вообще выбрать унаследованные VLAN донора.
      // Option рендерится на каждой СТРОКЕ "VLAN устройства" (DeviceVlanListEditor.vue) — строк
      // изначально 0 (донор ни одного VLAN устройства не назначал в этом тесте), поэтому сперва
      // добавляем пустую строку кнопкой "+ VLAN", как это сделал бы пользователь.
      const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
      await vlanEditor.find('.add-btn').trigger('click')
      expect(wrapper.find('option[value="v-domain"]').exists()).toBe(true)

      await wrapper.find('input[required][maxlength="255"]').setValue('SN-NEW')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const membershipPost = calls.find((c) => c.method === 'POST' && c.url.endsWith('/resources/vlan-domain-devices'))
      expect(membershipPost?.body).toEqual({ physical_device_id: 'dev-new', domain_id: 'domain-x' })
    })
  })

  describe('фикс п.3.3 (вторая часть): предупреждение при редактировании "Управления"/"Передачи данных"', () => {
    const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' } as never

    it('интерфейс с активным подключением, чьё назначение расходится со "вторым концом", подсвечивается предупреждением', async () => {
      const catalogs = useCatalogsStore()
      catalogs.items['interfaces'] = [
        { id: 'if-this', physical_device_id: 'dev-1', name: 'Gi0/1', is_management: true, is_data_transfer: false, vlan_mode: 'trunk' },
        { id: 'if-other', physical_device_id: 'dev-2', name: 'Gi0/2', is_management: false, is_data_transfer: true, vlan_mode: 'trunk' },
      ] as never
      const connections = useConnectionsStore()
      connections.all = [{ id: 'c-1', source_interface_id: 'if-this', destination_interface_id: 'if-other', is_active: true } as never]
      connections.loaded = true

      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          if (url.includes('/resources/interfaces') && url.includes('dev-1')) {
            return new Response(JSON.stringify({ items: [{ id: 'if-this', physical_device_id: 'dev-1', name: 'Gi0/1', is_management: true, is_data_transfer: false, vlan_mode: 'trunk' }], total: 1, offset: 0, limit: 1000 }))
          }
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )

      const wrapper = mount(DeviceFormModal, { props: { device } })
      await flushPromises()

      const cell = wrapper.find('tr:not(.bulk-edit-row) td.col-check')
      expect(cell.classes()).toContain('has-conflict')
    })

    it('интерфейс без активных подключений — предупреждения нет', async () => {
      const catalogs = useCatalogsStore()
      catalogs.items['interfaces'] = [{ id: 'if-this', physical_device_id: 'dev-1', name: 'Gi0/1', is_management: true, is_data_transfer: false, vlan_mode: 'trunk' }] as never
      const connections = useConnectionsStore()
      connections.all = []
      connections.loaded = true

      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          if (url.includes('/resources/interfaces') && url.includes('dev-1')) {
            return new Response(JSON.stringify({ items: [{ id: 'if-this', physical_device_id: 'dev-1', name: 'Gi0/1', is_management: true, is_data_transfer: false, vlan_mode: 'trunk' }], total: 1, offset: 0, limit: 1000 }))
          }
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )

      const wrapper = mount(DeviceFormModal, { props: { device } })
      await flushPromises()

      expect(wrapper.find('tr:not(.bulk-edit-row) td.col-check').classes()).not.toContain('has-conflict')
    })
  })

  describe('фикс п.2.1.2: новый VLAN устройства автоматически подхватывается портами с "Все VLAN"', () => {
    it('интерфейс в trunk-режиме, где уже выбраны все текущие опции, получает вновь добавленный VLAN устройства', async () => {
      const vlans = useVLANsStore()
      vlans.groups = [{ vlan_id: 10, definitions: [{ id: 'v-old', vlan_id: 10, name: 'Old', description: '', domain_id: null, domain_name: '', devices: [] }] }]
      vlans.loaded = true
      const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' } as never

      const calls: Array<{ url: string; method: string; body?: unknown }> = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
          if (url.includes('/resources/device-types')) return new Response(JSON.stringify(deviceTypesFixture))
          if (/\/resources$/.test(url)) return new Response(JSON.stringify([]))
          // Тип устройства не даёт ни одного VLAN сам по себе — единственный источник portVlanOptions
          // здесь "VLAN устройства" (deviceVlans), это и есть сценарий бага: единственный назначенный
          // VLAN устройства (v-old) уже выбран на порту как "Все VLAN".
          if (url.includes('/resources/device-type-vlans')) return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
          if (url.includes('/resources/device-vlans') && method === 'GET') {
            return new Response(JSON.stringify({ items: [{ id: 'dv-1', physical_device_id: 'dev-1', vlan_id: 'v-old', ip_address: null, prefix_length: null, is_management: false, description: null }], total: 1, offset: 0, limit: 1000 }))
          }
          if (url.includes('/resources/interfaces') && method === 'GET') {
            return new Response(JSON.stringify({ items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'Gi0/1', interface_type_id: null, mac_address: null, speed_id: null, is_management: false, is_data_transfer: false, description: null, vlan_mode: 'trunk' }], total: 1, offset: 0, limit: 1000 }))
          }
          if (url.includes('/resources/interface-vlans') && method === 'GET') {
            return new Response(JSON.stringify({ items: [{ id: 'iv-1', interface_id: 'if-1', vlan_id: 'v-old', mode: 'trunk' }], total: 1, offset: 0, limit: 1000 }))
          }
          if (url.includes('/vlan-dashboard')) {
            return new Response(
              JSON.stringify({
                items: [
                  { vlan_id: 10, definitions: [{ id: 'v-old', vlan_id: 10, name: 'Old', description: '', domain_id: null, domain_name: '', devices: [] }] },
                  { vlan_id: 20, definitions: [{ id: 'v-new', vlan_id: 20, name: 'New', description: '', domain_id: null, domain_name: '', devices: [] }] },
                ],
              }),
            )
          }
          if (method === 'POST' && url.endsWith('/resources/vlans')) {
            return new Response(JSON.stringify({ id: 'v-new', vlan_id: 20, name: 'New', domain_id: null }), { status: 201 })
          }
          if (method === 'PUT' && url.endsWith('/resources/devices/dev-1')) {
            return new Response(JSON.stringify(device))
          }
          if (method === 'PUT' && url.includes('/devices/dev-1/interfaces')) {
            return new Response(JSON.stringify({ items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'Gi0/1', vlan_mode: 'trunk' }] }))
          }
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )

      const wrapper = mount(DeviceFormModal, { props: { device } })
      await flushPromises()

      // Добавляем новый VLAN устройства через "+ VLAN" в блоке "VLAN устройства". Один VLAN
      // (v-old) там уже есть (donor row из GET device-vlans) — .col-vlan button берём ПОСЛЕДНЮЮ
      // (только что добавленную пустую строку), а не первую (иначе квик-адд откроется у уже
      // существующей строки v-old и перезапишет её вместо того, чтобы добавить новую).
      const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
      await vlanEditor.find('.add-btn').trigger('click')
      const quickAddButtons = vlanEditor.findAll('.col-vlan button')
      await quickAddButtons[quickAddButtons.length - 1].trigger('click')
      const body = new DOMWrapper(document.body)
      await body.find('input[type="number"]').setValue(20)
      await body.findAll('input[type="text"]')[0].setValue('New')
      await body.find('.overlay form').trigger('submit')
      await flushPromises()

      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const ifacesPut = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-1/interfaces'))
      const savedRow = (ifacesPut!.body as { interfaces: Array<{ id: string; vlan_ids: string[] }> }).interfaces.find((r) => r.id === 'if-1')
      expect(savedRow!.vlan_ids).toEqual(expect.arrayContaining(['v-old', 'v-new']))
    })
  })

  describe('фикс п.2.2: новый VLAN наследует единственный домен устройства', () => {
    it('устройство состоит ровно в одном домене — поле домена в форме добавления VLAN предзаполнено им', async () => {
      const catalogs = useCatalogsStore()
      catalogs.items['vlan-domains'] = [{ id: 'domain-x', name: 'Домен X' }]
      const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' } as never

      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          if (url.includes('/resources/vlan-domain-devices') && url.includes('dev-1')) {
            return new Response(JSON.stringify({ items: [{ id: 'link-1', domain_id: 'domain-x', physical_device_id: 'dev-1' }], total: 1, offset: 0, limit: 1000 }))
          }
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )

      const wrapper = mount(DeviceFormModal, { props: { device } })
      await flushPromises()

      const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
      await vlanEditor.find('.add-btn').trigger('click')
      await vlanEditor.find('.col-vlan button').trigger('click')

      const domainInput = new DOMWrapper(document.body).find('.fk-row .searchable-select input')
      expect((domainInput.element as HTMLInputElement).value).toBe('Домен X')
    })

    it('устройство ни в одном домене — поле домена пустое', async () => {
      const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' } as never
      vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))))

      const wrapper = mount(DeviceFormModal, { props: { device } })
      await flushPromises()

      const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
      await vlanEditor.find('.add-btn').trigger('click')
      await vlanEditor.find('.col-vlan button').trigger('click')

      const domainInput = new DOMWrapper(document.body).find('.fk-row .searchable-select input')
      expect((domainInput.element as HTMLInputElement).value).toBe('')
    })
  })

  describe('фикс п.3: валидация IP-адреса/префикса в блоке "VLAN устройства"', () => {
    it('не сохраняет устройство с некорректным IP-адресом на VLAN устройства', async () => {
      const wrapper = await mountWithLoadedCatalogs()
      await wrapper.find('select').setValue('type:dt-server')
      await wrapper.find('input[type="text"]').setValue('SN-1')

      const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
      await vlanEditor.find('.add-btn').trigger('click')
      await vlanEditor.find('input.col-ip').setValue('не ip адрес')

      const fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(fetchMock).not.toHaveBeenCalled()
      expect(wrapper.text()).toContain('Некорректный IP-адрес')
    })

    it('не сохраняет устройство с некорректным префиксом на VLAN устройства', async () => {
      const wrapper = await mountWithLoadedCatalogs()
      await wrapper.find('select').setValue('type:dt-server')
      await wrapper.find('input[type="text"]').setValue('SN-1')

      const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
      await vlanEditor.find('.add-btn').trigger('click')
      await vlanEditor.find('input.col-ip').setValue('10.0.0.1')
      await vlanEditor.find('input[placeholder="Префикс"]').setValue('999')

      const fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(fetchMock).not.toHaveBeenCalled()
      expect(wrapper.text()).toContain('Некорректный префикс')
    })
  })
})
