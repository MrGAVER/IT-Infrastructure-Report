import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceFormModal from '../DeviceFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useVLANsStore } from '../../stores/vlans'
import { useVLANDomainsStore } from '../../stores/vlanDomains'
import { usePreferencesStore } from '../../stores/preferences'
import { useConnectionsStore } from '../../stores/connections'
import { useDevicesStore } from '../../stores/devices'
import { deviceTypesFixture } from '../../stores/__tests__/fixtures'
import { useToast } from '../../composables/useToast'
import { usePortSyncPlanRequest } from '../../composables/usePortSyncPlanRequest'

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

// Поле VLAN в строке блока "VLAN устройства" — SearchableSelect (поиск вводом текста), а не
// нативный <select>: значение выбирается фокусом на поле и mousedown по опции, а выбранный VLAN
// виден только как подпись в поле. Хелперы ниже делают это так же, как пользователь.
interface VlanScope {
  findAll(selector: string): DOMWrapper<Element>[]
}
async function pickVlan(scope: VlanScope, labelPart: string, rowIndex = 0) {
  const select = scope.findAll('.col-vlan .searchable-select')[rowIndex]
  await select.find('input').trigger('focus')
  const option = select.findAll('.ss-option').find((o) => o.text().includes(labelPart))
  if (!option) throw new Error(`VLAN «${labelPart}» нет в списке выбора`)
  await option.trigger('mousedown')
}
function vlanRowLabels(scope: VlanScope): string[] {
  return scope.findAll('.col-vlan .searchable-select input').map((i) => (i.element as HTMLInputElement).value)
}
async function vlanChoices(scope: VlanScope, rowIndex = 0): Promise<string[]> {
  const select = scope.findAll('.col-vlan .searchable-select')[rowIndex]
  await select.find('input').trigger('focus')
  return select.findAll('.ss-option').map((o) => o.text())
}

// Поле «Тип / производитель / модель» — SearchableSelect: пользователь фокусирует поле и нажимает на опцию
// (mousedown), как у VLAN выше. label — подпись опции в списке: «Сервер» (тип без модели) или «Cisco WS-C2960».
async function pickTypeModel(wrapper: VueWrapper, label: string) {
  const field = wrapper.find('.form-grid .lookup-row .searchable-select')
  await field.find('input').trigger('focus')
  const option = field.findAll('.ss-option').find((o) => o.text() === label)
  if (!option) throw new Error(`Опции «${label}» нет в поле «Тип / производитель / модель»`)
  await option.trigger('mousedown')
}

// Серийный номер — по подписи поля: первое текстовое поле формы теперь поисковое «Тип / производитель / модель».
async function setSerial(wrapper: VueWrapper, value: string) {
  const field = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Серийный номер *')
  if (!field) throw new Error('Поле «Серийный номер» не найдено')
  await field.find('input').setValue(value)
}

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

    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-1')
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
        return new Response(JSON.stringify({ detail: { code: 'DUPLICATE_SYSTEM_NAME', message: 'Уже используется. Сохранить дубликат?' } }), { status: 409 })
      }
      const body = JSON.parse(init!.body as string)
      expect(body.confirm_system_name_duplicate).toBe(true)
      return new Response(JSON.stringify({ id: 'new-2', serial_number: 'SN-2' }), { status: 201 })
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    )

    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-2')
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
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    )

    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-3')
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
              items: [
                {
                  id: 'if-1',
                  physical_device_id: 'dev-1',
                  name: 'eth0',
                  interface_type_id: null,
                  mac_address: null,
                  speed_id: null,
                  is_management: false,
                  is_data_transfer: false,
                  description: null,
                  vlan_mode: 'access',
                },
              ],
              total: 1,
              offset: 0,
              limit: 1000,
            }),
          )
        }
        if (url.includes('/interface-open-ports')) {
          return new Response(
            JSON.stringify({
              items: [
                {
                  id: 'op-1',
                  owner_type: 'device_interface',
                  owner_id: 'if-1',
                  transport_protocol: 'TCP',
                  port: 22,
                  protocol: 'SSH',
                  protocol_catalog_id: 'cat-ssh',
                  ip_address: null,
                  description: null,
                },
              ],
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

    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-4')
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
    // Поле ПО — SearchableSelect: выбираем опцию по подписи, а не по порядку (в каталоге их может быть больше одной).
    await wrapper.find('.col-asset .searchable-select input').trigger('focus')
    await wrapper
      .findAll('.col-asset .ss-option')
      .find((o) => o.text() === 'Active Directory')!
      .trigger('mousedown')

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

    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-5')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // ПО уходит одним PUT под id нового устройства, а не отдельными POST /resources/deployed-software.
    const softwareSync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/devices/dev-new/deployed-software'))
    expect(softwareSync?.body).toEqual({ deployed_software: [{ software_asset_id: 'sa-ad', version: null }] })
    expect(calls.some((c) => c.method !== 'GET' && c.url.includes('/resources/deployed-software'))).toBe(false)
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('новое устройство без заполненного ПО: запросов к deployed-software нет вовсе', async () => {
    stubCatalogsFetch()
    await useCatalogsStore().ensureLoaded()
    const wrapper = mount(DeviceFormModal, { props: { device: null } })
    await wrapper.findAll('button.add-btn')[0].trigger('click') // + Программный актив, оставляем пустым

    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        if (method === 'POST' && url.includes('/resources/devices'))
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-6' }), { status: 201 })
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-6')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(calls.some((c) => c.method !== 'GET' && c.url.includes('deployed-software'))).toBe(false)
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  describe('ПО существующего устройства сохраняется без удаления и пересоздания', () => {
    const device = { id: 'dev-sw', device_type_id: 'dt-server', serial_number: 'SN-SW' } as never
    const apiSoftware = (id: string, assetId: string, version: string | null) => ({
      id,
      owner_type: 'physical_device',
      owner_id: 'dev-sw',
      software_asset_id: assetId,
      version,
    })

    async function mountWithSoftware(software: unknown[]) {
      stubCatalogsFetch()
      await useCatalogsStore().ensureLoaded()
      const calls: Array<{ url: string; method: string; body?: unknown }> = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
          if (method === 'GET' && url.includes('/resources/deployed-software'))
            return new Response(JSON.stringify({ items: software, total: software.length, offset: 0, limit: 1000 }))
          if (method === 'PUT' && url.endsWith('/devices/dev-sw/deployed-software')) return new Response(JSON.stringify({ items: [] }))
          if (method === 'PUT' && url.includes('/resources/devices/dev-sw')) return new Response(JSON.stringify({ id: 'dev-sw', serial_number: 'SN-SW' }))
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )
      const wrapper = mount(DeviceFormModal, { props: { device } })
      await flushPromises()
      return { wrapper, calls }
    }

    it('один PUT с id сохранённой записи, без DELETE и POST', async () => {
      const { wrapper, calls } = await mountWithSoftware([apiSoftware('sw-old', 'sa-ad', '2022')])

      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const sync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/devices/dev-sw/deployed-software'))
      expect(sync?.body).toEqual({ deployed_software: [{ id: 'sw-old', software_asset_id: 'sa-ad', version: '2022' }] })
      expect(calls.some((c) => c.method === 'DELETE' || (c.method === 'POST' && c.url.includes('/resources/deployed-software')))).toBe(false)
      expect(wrapper.emitted('saved')).toBeTruthy()
    })

    it('ПО, убранное в форме, в запрос не попадает; пустой список снимает всё ПО', async () => {
      const { wrapper, calls } = await mountWithSoftware([apiSoftware('sw-1', 'sa-ad', null), apiSoftware('sw-2', 'sa-nginx', '1.25')])

      await wrapper.findAll('button[aria-label="Удалить программный актив"]')[0].trigger('click')
      await wrapper.find('form').trigger('submit')
      await flushPromises()
      expect(calls.find((c) => c.method === 'PUT' && c.url.endsWith('/devices/dev-sw/deployed-software'))?.body).toEqual({
        deployed_software: [{ id: 'sw-2', software_asset_id: 'sa-nginx', version: '1.25' }],
      })
      expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    })

    it('все строки убраны: PUT с пустым списком', async () => {
      const { wrapper, calls } = await mountWithSoftware([apiSoftware('sw-1', 'sa-ad', null)])

      await wrapper.find('button[aria-label="Удалить программный актив"]').trigger('click')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(calls.find((c) => c.method === 'PUT' && c.url.endsWith('/devices/dev-sw/deployed-software'))?.body).toEqual({ deployed_software: [] })
    })
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
              items: [
                {
                  id: 'if-1',
                  physical_device_id: 'dev-2',
                  name: 'eth0',
                  interface_type_id: null,
                  mac_address: null,
                  speed_id: null,
                  is_management: false,
                  is_data_transfer: true,
                  description: null,
                },
              ],
              total: 1,
              offset: 0,
              limit: 1000,
            }),
          )
        }
        if (url.includes('/interface-ips')) {
          return new Response(
            JSON.stringify({
              items: [
                {
                  id: 'ip-1',
                  owner_type: 'device_interface',
                  owner_id: 'if-1',
                  ip_address: '192.168.1.1',
                  prefix_length: 24,
                  purpose: null,
                  is_management: false,
                },
              ],
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

    expect(wrapper.find('.iface-table input.cell-input').element).toHaveProperty('value', 'eth0')
    await wrapper.find('.expand-toggle').trigger('click') // IP-адреса скрыты под toggle (п.3.4)
    expect(wrapper.find('.ip-row input').element).toHaveProperty('value', '192.168.1.1')
  })

  describe('группы портов (правка формы устройства, п.4)', () => {
    const groupDto = {
      id: 'g-1',
      physical_device_id: 'dev-g',
      name: 'Серверные',
      vlan_mode: null,
      vlan_ids: [],
      ips: [{ id: 'gip-1', ip_address: '10.0.0.5', prefix_length: 24, purpose: null }],
      manage_open_ports: false,
      open_ports: [],
    }
    const ifaceDto = (id: string, name: string, groupId: string | null) => ({
      id,
      physical_device_id: 'dev-g',
      name,
      interface_type_id: null,
      mac_address: null,
      speed_id: null,
      is_management: false,
      is_data_transfer: false,
      description: null,
      vlan_mode: 'access',
      group_id: groupId,
    })
    const device = { id: 'dev-g', device_type_id: 'dt-server', serial_number: 'SN-G' } as never

    async function mountWithGroups(props: { device: never | null; copyFrom?: never | null }, calls: Array<{ url: string; method: string; body?: unknown }>) {
      stubCatalogsFetch()
      await useCatalogsStore().ensureLoaded()
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
          if (url.includes('/devices/dev-g/interface-groups')) return new Response(JSON.stringify({ items: [groupDto] }))
          if (url.includes('/resources/interfaces') && method === 'GET') {
            return new Response(
              JSON.stringify({ items: [ifaceDto('if-1', 'Gi0/1', 'g-1'), ifaceDto('if-2', 'Gi0/2', null)], total: 2, offset: 0, limit: 1000 }),
            )
          }
          if (url.includes('/interface-ips') && method === 'GET') {
            return new Response(
              JSON.stringify({
                items: [
                  {
                    id: 'ip-1',
                    owner_type: 'device_interface',
                    owner_id: 'if-1',
                    ip_address: '10.0.0.5',
                    prefix_length: 24,
                    purpose: null,
                    is_management: false,
                  },
                ],
                total: 1,
                offset: 0,
                limit: 1000,
              }),
            )
          }
          if (method === 'PUT' && url.includes('/devices/dev-g/interfaces')) return new Response(JSON.stringify({ items: [], groups: [] }))
          if (method === 'POST' && url.includes('/resources/devices'))
            return new Response(JSON.stringify({ id: 'dev-copy', serial_number: 'SN-COPY' }), { status: 201 })
          if (method === 'PUT' && url.includes('/resources/devices/dev-g')) return new Response(JSON.stringify({ id: 'dev-g', serial_number: 'SN-G' }))
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )
      const wrapper = mount(DeviceFormModal, { props })
      await flushPromises()
      return wrapper
    }

    it('редактирование: группы загружаются, порт показывает свою группу, а при сохранении группы и group_key уходят одним PUT', async () => {
      const calls: Array<{ url: string; method: string; body?: unknown }> = []
      const wrapper = await mountWithGroups({ device }, calls)

      expect(wrapper.find('.groups-panel').text()).toContain('Серверные')
      expect(wrapper.findAll('.expand-toggle').map((b) => b.text())[0]).toContain('Группа «Серверные»')

      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-g/interfaces'))
      const body = put?.body as { groups: Array<Record<string, unknown>>; interfaces: Array<{ name: string; group_key: string | null }> }
      expect(body.groups).toEqual([
        expect.objectContaining({
          id: 'g-1',
          key: 'g-1',
          name: 'Серверные',
          ips: [expect.objectContaining({ id: 'gip-1', ip_address: '10.0.0.5', prefix_length: 24 })],
          vlan_mode: null,
        }),
      ])
      expect(body.interfaces.map((i) => [i.name, i.group_key])).toEqual([
        ['Gi0/1', 'g-1'],
        ['Gi0/2', null],
      ])
    })

    it('копирование устройства: группы донора создаются заново без id, порты перевязываются на новые ключи', async () => {
      const calls: Array<{ url: string; method: string; body?: unknown }> = []
      const wrapper = await mountWithGroups({ device: null, copyFrom: device }, calls)

      await wrapper.find('input[required][maxlength="255"]').setValue('SN-COPY')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-copy/interfaces'))
      const body = put?.body as {
        groups: Array<{ id?: string; key: string; name: string }>
        interfaces: Array<{ id?: string; name: string; group_key: string | null }>
      }
      expect(body.groups).toHaveLength(1)
      expect(body.groups[0].id).toBeUndefined()
      expect(body.groups[0].key).not.toBe('g-1')
      expect(body.interfaces.map((i) => [i.id, i.name, i.group_key])).toEqual([
        [undefined, 'Gi0/1', body.groups[0].key],
        [undefined, 'Gi0/2', null],
      ])
    })

    it('группа с некорректным IP не применяется: окно группы остаётся открытым, запрос сохранения не уходит', async () => {
      const calls: Array<{ url: string; method: string; body?: unknown }> = []
      const wrapper = await mountWithGroups({ device }, calls)

      await wrapper.find('button[aria-label="Изменить группу"]').trigger('click')
      await wrapper.find('input[aria-label="Общий IP-адрес группы"]').setValue('999.1.1.1')
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      // Некорректный IP отсекается уже при применении группы — в форме остаётся прежнее значение.
      expect(wrapper.find('.group-modal').exists()).toBe(true)
      expect(calls.some((c) => c.method === 'PUT' && c.url.includes('/interfaces'))).toBe(false)
    })
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

    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-6')
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

    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-6')
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
              items: [
                {
                  id: 'if-1',
                  physical_device_id: 'dev-3',
                  name: 'eth0',
                  interface_type_id: null,
                  mac_address: null,
                  speed_id: null,
                  is_management: false,
                  is_data_transfer: false,
                  description: null,
                },
              ],
              total: 1,
              offset: 0,
              limit: 1000,
            }),
          )
        }
        if (url.includes('/devices/dev-3/interface-vlans')) {
          return new Response(JSON.stringify({ items: [{ interface_id: 'if-1', all_vlans: false, vlan_ids: ['vlan-legacy'] }] }))
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
              items: [
                {
                  id: 'if-1',
                  physical_device_id: 'dev-5',
                  name: 'eth0',
                  interface_type_id: null,
                  mac_address: null,
                  speed_id: null,
                  is_management: false,
                  is_data_transfer: false,
                  description: null,
                },
              ],
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
            JSON.stringify({
              items: [
                {
                  id: 'dv-1',
                  physical_device_id: 'dev-5',
                  vlan_id: 'v-assigned',
                  ip_address: null,
                  prefix_length: null,
                  is_management: false,
                  description: null,
                },
              ],
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
    await wrapper.find('.expand-toggle').trigger('click') // VLAN на порту скрыты под toggle (п.3.4)

    // Список VLAN trunk-порта — во всплывающем окне (PortVlanPickerModal), а не в карточке порта; :not(.vlan-check-all) —
    // исключает сводный чекбокс "Все VLAN" (п.1.4.3.2), это не отдельная опция каталога.
    await wrapper.find('.iface-detail .vlan-picker-btn').trigger('click')
    const labels = wrapper.findAll('.vlan-picker-modal .vlan-check:not(.vlan-check-all)').map((l) => l.text())
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
              items: [
                {
                  vlan_id: 55,
                  definitions: [{ id: 'v-new', vlan_id: 55, name: 'Гостевой-X', description: '', domain_id: 'domain-x', domain_name: 'Домен X', devices: [] }],
                },
              ],
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
    await body.find('.modal-overlay form').trigger('submit')
    await flushPromises()

    // Фикс п.1.3.8, часть 1: VLAN не выпал из опций сразу после создания — он подставился в
    // строку подписью, а не "висящим" vlan_id без неё (что визуально выглядело бы как сброс
    // выбора), и остаётся в списке доступных VLAN: пока он занят первой строкой, в новой его не
    // предлагают (правило «как у открытых портов»), а стоит строку убрать — он снова в списке выбора.
    expect(vlanRowLabels(wrapper)).toEqual(['55 — Гостевой-X [Домен X]'])
    await vlanEditor.find('.add-btn').trigger('click')
    expect(await vlanChoices(wrapper, 1)).not.toContain('55 — Гостевой-X [Домен X]')
    await vlanEditor.find('.nested-row .icon-btn.danger').trigger('click') // убрать первую строку с VLAN 55
    expect(await vlanChoices(wrapper, 0)).toContain('55 — Гостевой-X [Домен X]')
    await pickVlan(wrapper, '55 — Гостевой-X [Домен X]', 0) // назначаем снова — дальше проверяется сохранение

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // Фикс п.1.3.8, часть 2: устройство реально закреплено за доменом на бэкенде — иначе
    // backend/app/services/crud.py:_validate_physical_device_vlan откатил бы PUT /devices/{id}/vlans
    // с 422 "Устройство не включено в домен этого VLAN".
    const membershipIdx = calls.findIndex((c) => c.method === 'POST' && c.url.endsWith('/resources/vlan-domain-devices'))
    const deviceVlanIdx = calls.findIndex((c) => c.method === 'PUT' && c.url.endsWith('/devices/dev-8/vlans'))
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
              items: [
                {
                  vlan_id: 66,
                  definitions: [
                    { id: 'v-new', vlan_id: 66, name: 'Новый VLAN', description: '', domain_id: 'domain-new', domain_name: 'Домен для dev-9', devices: [] },
                  ],
                },
              ],
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
    await body.find('.modal-overlay form').trigger('submit')
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
    vlans.groups = [
      { vlan_id: 20, definitions: [{ id: 'v-assigned', vlan_id: 20, name: 'Назначенный', description: '', domain_id: null, domain_name: '', devices: [] }] },
    ]
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
              items: [
                {
                  id: 'if-1',
                  physical_device_id: 'dev-6',
                  name: 'eth0',
                  interface_type_id: null,
                  mac_address: null,
                  speed_id: null,
                  is_management: false,
                  is_data_transfer: false,
                  description: null,
                },
              ],
              total: 1,
              offset: 0,
              limit: 1000,
            }),
          )
        }
        if (url.includes('/devices/dev-6/interface-vlans')) {
          return new Response(JSON.stringify({ items: [{ interface_id: 'if-1', all_vlans: false, vlan_ids: ['v-assigned'] }] }))
        }
        if (url.includes('/resources/device-vlans') && method === 'GET') {
          return new Response(
            JSON.stringify({
              items: [
                {
                  id: 'dv-1',
                  physical_device_id: 'dev-6',
                  vlan_id: 'v-assigned',
                  ip_address: null,
                  prefix_length: null,
                  is_management: false,
                  description: null,
                },
              ],
              total: 1,
              offset: 0,
              limit: 1000,
            }),
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
    // Чекбокс самого VLAN (в окне выбора) отмечен; «Все VLAN» (в карточке порта) — нет: набор выбран вручную, признака в БД нет.
    expect((wrapper.find('.iface-detail .vlan-check-all input').element as HTMLInputElement).checked).toBe(false)
    await wrapper.find('.iface-detail .vlan-picker-btn').trigger('click')
    expect((wrapper.find('.vlan-picker-modal .vlan-check:not(.vlan-check-all) input').element as HTMLInputElement).checked).toBe(true)
    await wrapper.find('.vlan-picker-modal .btn-primary').trigger('click') // «Готово»

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
    await pickVlan(wrapper, 'Новый')

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

    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-16')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const vlanCreateIndex = calls.findIndex((c) => c.method === 'PUT' && c.url.includes('/devices/dev-new/vlans'))
    const interfacesSyncIndex = calls.findIndex((c) => c.method === 'PUT' && c.url.includes('/devices/dev-new/interfaces'))
    expect(vlanCreateIndex).toBeGreaterThanOrEqual(0)
    expect(interfacesSyncIndex).toBeGreaterThan(vlanCreateIndex)
  })

  it('доменный VLAN доступен для выбора только если устройство состоит в этом домене', async () => {
    const vlans = useVLANsStore()
    vlans.groups = [
      { vlan_id: 10, definitions: [{ id: 'v-10', vlan_id: 10, name: 'Мониторинг', description: '', domain_id: null, domain_name: '', devices: [] }] },
      {
        vlan_id: 20,
        definitions: [{ id: 'v-20', vlan_id: 20, name: 'Управление', description: '', domain_id: 'dom-1', domain_name: 'Ядро сети', devices: [] }],
      },
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

    const texts = await vlanChoices(wrapper)
    expect(texts.some((t) => t.includes('Мониторинг'))).toBe(true) // без домена — доступен всем
    expect(texts.some((t) => t.includes('Управление'))).toBe(false) // доменный, не участник — скрыт
  })

  it('пункт 3: если устройство состоит в домене VLAN, в списке «VLAN устройства» только VLAN этого домена; уже выбранный VLAN без домена остаётся виден в своей строке', async () => {
    const vlans = useVLANsStore()
    const definition = (id: string, vlanId: number, name: string, domainId: string | null, domainName: string) => ({
      id,
      vlan_id: vlanId,
      name,
      description: '',
      domain_id: domainId,
      domain_name: domainName,
      devices: [],
    })
    vlans.groups = [
      { vlan_id: 10, definitions: [definition('v-10', 10, 'Мониторинг', null, '')] },
      { vlan_id: 20, definitions: [definition('v-20', 20, 'Управление', 'dom-1', 'Ядро сети')] },
      { vlan_id: 30, definitions: [definition('v-30', 30, 'Гости', 'dom-2', 'Филиал')] },
    ]
    vlans.loaded = true

    const device = { id: 'dev-dom', device_type_id: 'dt-server', serial_number: 'SN-DOM-1' } as never
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        // Устройство состоит в домене dom-1 и уже имеет VLAN без домена (v-10) — назначен до включения в домен.
        if (url.includes('/resources/vlan-domain-devices')) {
          return new Response(
            JSON.stringify({ items: [{ id: 'link-1', domain_id: 'dom-1', physical_device_id: 'dev-dom' }], total: 1, offset: 0, limit: 1000 }),
          )
        }
        if (url.includes('/resources/device-vlans')) {
          return new Response(
            JSON.stringify({
              items: [
                { id: 'dv-1', physical_device_id: 'dev-dom', vlan_id: 'v-10', ip_address: null, prefix_length: null, is_management: false, description: null },
              ],
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

    const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
    // Выбранный ранее VLAN без домена не пропал из строки, хотя больше не предлагается для выбора.
    expect(vlanRowLabels(vlanEditor)).toEqual(['10 — Мониторинг'])
    await vlanEditor.find('.add-btn').trigger('click')
    // В новой строке — только VLAN домена dom-1: без VLAN без домена и без VLAN чужого домена dom-2.
    expect(await vlanChoices(vlanEditor, 1)).toEqual(['20 — Управление [Ядро сети]'])
  })

  it('сохраняет добавленный VLAN устройства под id нового устройства', async () => {
    const vlans = useVLANsStore()
    vlans.groups = [
      { vlan_id: 10, definitions: [{ id: 'v-10', vlan_id: 10, name: 'Мониторинг', description: '', domain_id: null, domain_name: '', devices: [] }] },
    ]
    vlans.loaded = true

    const wrapper = await mountWithLoadedCatalogs()
    await wrapper.find('.nested-editor:last-of-type button.add-btn').trigger('click') // + VLAN — последний редактор в форме
    await pickVlan(wrapper, 'Мониторинг')

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

    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-13')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const vlanSync = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-new/vlans'))
    expect(vlanSync?.body).toMatchObject({ vlans: [{ vlan_id: 'v-10' }] })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('объединённое поле типа/производителя/модели: группа "без модели" не завязана на конкретную модель', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    const field = wrapper.find('.form-grid .lookup-row .searchable-select')
    expect(wrapper.find('.form-grid .lookup-row').find('select').exists()).toBe(false) // первая строка lookup — это тип/модель

    await field.find('input').trigger('focus')
    expect(field.findAll('.ss-group-label').map((g) => g.text())).toEqual(['Тип устройства (без конкретной модели)'])

    await pickTypeModel(wrapper, 'Сервер')
    expect((field.find('input').element as HTMLInputElement).value).toBe('Сервер')
  })

  it('п.1.3.7: option модели показывает производителя целиком ("Cisco WS-C2960-48TD-L"), не только модель', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    const catalogs = useCatalogsStore()
    catalogs.items['manufacturers'] = [{ id: 'mf-cisco', name: 'Cisco' }]
    catalogs.items['device-models'] = [{ id: 'dm-1', name: 'WS-C2960-48TD-L', manufacturer_id: 'mf-cisco', device_type_id: 'dt-net', model: 'WS-C2960-48TD-L' }]
    await wrapper.vm.$nextTick()

    const field = wrapper.find('.form-grid .lookup-row .searchable-select')
    await field.find('input').trigger('focus')
    expect(field.findAll('.ss-option').map((o) => o.text())).toContain('Cisco WS-C2960-48TD-L')
    // Закрытое поле после выбора показывает ТОЛЬКО подпись опции (заголовок группы не виден) —
    // это и есть тот сценарий, где раньше терялось «чьё это оборудование».
    await pickTypeModel(wrapper, 'Cisco WS-C2960-48TD-L')
    expect((field.find('input').element as HTMLInputElement).value).toBe('Cisco WS-C2960-48TD-L')
  })

  it('поиск вводом текста в поле «Тип / производитель / модель»: по производителю, модели и названию типа; выбор уходит в payload', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    const catalogs = useCatalogsStore()
    catalogs.items['manufacturers'] = [
      { id: 'mf-cisco', name: 'Cisco' },
      { id: 'mf-hp', name: 'HP' },
    ]
    catalogs.items['device-models'] = [
      { id: 'dm-1', name: 'C2960', manufacturer_id: 'mf-cisco', device_type_id: 'dt-net', model: 'WS-C2960-48TD-L' },
      { id: 'dm-2', name: 'DL380', manufacturer_id: 'mf-hp', device_type_id: 'dt-server', model: 'DL380' },
    ]
    await wrapper.vm.$nextTick()

    const field = wrapper.find('.form-grid .lookup-row .searchable-select')
    const input = field.find('input')
    const shown = () => field.findAll('.ss-option').map((o) => o.text())
    await input.trigger('focus')
    expect(shown()).toEqual(['Cisco WS-C2960-48TD-L', 'HP DL380', 'Сервер', 'Сетевое оборудование'])

    await input.setValue('cisco') // производитель
    expect(shown()).toEqual(['Cisco WS-C2960-48TD-L'])
    await input.setValue('2960') // часть модели
    expect(shown()).toEqual(['Cisco WS-C2960-48TD-L'])
    await input.setValue('сетевое') // название типа находит и саму модель этого типа, и «голый» тип
    expect(shown()).toEqual(['Cisco WS-C2960-48TD-L', 'Сетевое оборудование'])
    await input.setValue('серверное cisco') // ни одной опции — ничего не найдено
    expect(shown()).toEqual([])
    expect(field.find('.ss-empty').text()).toBe('Ничего не найдено')

    await input.setValue('hp dl')
    await field.find('.ss-option').trigger('mousedown')
    expect((input.element as HTMLInputElement).value).toBe('HP DL380')

    let body: Record<string, unknown> | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.includes('/resources/devices')) {
          body = JSON.parse(init!.body as string)
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-FIND' }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )
    await setSerial(wrapper, 'SN-FIND')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(body).toMatchObject({ model_id: 'dm-2', device_type_id: 'dt-server', manufacturer_id: 'mf-hp' })
  })

  it('поле «Тип / производитель / модель» обязательно: без выбора форма не отправляется, а очистка выбора возвращает эту ошибку', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    await setSerial(wrapper, 'SN-NOTYPE')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('Укажите тип устройства')

    await pickTypeModel(wrapper, 'Сервер')
    await wrapper.find('.form-grid .lookup-row .ss-clear').trigger('mousedown')
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('Укажите тип устройства')
    expect(wrapper.emitted('saved')).toBeFalsy()
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
    const typeSearch = body.findAll('.modal-overlay .searchable-select input')[0]
    await typeSearch.trigger('focus')
    const typeOptions = body.findAll('.modal-overlay .searchable-select')[0].findAll('.ss-option')
    await typeOptions.find((o) => o.text() === 'Сетевое оборудование')!.trigger('mousedown') // dt-net — из deviceTypesFixture

    const mfSearch = body.findAll('.modal-overlay .searchable-select input')[1]
    await mfSearch.trigger('focus')
    await body.findAll('.modal-overlay .searchable-select')[1].find('.ss-option').trigger('mousedown') // Dell — единственный производитель в тесте

    // device-models: после двух SearchableSelect (Тип/Производитель) в DOM идёт обычный input
    // поля "Модель" — он последний среди input[type="text"], а не первый (первые два теперь
    // принадлежат поисковым полям SearchableSelect).
    const overlayTextInputs = body.findAll('.modal-overlay input[type="text"]')
    await overlayTextInputs[overlayTextInputs.length - 1].setValue('PowerVault')
    await body.find('.modal-overlay form').trigger('submit')
    await flushPromises()

    // Объединённое поле отражает выбранную модель, а не "сырой" device_type_id.
    expect((wrapper.find('.form-grid .lookup-row .searchable-select input').element as HTMLInputElement).value).toBe('Dell PowerVault')

    // А device_type_id/manufacturer_id формы реально синхронизированы — проверяем по факту
    // отправленного payload'а, а не по DOM-значению другого select'а (которого больше нет).
    const postMock = fetch as unknown as ReturnType<typeof vi.fn>
    await setSerial(wrapper, 'SN-77')
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
    await body.find('.modal-overlay input[type="text"]').setValue('Корпус Б')
    await body.find('.modal-overlay form').trigger('submit')
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
    await body.find('.modal-overlay .searchable-select input').trigger('focus')
    await body.find('.modal-overlay .ss-option').trigger('mousedown') // единственный вариант — b-1 "Корпус А"
    const roomTextInputs = body.findAll('.modal-overlay input[type="text"]')
    await roomTextInputs[roomTextInputs.length - 1].setValue('204')
    await body.find('.modal-overlay form').trigger('submit')
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
    await body.find('.modal-overlay .searchable-select input').trigger('focus')
    await body.find('.modal-overlay .ss-option').trigger('mousedown') // единственный вариант — room-1 "204"
    const rackTextInputs = body.findAll('.modal-overlay input[type="text"]')
    await rackTextInputs[rackTextInputs.length - 1].setValue('R-1')
    await body.find('.modal-overlay form').trigger('submit')
    await flushPromises()

    const buildingRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Здание')!
    const roomRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Помещение')!
    expect((buildingRow.find('.searchable-select input').element as HTMLInputElement).value).toBe('Корпус А')
    expect((roomRow.find('.searchable-select input').element as HTMLInputElement).value).toBe('204')
    expect((rackRow.find('.searchable-select input').element as HTMLInputElement).value).toBe('R-1')
  })

  // Окно «Добавить: Стойка» из формы устройства: помещения — только выбранного там здания (здание не выбрано — все),
  // а помещение, уже выбранное в форме, подставляется в окно автоматически.
  describe('быстрое добавление стойки: помещения здания и выбранное помещение', () => {
    async function pickInField(wrapper: VueWrapper, fieldLabel: string, optionLabel: string) {
      const field = wrapper.findAll('.field').find((f) => f.find('span').text() === fieldLabel)!
      await field.find('.searchable-select input').trigger('focus')
      await field
        .findAll('.ss-option')
        .find((o) => o.text() === optionLabel)!
        .trigger('mousedown')
    }
    async function openRackModal(wrapper: VueWrapper) {
      const rackRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Стойка')!
      await rackRow.find('button').trigger('click')
      return new DOMWrapper(document.body)
    }
    async function mountWithBuildingsAndRooms() {
      const wrapper = await mountWithLoadedCatalogs()
      const catalogs = useCatalogsStore()
      catalogs.items['buildings'] = [
        { id: 'b-1', name: 'Корпус А' },
        { id: 'b-2', name: 'Корпус Б' },
      ]
      catalogs.items['rooms'] = [
        { id: 'room-1', building_id: 'b-1', name: '204' },
        { id: 'room-2', building_id: 'b-2', name: '305' },
      ]
      return wrapper
    }
    async function roomChoicesInRackModal(body: DOMWrapper<HTMLElement>): Promise<string[]> {
      await body.find('.modal-overlay .searchable-select input').trigger('focus')
      return body.findAll('.modal-overlay .ss-option').map((o) => o.text())
    }

    it('со зданием в форме в окне стойки только помещения этого здания', async () => {
      const wrapper = await mountWithBuildingsAndRooms()
      await pickInField(wrapper, 'Здание', 'Корпус А')

      const body = await openRackModal(wrapper)

      expect(await roomChoicesInRackModal(body)).toEqual(['204'])
    })

    it('без выбранного здания в окне стойки полный список помещений', async () => {
      const wrapper = await mountWithBuildingsAndRooms()

      const body = await openRackModal(wrapper)

      expect(await roomChoicesInRackModal(body)).toEqual(['204', '305'])
    })

    it('выбранное в форме помещение автоматически выбрано в окне стойки', async () => {
      const wrapper = await mountWithBuildingsAndRooms()
      await pickInField(wrapper, 'Здание', 'Корпус Б')
      await pickInField(wrapper, 'Помещение', '305')

      const body = await openRackModal(wrapper)

      expect((body.find('.modal-overlay .searchable-select input').element as HTMLInputElement).value).toBe('305')
    })

    it('если помещение в форме не выбрано, в окне стойки оно не заполнено', async () => {
      const wrapper = await mountWithBuildingsAndRooms()
      await pickInField(wrapper, 'Здание', 'Корпус А')

      const body = await openRackModal(wrapper)

      expect((body.find('.modal-overlay .searchable-select input').element as HTMLInputElement).value).toBe('')
    })
  })

  // Окно «Добавить: Помещение» из формы устройства: поле «Здание» заранее равно зданию, выбранному в форме.
  describe('быстрое добавление помещения: здание из формы', () => {
    async function pickInField(wrapper: VueWrapper, fieldLabel: string, optionLabel: string) {
      const field = wrapper.findAll('.field').find((f) => f.find('span').text() === fieldLabel)!
      await field.find('.searchable-select input').trigger('focus')
      await field
        .findAll('.ss-option')
        .find((o) => o.text() === optionLabel)!
        .trigger('mousedown')
    }
    async function openRoomModal(wrapper: VueWrapper) {
      const roomRow = wrapper.findAll('.field').find((f) => f.find('span').text() === 'Помещение')!
      await roomRow.find('button').trigger('click')
      return new DOMWrapper(document.body)
    }
    async function mountWithBuildings() {
      const wrapper = await mountWithLoadedCatalogs()
      const catalogs = useCatalogsStore()
      catalogs.items['buildings'] = [
        { id: 'b-1', name: 'Корпус А' },
        { id: 'b-2', name: 'Корпус Б' },
      ]
      catalogs.items['rooms'] = []
      return wrapper
    }

    it('выбранное в форме здание автоматически выбрано в окне помещения', async () => {
      const wrapper = await mountWithBuildings()
      await pickInField(wrapper, 'Здание', 'Корпус Б')

      const body = await openRoomModal(wrapper)

      // rooms: [building_id (fk, SearchableSelect), name (text)] — первый SearchableSelect окна — «Здание».
      expect((body.find('.modal-overlay .searchable-select input').element as HTMLInputElement).value).toBe('Корпус Б')
    })

    it('если здание в форме не выбрано, в окне помещения оно не заполнено', async () => {
      const wrapper = await mountWithBuildings()

      const body = await openRoomModal(wrapper)

      expect((body.find('.modal-overlay .searchable-select input').element as HTMLInputElement).value).toBe('')
    })

    it('предзаполненное здание можно сменить в окне — это только стартовое значение', async () => {
      const wrapper = await mountWithBuildings()
      await pickInField(wrapper, 'Здание', 'Корпус А')

      const body = await openRoomModal(wrapper)
      await body.find('.modal-overlay .searchable-select input').trigger('focus')
      await body
        .findAll('.modal-overlay .ss-option')
        .find((o) => o.text() === 'Корпус Б')!
        .trigger('mousedown')

      expect((body.find('.modal-overlay .searchable-select input').element as HTMLInputElement).value).toBe('Корпус Б')
    })
  })

  // п.3.8: наивный @click.self на подложке закрывал форму при попытке выделить текст внутри
  // карточки, если mouseup (а значит и click) заканчивался за пределами карточки.
  describe('закрытие по клику на подложку (п.3.8)', () => {
    it('закрывает форму по обычному клику на подложку', async () => {
      const wrapper = await mountWithLoadedCatalogs()
      await wrapper.find('.modal-overlay').trigger('mousedown')
      await wrapper.find('.modal-overlay').trigger('click')
      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('НЕ закрывает форму, если mousedown начался внутри карточки (типичная попытка выделить текст)', async () => {
      const wrapper = await mountWithLoadedCatalogs()
      await wrapper.find('.modal-head h2').trigger('mousedown') // mousedown на заголовке ВНУТРИ карточки
      await wrapper.find('.modal-overlay').trigger('click') // click "долетел" до подложки (mouseup был за пределами карточки)
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
          if (url.includes('/interface-open-ports') && method === 'GET') {
            return new Response(
              JSON.stringify({
                items: [
                  {
                    id: 'op-src',
                    owner_type: 'device_interface',
                    owner_id: 'if-src',
                    transport_protocol: 'TCP',
                    port: 22,
                    protocol: 'SSH',
                    protocol_catalog_id: 'cat-ssh',
                    ip_address: null,
                    description: null,
                  },
                ],
                total: 1,
                offset: 0,
                limit: 1000,
              }),
            )
          }
          if (url.includes('/resources/interfaces') && method === 'GET') {
            return new Response(
              JSON.stringify({
                items: [
                  {
                    id: 'if-src',
                    physical_device_id: 'dev-src',
                    name: 'eth0',
                    interface_type_id: null,
                    mac_address: null,
                    speed_id: null,
                    is_management: false,
                    is_data_transfer: false,
                    description: null,
                    vlan_mode: 'access',
                  },
                ],
                total: 1,
                offset: 0,
                limit: 1000,
              }),
            )
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
      vlans.groups = [
        {
          vlan_id: 77,
          definitions: [{ id: 'v-domain', vlan_id: 77, name: 'Гостевой', description: '', domain_id: 'domain-x', domain_name: 'Домен X', devices: [] }],
        },
      ]
      vlans.loaded = true

      const calls: Array<{ url: string; method: string; body?: unknown }> = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
          if (url.includes('/resources/vlan-domain-devices') && method === 'GET') {
            return new Response(
              JSON.stringify({ items: [{ id: 'link-src', domain_id: 'domain-x', physical_device_id: 'dev-src' }], total: 1, offset: 0, limit: 1000 }),
            )
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
      // Устройство (копия) состоит только в domain-x — в списке ровно VLAN этого домена.
      expect(await vlanChoices(vlanEditor)).toEqual(['77 — Гостевой [Домен X]'])

      await wrapper.find('input[required][maxlength="255"]').setValue('SN-NEW')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const membershipPost = calls.find((c) => c.method === 'POST' && c.url.endsWith('/resources/vlan-domain-devices'))
      expect(membershipPost?.body).toEqual({ physical_device_id: 'dev-new', domain_id: 'domain-x' })
    })
  })

  describe('пункты 1-2 правки "физическое устройство: расхождение с соседним портом" — вычисление в DeviceFormModal.vue', () => {
    const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' } as never

    // Сведения о соседе приходят с сервера вместе с подключением порта (GET /devices/{id}/interface-connections):
    // ни общий список подключений, ни каталог интерфейсов форме для расхождений не нужны — стор подключений
    // намеренно оставлен пустым, чтобы тест это доказывал.
    function mountWithConnection(thisIface: Record<string, unknown>, otherIface: Record<string, unknown>) {
      const connections = useConnectionsStore()
      connections.all = []
      connections.loaded = true
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          if (url.includes('/resources/interfaces') && url.includes('dev-1')) {
            return new Response(
              JSON.stringify({ items: [{ id: 'if-this', physical_device_id: 'dev-1', name: 'Gi0/1', ...thisIface }], total: 1, offset: 0, limit: 1000 }),
            )
          }
          if (/\/devices\/dev-1\/interface-connections$/.test(url)) {
            const peer = otherIface as { is_management: boolean; is_data_transfer: boolean; vlan_mode: string }
            return new Response(
              JSON.stringify({
                items: [
                  {
                    interface_id: 'if-this',
                    connection_id: 'c-1',
                    connection_type_id: 'ct-1',
                    description: null,
                    peer_interface_id: 'if-other',
                    peer_interface_name: 'Gi0/2',
                    peer_device_id: 'dev-2',
                    peer_device_name: 'sw-02',
                    peer_is_management: peer.is_management,
                    peer_is_data_transfer: peer.is_data_transfer,
                    peer_vlan_mode: peer.vlan_mode,
                  },
                ],
              }),
            )
          }
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )
      return mount(DeviceFormModal, { props: { device } })
    }

    it('интерфейс с активным подключением, чьё назначение расходится со "вторым концом", подсвечивается предупреждением', async () => {
      const wrapper = mountWithConnection(
        { is_management: true, is_data_transfer: false, vlan_mode: 'trunk' },
        { is_management: false, is_data_transfer: true, vlan_mode: 'trunk' },
      )
      await flushPromises()

      const cell = wrapper.find('tr:not(.bulk-edit-row) td.col-check')
      expect(cell.classes()).toContain('has-conflict')
    })

    it('интерфейс без активных подключений — предупреждения нет', async () => {
      const catalogs = useCatalogsStore()
      catalogs.items['interfaces'] = [
        { id: 'if-this', physical_device_id: 'dev-1', name: 'Gi0/1', is_management: true, is_data_transfer: false, vlan_mode: 'trunk' },
      ] as never
      const connections = useConnectionsStore()
      connections.all = []
      connections.loaded = true

      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          if (url.includes('/resources/interfaces') && url.includes('dev-1')) {
            return new Response(
              JSON.stringify({
                items: [{ id: 'if-this', physical_device_id: 'dev-1', name: 'Gi0/1', is_management: true, is_data_transfer: false, vlan_mode: 'trunk' }],
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

      expect(wrapper.find('tr:not(.bulk-edit-row) td.col-check').classes()).not.toContain('has-conflict')
    })

    it('пункт 2: совпадающие флаги, но разный режим порта — конфликт есть, но ячейки Упр./Данные не подсвечены', async () => {
      const wrapper = mountWithConnection(
        { is_management: true, is_data_transfer: true, vlan_mode: 'access' },
        { is_management: true, is_data_transfer: true, vlan_mode: 'trunk' },
      )
      await flushPromises()

      expect(wrapper.find('tr:not(.bulk-edit-row) td.col-check').classes()).not.toContain('has-conflict')
      expect(wrapper.find('.expand-toggle .conflict-icon').exists()).toBe(true)
    })

    it('совпадающие флаги И режим порта — конфликта нет вовсе', async () => {
      const wrapper = mountWithConnection(
        { is_management: true, is_data_transfer: false, vlan_mode: 'access' },
        { is_management: true, is_data_transfer: false, vlan_mode: 'access' },
      )
      await flushPromises()

      expect(wrapper.find('tr:not(.bulk-edit-row) td.col-check').classes()).not.toContain('has-conflict')
      expect(wrapper.find('.expand-toggle .conflict-icon').exists()).toBe(false)
    })

    it('«Применить текущую конфигурацию» соседу: форма перечитывает соседей с сервера, и значок расхождения исчезает сразу', async () => {
      const connections = useConnectionsStore()
      connections.all = []
      connections.loaded = true
      let neighborIsManagement = false // у соседа «Управление» выключено, у нашего порта — включено
      const calls: Array<{ url: string; method: string }> = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          calls.push({ url, method })
          if (url.includes('/resources/interfaces') && url.includes('dev-1')) {
            return new Response(
              JSON.stringify({
                items: [{ id: 'if-this', physical_device_id: 'dev-1', name: 'Gi0/1', is_management: true, is_data_transfer: true, vlan_mode: 'trunk' }],
                total: 1,
                offset: 0,
                limit: 1000,
              }),
            )
          }
          if (method === 'PUT' && url.endsWith('/resources/interfaces/if-other')) {
            neighborIsManagement = true // сервер записал конфигурацию соседа
            return new Response(JSON.stringify({ id: 'if-other' }))
          }
          if (/\/devices\/dev-1\/interface-connections$/.test(url)) {
            return new Response(
              JSON.stringify({
                items: [
                  {
                    interface_id: 'if-this',
                    connection_id: 'c-1',
                    connection_type_id: 'ct-1',
                    description: null,
                    peer_interface_id: 'if-other',
                    peer_interface_name: 'Gi0/2',
                    peer_device_id: 'dev-2',
                    peer_device_name: 'sw-02',
                    peer_is_management: neighborIsManagement,
                    peer_is_data_transfer: true,
                    peer_vlan_mode: 'trunk',
                  },
                ],
              }),
            )
          }
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )
      const wrapper = mount(DeviceFormModal, { props: { device } })
      await flushPromises()
      expect(wrapper.find('tr:not(.bulk-edit-row) td.col-check').classes()).toContain('has-conflict')

      await wrapper.find('.conflict-icon-btn').trigger('click')
      await wrapper.find('.conflict-modal-actions .btn-primary').trigger('click') // применить текущую конфигурацию соседу
      await flushPromises()

      expect(calls.filter((c) => c.url.endsWith('/devices/dev-1/interface-connections'))).toHaveLength(2) // при открытии и после записи соседу
      expect(wrapper.find('tr:not(.bulk-edit-row) td.col-check').classes()).not.toContain('has-conflict')
      expect(wrapper.find('.expand-toggle .conflict-icon').exists()).toBe(false)
    })

    it('окно решения показывает реальные имена устройства/порта соседа из подключения (enrich_connections)', async () => {
      const wrapper = mountWithConnection(
        { is_management: true, is_data_transfer: false, vlan_mode: 'access' },
        { is_management: false, is_data_transfer: false, vlan_mode: 'access' },
      )
      await flushPromises()

      await wrapper.find('.conflict-icon-btn').trigger('click')
      expect(wrapper.text()).toContain('sw-02')
      expect(wrapper.text()).toContain('Gi0/2')
    })
  })

  describe('фикс п.2.1.2: новый VLAN устройства автоматически подхватывается портами и группами с "Все VLAN"', () => {
    type Call = { url: string; method: string; body?: unknown }

    // Сценарий бага: единственный назначенный VLAN устройства (v-old) уже выбран на порту (и, если
    // withGroup, в его группе) как "Все VLAN"; затем пользователь добавляет в блок "VLAN устройства" новый (v-new).
    // «Все VLAN» — сохраняемый признак (all_vlans, по умолчанию стоит): без него (allVlans: false) тот же полный набор —
    // обычный ручной выбор и новых VLAN не получает.
    function stubScenarioFetch(calls: Call[], opts: { withGroup: boolean; deviceVlanIds?: string[]; groupVlanIds?: string[]; allVlans?: boolean }) {
      const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' }
      const allVlans = opts.allVlans ?? true
      const group = {
        id: 'g-1',
        name: 'Транки',
        vlan_mode: 'trunk',
        all_vlans: allVlans,
        vlan_ids: opts.groupVlanIds ?? ['v-old'],
        ips: [],
        manage_open_ports: false,
        open_ports: [],
      }
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
          if (url.includes('/resources/device-types')) return new Response(JSON.stringify(deviceTypesFixture))
          if (/\/resources$/.test(url)) return new Response(JSON.stringify([]))
          if (url.includes('/devices/dev-1/interface-groups')) return new Response(JSON.stringify({ items: opts.withGroup ? [group] : [] }))
          // Тип устройства не даёт ни одного VLAN сам по себе — единственный источник portVlanOptions
          // здесь "VLAN устройства" (deviceVlans), это и есть сценарий бага: единственный назначенный
          // VLAN устройства (v-old) уже выбран на порту как "Все VLAN".
          if (url.includes('/resources/device-type-vlans')) return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
          if (url.includes('/resources/device-vlans') && method === 'GET') {
            const items = (opts.deviceVlanIds ?? ['v-old']).map((vlan_id, i) => ({
              id: `dv-${i + 1}`,
              physical_device_id: 'dev-1',
              vlan_id,
              ip_address: null,
              prefix_length: null,
              is_management: false,
              description: null,
            }))
            return new Response(JSON.stringify({ items, total: items.length, offset: 0, limit: 1000 }))
          }
          if (url.includes('/resources/interfaces') && method === 'GET') {
            const iface = {
              id: 'if-1',
              physical_device_id: 'dev-1',
              name: 'Gi0/1',
              interface_type_id: null,
              mac_address: null,
              speed_id: null,
              is_management: false,
              is_data_transfer: false,
              description: null,
              vlan_mode: 'trunk',
              ...(opts.withGroup ? { group_id: 'g-1' } : {}),
            }
            return new Response(JSON.stringify({ items: [iface], total: 1, offset: 0, limit: 1000 }))
          }
          if (url.includes('/devices/dev-1/interface-vlans') && method === 'GET') {
            return new Response(JSON.stringify({ items: [{ interface_id: 'if-1', all_vlans: allVlans, vlan_ids: opts.groupVlanIds ?? ['v-old'] }] }))
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
            return new Response(JSON.stringify({ items: [{ id: 'if-1', physical_device_id: 'dev-1', name: 'Gi0/1', vlan_mode: 'trunk' }], groups: [] }))
          }
          return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        }),
      )
    }

    async function addNewVlanAndSave(calls: Call[], withGroup: boolean, allVlans = true) {
      const vlans = useVLANsStore()
      vlans.groups = [{ vlan_id: 10, definitions: [{ id: 'v-old', vlan_id: 10, name: 'Old', description: '', domain_id: null, domain_name: '', devices: [] }] }]
      vlans.loaded = true
      const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' } as never
      stubScenarioFetch(calls, { withGroup, allVlans })

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
      await body.find('.modal-overlay form').trigger('submit')
      await flushPromises()

      await wrapper.find('form').trigger('submit')
      await flushPromises()
    }

    type SavedBody = {
      interfaces: Array<{ id: string; vlan_ids: string[]; all_vlans: boolean; group_key?: string | null }>
      groups?: Array<{ id: string; vlan_mode: string | null; all_vlans: boolean; vlan_ids: string[] }>
    }
    const savedBody = (calls: Call[]) => calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-1/interfaces'))!.body as SavedBody

    it('интерфейс с признаком «Все VLAN» в trunk-режиме получает вновь добавленный VLAN устройства и остаётся с признаком', async () => {
      const calls: Call[] = []
      await addNewVlanAndSave(calls, false)

      const savedRow = savedBody(calls).interfaces.find((r) => r.id === 'if-1')
      expect(savedRow!.vlan_ids).toEqual(expect.arrayContaining(['v-old', 'v-new']))
      expect(savedRow!.all_vlans).toBe(true)
    })

    it('полный набор, выбранный вручную (без признака «Все VLAN»), нового VLAN устройства не получает', async () => {
      const calls: Call[] = []
      await addNewVlanAndSave(calls, false, false)

      const savedRow = savedBody(calls).interfaces.find((r) => r.id === 'if-1')
      expect(savedRow!.vlan_ids).toEqual(['v-old'])
      expect(savedRow!.all_vlans).toBe(false)
    })

    it('группа портов в trunk-режиме с полным набором VLAN тоже получает новый VLAN — группа и её порт согласованы', async () => {
      const calls: Call[] = []
      await addNewVlanAndSave(calls, true)

      const body = savedBody(calls)
      const savedGroup = body.groups!.find((g) => g.id === 'g-1')
      const savedRow = body.interfaces.find((r) => r.id === 'if-1')
      // Без обновления группы сервер записал бы в порт прежний набор группы и затёр бы новый VLAN порта.
      expect(savedGroup!.vlan_ids).toEqual(['v-old', 'v-new'])
      expect(savedGroup!.all_vlans).toBe(true)
      expect(savedRow!.group_key).toBe('g-1')
      expect(savedRow!.vlan_ids).toEqual(['v-old', 'v-new'])
      expect(savedRow!.all_vlans).toBe(true)
    })

    describe('уведомление, когда VLAN, снятый с устройства, убирается из групп портов', () => {
      const def = (id: string, vlan_id: number, name: string) => ({ id, vlan_id, name, description: '', domain_id: null, domain_name: '', devices: [] })

      async function mountAndRemoveLastDeviceVlan(calls: Call[], groupVlanIds: string[], allVlans = true) {
        const vlans = useVLANsStore()
        vlans.groups = [
          { vlan_id: 10, definitions: [def('v-a', 10, 'Серверы')] },
          { vlan_id: 20, definitions: [def('v-b', 20, 'Гости')] },
        ]
        vlans.loaded = true
        stubScenarioFetch(calls, { withGroup: true, deviceVlanIds: ['v-a', 'v-b'], groupVlanIds, allVlans })
        const wrapper = mount(DeviceFormModal, { props: { device: { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' } as never } })
        await flushPromises()
        useToast().toasts.splice(0)

        const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
        const removeButtons = vlanEditor.findAll('button[aria-label="Удалить VLAN"]')
        await removeButtons[removeButtons.length - 1].trigger('click') // удаляем строку «20 — Гости»
        await flushPromises()
        return wrapper
      }

      it('VLAN убран из группы вместе со снятием с устройства — предупреждение называет VLAN и группу, в запрос сохранения уходит очищенная группа', async () => {
        const calls: Call[] = []
        const wrapper = await mountAndRemoveLastDeviceVlan(calls, ['v-a', 'v-b'])

        const toasts = useToast().toasts
        expect(toasts.map((t) => t.type)).toEqual(['warning'])
        expect(toasts[0].message).toBe('Снятые с устройства VLAN (20 — Гости) убраны и из групп портов: «Транки».')

        await wrapper.find('form').trigger('submit')
        await flushPromises()
        const body = savedBody(calls)
        expect(body.groups!.find((g) => g.id === 'g-1')!.vlan_ids).toEqual(['v-a'])
        expect(body.interfaces.find((r) => r.id === 'if-1')!.vlan_ids).toEqual(['v-a'])
      })

      it('если снятого VLAN не было ни в одной группе — уведомления нет', async () => {
        const calls: Call[] = []
        await mountAndRemoveLastDeviceVlan(calls, ['v-a'], false) // группа выбрана вручную (не «Все VLAN») без снимаемого VLAN

        expect(useToast().toasts).toHaveLength(0)
      })
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
            return new Response(
              JSON.stringify({ items: [{ id: 'link-1', domain_id: 'domain-x', physical_device_id: 'dev-1' }], total: 1, offset: 0, limit: 1000 }),
            )
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
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))),
      )

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
      await pickTypeModel(wrapper, 'Сервер')
      await setSerial(wrapper, 'SN-1')

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
      await pickTypeModel(wrapper, 'Сервер')
      await setSerial(wrapper, 'SN-1')

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

describe('правки формы физического устройства: порядок типов, поиск ОС, домен VLAN, уведомление о портах', () => {
  const emptyList = () => new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))

  it('пункт 1: группы моделей (добавленные пользователем) идут первыми, а "Тип устройства (без конкретной модели)" — в самом конце', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    const catalogs = useCatalogsStore()
    catalogs.items['manufacturers'] = [
      { id: 'mf-cisco', name: 'Cisco' },
      { id: 'mf-hp', name: 'HP' },
    ]
    catalogs.items['device-models'] = [
      { id: 'dm-1', name: 'C2960', manufacturer_id: 'mf-cisco', device_type_id: 'dt-net', model: 'C2960' },
      { id: 'dm-2', name: 'DL380', manufacturer_id: 'mf-hp', device_type_id: 'dt-server', model: 'DL380' },
    ]
    await wrapper.vm.$nextTick()

    await wrapper.find('.form-grid .lookup-row .searchable-select input').trigger('focus')
    const labels = wrapper.findAll('.form-grid .lookup-row .ss-group-label').map((g) => g.text())
    expect(labels).toEqual(['Cisco', 'HP', 'Тип устройства (без конкретной модели)'])
  })

  it.each([
    ['Операционная система', 'operating-systems', 'operating_system_id', 'Ubuntu 22.04'],
    ['Встроенная ОС (для сетевого оборудования)', 'embedded-os', 'embedded_os_id', 'IOS 15.2'],
  ] as const)('пункт 2: поле «%s» — SearchableSelect: фильтруется вводом текста, выбор попадает в payload', async (title, catalogKey, payloadKey, label) => {
    const wrapper = await mountWithLoadedCatalogs()
    const catalogs = useCatalogsStore()
    const [name, version] = label.split(' ')
    catalogs.items[catalogKey] = [
      { id: 'os-other', name: 'Windows Server', version: '2019' },
      { id: 'os-target', name, version },
    ]
    await wrapper.vm.$nextTick()

    const field = wrapper.findAll('.field').find((f) => f.find('span').text() === title)!
    expect(field.find('select').exists()).toBe(false)
    const input = field.find('.searchable-select input')
    await input.trigger('focus')
    await input.setValue(name.slice(0, 3))

    const options = field.findAll('.ss-option')
    expect(options.map((o) => o.text())).toEqual([label])
    await options[0].trigger('mousedown')

    let body: Record<string, unknown> | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.includes('/resources/devices')) {
          body = JSON.parse(init!.body as string)
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-OS' }), { status: 201 })
        }
        return emptyList()
      }),
    )
    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-OS')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(body?.[payloadKey]).toBe('os-target')
  })

  it('пункты 3-4: «Включить в домен» сразу показывает домен и подтягивает его VLAN в блок, при сохранении они не теряются', async () => {
    const vlanDomains = useVLANDomainsStore()
    vlanDomains.all = [{ id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: null, auto_sync: false }]
    vlanDomains.loaded = true
    const vlans = useVLANsStore()
    vlans.groups = []
    vlans.loaded = true
    const wrapper = await mountWithLoadedCatalogs()

    const definition = (id: string, vlanId: number, domainId: string | null) => ({
      id,
      vlan_id: vlanId,
      name: `VLAN ${vlanId}`,
      description: '',
      domain_id: domainId,
      domain_name: domainId ? 'Ядро сети' : '',
      devices: [],
    })
    const calls: Array<{ url: string; method: string; body?: Record<string, unknown> }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.includes('/vlan-dashboard')) {
          return new Response(
            JSON.stringify({
              items: [
                { vlan_id: 10, definitions: [definition('v-10', 10, 'dom-1')] },
                { vlan_id: 20, definitions: [definition('v-20', 20, 'dom-1')] },
                { vlan_id: 30, definitions: [definition('v-30', 30, 'dom-other')] },
              ],
            }),
          )
        }
        if (method === 'POST' && url.endsWith('/resources/devices'))
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-DOM' }), { status: 201 })
        if (method === 'POST') return new Response(JSON.stringify({ id: 'created' }), { status: 201 })
        return emptyList()
      }),
    )

    const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
    expect(vlanEditor.find('[data-testid="member-domain"]').exists()).toBe(false)

    await vlanEditor.find('.join-domain-row select').setValue('dom-1')
    await vlanEditor.find('.join-domain-row button').trigger('click')
    await flushPromises()

    // Пункт 3: включение видно сразу — без сохранения и перезагрузки страницы.
    const chips = vlanEditor.findAll('[data-testid="member-domain"]')
    expect(chips).toHaveLength(1)
    expect(chips[0].text()).toContain('Ядро сети')
    expect(chips[0].text()).toContain('будет включено при сохранении')
    // Пункт 4: VLAN именно этого домена (не чужого) уже назначены устройству в форме.
    expect(vlanRowLabels(vlanEditor)).toEqual(['10 — VLAN 10 [Ядро сети]', '20 — VLAN 20 [Ядро сети]'])
    expect(vlanEditor.find('.join-domain-row').exists()).toBe(false) // единственный домен — больше не предлагается

    calls.length = 0
    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-DOM')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // Один атомарный PUT со всеми VLAN устройства (а не delete + N×create) — и домен, и его VLAN.
    const vlanSyncs = calls.filter((c) => c.method === 'PUT' && c.url.endsWith('/devices/dev-new/vlans'))
    expect(vlanSyncs).toHaveLength(1)
    expect((vlanSyncs[0].body?.vlans as Array<{ vlan_id: string }>).map((v) => v.vlan_id)).toEqual(['v-10', 'v-20'])
    expect(calls.some((c) => c.url.includes('/resources/device-vlans') && c.method !== 'GET')).toBe(false)
    expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/resources/vlan-domain-devices'))).toBe(true)
    // Сторы VLAN перечитаны после сохранения — другие экраны не показывают устаревшие данные.
    expect(calls.filter((c) => c.url.includes('/vlan-dashboard')).length).toBeGreaterThan(0)
  })

  it('отмена ещё не сохранённого включения в домен (×): чип исчезает, VLAN домена убираются, домен снова предлагается, членство не создаётся', async () => {
    const vlanDomains = useVLANDomainsStore()
    vlanDomains.all = [{ id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: null, auto_sync: false }]
    vlanDomains.loaded = true
    const definition = (id: string, vlanId: number, domainId: string | null) => ({
      id,
      vlan_id: vlanId,
      name: `VLAN ${vlanId}`,
      description: '',
      domain_id: domainId,
      domain_name: domainId ? 'Ядро сети' : '',
      devices: [],
    })
    const vlans = useVLANsStore()
    vlans.groups = [{ vlan_id: 30, definitions: [definition('v-30', 30, null)] }] // глобальный VLAN доступен сразу
    vlans.loaded = true
    const wrapper = await mountWithLoadedCatalogs()

    const calls: Array<{ url: string; method: string; body?: Record<string, unknown> }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.includes('/vlan-dashboard')) {
          return new Response(
            JSON.stringify({
              items: [
                { vlan_id: 10, definitions: [definition('v-10', 10, 'dom-1')] },
                { vlan_id: 30, definitions: [definition('v-30', 30, null)] },
              ],
            }),
          )
        }
        if (method === 'POST' && url.endsWith('/resources/devices'))
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-CANCEL' }), { status: 201 })
        if (method === 'PUT' && url.includes('/devices/dev-new/vlans')) return new Response(JSON.stringify({ items: [] }))
        return emptyList()
      }),
    )

    const vlanEditor = () => wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
    // VLAN без домена, назначенный вручную ДО включения, — не относится к домену и должен пережить отмену.
    await vlanEditor().find('button.add-btn').trigger('click')
    await wrapper.vm.$nextTick()
    await pickVlan(vlanEditor(), '30 — VLAN 30')

    await vlanEditor().find('.join-domain-row select').setValue('dom-1')
    await vlanEditor().find('.join-domain-row button').trigger('click')
    await flushPromises()
    expect(vlanEditor().findAll('[data-testid="member-domain"]')).toHaveLength(1)
    // v-30 (без домена) скрыт фильтром по домену, но остаётся подписан в своей строке; добавленные VLAN домена
    // встают в список по номеру (как при добавлении строки вручную), а не дописываются в конец.
    expect(vlanRowLabels(vlanEditor())).toEqual(['10 — VLAN 10 [Ядро сети]', '30 — VLAN 30'])

    await vlanEditor().find('[data-testid="cancel-join-domain"]').trigger('click')
    await flushPromises()

    expect(vlanEditor().find('[data-testid="member-domain"]').exists()).toBe(false)
    expect(vlanRowLabels(vlanEditor())).toEqual(['30 — VLAN 30'])
    expect(vlanEditor().find('.join-domain-row option[value="dom-1"]').exists()).toBe(true) // домен снова можно включить

    calls.length = 0
    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-CANCEL')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(calls.some((c) => c.url.endsWith('/resources/vlan-domain-devices'))).toBe(false)
    const sync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/devices/dev-new/vlans'))
    expect((sync?.body?.vlans as Array<{ vlan_id: string }>).map((v) => v.vlan_id)).toEqual(['v-30'])
  })

  describe('пункт 5: уведомление о сохранении порта с расхождением относительно соседа', () => {
    const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' } as never

    // Сосед приходит с сервера вместе с подключением порта (GET /devices/{id}/interface-connections); общий список
    // подключений и каталог интерфейсов не нужны, стор подключений пуст намеренно.
    function mountWithNeighbour(thisIface: Record<string, unknown>, otherIface: Record<string, unknown>) {
      useToast().toasts.splice(0)
      const connections = useConnectionsStore()
      connections.all = []
      connections.loaded = true
      const peer = otherIface as { is_management: boolean; is_data_transfer: boolean; vlan_mode: string }
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          if (method === 'PUT' && url.includes('/devices/dev-1/interfaces'))
            return new Response(JSON.stringify({ items: [{ id: 'if-this', physical_device_id: 'dev-1', name: 'Gi0/1', ...thisIface }] }))
          if (method === 'PUT' && url.includes('/resources/devices/dev-1')) return new Response(JSON.stringify(device))
          if (url.includes('/resources/interfaces') && url.includes('dev-1')) {
            return new Response(
              JSON.stringify({ items: [{ id: 'if-this', physical_device_id: 'dev-1', name: 'Gi0/1', ...thisIface }], total: 1, offset: 0, limit: 1000 }),
            )
          }
          if (/\/devices\/dev-1\/interface-connections$/.test(url)) {
            return new Response(
              JSON.stringify({
                items: [
                  {
                    interface_id: 'if-this',
                    connection_id: 'c-1',
                    connection_type_id: 'ct-1',
                    description: null,
                    peer_interface_id: 'if-other',
                    peer_interface_name: 'Gi0/2',
                    peer_device_id: 'dev-2',
                    peer_device_name: 'sw-02',
                    peer_is_management: peer.is_management,
                    peer_is_data_transfer: peer.is_data_transfer,
                    peer_vlan_mode: peer.vlan_mode,
                  },
                ],
              }),
            )
          }
          return emptyList()
        }),
      )
      return mount(DeviceFormModal, { props: { device } })
    }

    const matching = { is_management: false, is_data_transfer: true, vlan_mode: 'trunk' }

    it('порт, сохраняемый с НОВОЙ конфигурацией, расходящейся с соседом, вызывает toast с именами портов', async () => {
      const wrapper = mountWithNeighbour(matching, matching) // при открытии формы расхождения нет
      await flushPromises()

      await wrapper.find('tr:not(.bulk-edit-row) td.col-check input').setValue(true) // «Управление» включено только у этого порта
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(useToast().toasts.map((t) => t.type)).toEqual(['warning']) // предупреждение, а не нейтральное «инфо»
      const messages = useToast().toasts.map((t) => t.message)
      expect(messages).toHaveLength(1)
      expect(messages[0]).toContain('Gi0/1')
      expect(messages[0]).toContain('sw-02')
      expect(wrapper.emitted('saved')).toBeTruthy()
    })

    it('расхождение уже существовало на момент открытия и порт не менялся — повторного уведомления нет', async () => {
      const wrapper = mountWithNeighbour({ ...matching, is_management: true }, matching)
      await flushPromises()

      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(useToast().toasts).toHaveLength(0)
      expect(wrapper.emitted('saved')).toBeTruthy()
    })

    it('порт изменён, но совпадает с соседом — уведомления нет', async () => {
      const wrapper = mountWithNeighbour({ ...matching, is_management: true }, matching) // изначально расходился
      await flushPromises()

      await wrapper.find('tr:not(.bulk-edit-row) td.col-check input').setValue(false) // привели к конфигурации соседа
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(useToast().toasts).toHaveLength(0)
    })
  })
})

// Фейковый GET /devices/options (backend services/device_connectivity.py:list_device_options): устройства для выбора соседа
// ищутся на сервере, а не берутся из стора устройств. Редактируемое устройство форма просит исключить (exclude).
const SERVER_DEVICES = [
  { id: 'dev-1', system_name: 'srv-1', serial_number: 'SN-1' },
  { id: 'dev-b', system_name: 'sw-b', serial_number: 'SN-B' },
]
function deviceOptionsResponse(url: string): Response | undefined {
  if (!/\/devices\/options\?/.test(url)) return undefined
  const params = new URLSearchParams(url.split('?')[1])
  const exclude = new Set(params.getAll('exclude'))
  const include = new Set(params.getAll('include'))
  const q = (params.get('q') ?? '').toLowerCase()
  const items = SERVER_DEVICES.filter(
    (d) => !exclude.has(d.id) && (include.has(d.id) || !q || d.system_name.toLowerCase().includes(q) || d.serial_number.toLowerCase().includes(q)),
  ).map((d) => ({ id: d.id, label: d.system_name, system_name: d.system_name, serial_number: d.serial_number }))
  return new Response(JSON.stringify({ items, total: items.length, offset: 0, limit: 50 }))
}

describe('подключения портов в блоке «Порты / интерфейсы» формы устройства', () => {
  const emptyList = () => new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
  type Call = { url: string; method: string; body?: Record<string, unknown> }

  // Ответы сервера для блока «Подключение» (backend services/device_connectivity.py): свободные порты соседа sw-b
  // (Gi0/1 с включённым «Управлением») и подключения редактируемого устройства dev-1. Занятый порт сервер отдаёт
  // только по явному include — как делает форма для текущего соседа.
  let connectivityState: { peerBusy: boolean; own: Array<Record<string, unknown>> }
  function connectivity(url: string): Response | undefined {
    const devices = deviceOptionsResponse(url)
    if (devices) return devices
    if (/\/devices\/dev-b\/free-interfaces\?/.test(url)) {
      const include = new URLSearchParams(url.split('?')[1]).getAll('include')
      const items =
        connectivityState.peerBusy && !include.includes('b-1')
          ? []
          : [{ id: 'b-1', name: 'Gi0/1', is_management: true, is_data_transfer: false, vlan_mode: 'access', occupied: connectivityState.peerBusy }]
      return new Response(JSON.stringify({ items, total: items.length, offset: 0, limit: 200 }))
    }
    if (/\/devices\/dev-1\/interface-connections$/.test(url)) return new Response(JSON.stringify({ items: connectivityState.own }))
    return undefined
  }
  const ownConnectionRow = {
    interface_id: 'if-1',
    connection_id: 'c-1',
    connection_type_id: 'ct-1',
    description: null,
    peer_interface_id: 'b-1',
    peer_interface_name: 'Gi0/1',
    peer_device_id: 'dev-b',
    peer_device_name: 'sw-b',
    peer_is_management: true,
    peer_is_data_transfer: false,
    peer_vlan_mode: 'access',
  }

  // Соседнее устройство sw-b с портом Gi0/1 (у него включено «Управление»), тип линии «Витая пара».
  function seedStores(connections: Array<Record<string, unknown>> = [], own: Array<Record<string, unknown>> = []) {
    connectivityState = { peerBusy: own.length > 0, own }
    useToast().toasts.splice(0)
    const devices = useDevicesStore()
    devices.all = [
      { id: 'dev-1', system_name: 'srv-1', serial_number: 'SN-1' },
      { id: 'dev-b', system_name: 'sw-b', serial_number: 'SN-B' },
    ] as never
    devices.loaded = true
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = [
      { id: 'b-1', physical_device_id: 'dev-b', name: 'Gi0/1', is_management: true, is_data_transfer: false, vlan_mode: 'access' },
    ] as never
    catalogs.items['connection-types'] = [{ id: 'ct-1', name: 'Витая пара' }] as never
    const store = useConnectionsStore()
    store.all = connections as never
    store.loaded = true
  }

  function recordingFetch(handlers: (url: string, method: string) => Response | undefined) {
    const calls: Call[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        return handlers(url, method) ?? connectivity(url) ?? emptyList()
      }),
    )
    return calls
  }

  async function pick(wrapper: ReturnType<typeof mount>, block: string, label: string) {
    const select = wrapper.find(`${block} .searchable-select`)
    await select.find('input').trigger('focus')
    await flushPromises() // устройства-соседи запрашиваются у сервера при открытии списка
    const option = select.findAll('.ss-option').find((o) => o.text() === label)
    if (!option) throw new Error(`«${label}» нет в списке выбора ${block}`)
    await option.trigger('mousedown')
  }

  // Кнопка диалога «расхождение с соседом» (DeviceInterfacesEditor.vue), который форма показывает при «Сохранить».
  const reviewButton = (wrapper: ReturnType<typeof mount>, text: string) => {
    const button = wrapper.findAll('.review-modal button').find((b) => b.text() === text)
    if (!button) throw new Error(`В диалоге расхождений нет кнопки «${text}»`)
    return button
  }

  async function mountNewDeviceWithPort() {
    stubCatalogsFetch()
    await useCatalogsStore().ensureLoaded()
    seedStores()
    const wrapper = mount(DeviceFormModal, { props: { device: null } })
    await flushPromises()
    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-NEW')
    await wrapper.find('.empty button.btn-secondary').trigger('click') // + Интерфейс (список пуст)
    await wrapper.find('.iface-table input.cell-input').setValue('eth0')
    await wrapper.find('.expand-toggle').trigger('click')
    return wrapper
  }

  it('новое устройство: подключение нового порта уходит в тот же PUT, что и порт; после сохранения — предупреждение о расхождении с соседом', async () => {
    const wrapper = await mountNewDeviceWithPort()
    const calls = recordingFetch((url, method) => {
      if (method === 'POST' && url.includes('/resources/devices'))
        return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-NEW' }), { status: 201 })
      if (method === 'PUT' && url.includes('/devices/dev-new/interfaces')) {
        return new Response(
          JSON.stringify({
            items: [{ id: 'if-new', physical_device_id: 'dev-new', name: 'eth0', is_management: false, is_data_transfer: false, vlan_mode: 'access' }],
            groups: [],
          }),
        )
      }
      // Соседа для предупреждения форма спрашивает у сервера по только что сохранённому устройству.
      if (method === 'GET' && /\/devices\/dev-new\/interface-connections$/.test(url)) {
        return new Response(
          JSON.stringify({
            items: [
              {
                interface_id: 'if-new',
                connection_id: 'c-new',
                connection_type_id: 'ct-1',
                description: 'патч-корд №5',
                peer_interface_id: 'b-1',
                peer_interface_name: 'Gi0/1',
                peer_device_id: 'dev-b',
                peer_device_name: 'sw-b',
                peer_is_management: true,
                peer_is_data_transfer: false,
                peer_vlan_mode: 'access',
              },
            ],
          }),
        )
      }
      if (method === 'GET' && url.includes('/resources/connections')) return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      return undefined
    })

    await wrapper.find('.connection-connect-btn').trigger('click')
    await pick(wrapper, '.connection-peer-device', 'sw-b')
    await flushPromises() // свободные порты sw-b приходят с сервера
    await pick(wrapper, '.connection-peer-port', 'Gi0/1')
    await pick(wrapper, '.connection-type', 'Витая пара')
    await wrapper.find('.connection-description input').setValue('патч-корд №5')
    expect(wrapper.find('.connection-diffs').text()).toContain('«Управление»: нет / у соседа да') // видно ещё до сохранения

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // Расхождение видно ДО записи — диалогом, а не только уведомлением после неё; пока выбора нет, ничего не записано.
    expect(wrapper.find('.review-modal').text()).toContain('Порт «eth0» ↔ «Gi0/1» (sw-b)')
    expect(wrapper.find('.review-modal').text()).toContain('«Управление»: нет / у соседа да')
    expect(calls.filter((c) => c.method !== 'GET')).toEqual([])
    await reviewButton(wrapper, 'Сохранить как есть').trigger('click')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-new/interfaces'))
    expect(put?.body).toMatchObject({
      interfaces: [{ name: 'eth0', connection: { peer_interface_id: 'b-1', connection_type_id: 'ct-1', description: 'патч-корд №5' } }],
    })
    expect(calls.some((c) => c.method === 'GET' && c.url.includes('/devices/dev-new/interface-connections'))).toBe(true) // сосед — у сервера
    expect(calls.some((c) => c.method === 'GET' && c.url.includes('/resources/connections'))).toBe(true) // общий список был загружен — обновлён
    expect(wrapper.emitted('saved')).toBeTruthy()
    const toasts = useToast().toasts
    expect(toasts.map((t) => t.type)).toEqual(['warning'])
    expect(toasts[0].message).toContain('eth0')
    expect(toasts[0].message).toContain('sw-b')
  })

  it('соседей форма ищет у сервера: ни полный список устройств, ни общий список подключений при этом не запрашиваются', async () => {
    stubCatalogsFetch()
    await useCatalogsStore().ensureLoaded()
    seedStores()
    useDevicesStore().loaded = false
    useConnectionsStore().loaded = false
    const calls = recordingFetch(() => undefined)
    const wrapper = mount(DeviceFormModal, { props: { device: null } })
    await flushPromises()
    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-NEW')
    await wrapper.find('.empty button.btn-secondary').trigger('click')
    await wrapper.find('.iface-table input.cell-input').setValue('eth0')
    await wrapper.find('.expand-toggle').trigger('click')
    await wrapper.find('.connection-connect-btn').trigger('click')
    await pick(wrapper, '.connection-peer-device', 'sw-b')

    expect(calls.some((c) => /\/api\/v1\/devices(\?|$)/.test(c.url))).toBe(false) // GET /devices — весь реестр устройств
    expect(calls.some((c) => c.url.includes('/resources/connections'))).toBe(false)
    expect(calls.some((c) => c.url.includes('/devices/options?'))).toBe(true)
  })

  it('общий список подключений не загружается, пока им никто не пользуется: форма его ни открывает, ни перезагружает', async () => {
    const wrapper = await mountNewDeviceWithPort()
    useConnectionsStore().loaded = false
    const calls = recordingFetch((url, method) => {
      if (method === 'POST' && url.includes('/resources/devices'))
        return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-NEW' }), { status: 201 })
      if (method === 'PUT' && url.includes('/devices/dev-new/interfaces')) {
        return new Response(
          JSON.stringify({
            items: [{ id: 'if-new', physical_device_id: 'dev-new', name: 'eth0', is_management: true, is_data_transfer: false, vlan_mode: 'access' }],
            groups: [],
          }),
        )
      }
      if (method === 'GET' && /\/devices\/dev-new\/interface-connections$/.test(url)) {
        return new Response(
          JSON.stringify({
            items: [
              {
                interface_id: 'if-new',
                connection_id: 'c-new',
                connection_type_id: 'ct-1',
                description: null,
                peer_interface_id: 'b-1',
                peer_interface_name: 'Gi0/1',
                peer_device_id: 'dev-b',
                peer_device_name: 'sw-b',
                peer_is_management: true,
                peer_is_data_transfer: false,
                peer_vlan_mode: 'access',
              },
            ],
          }),
        )
      }
      return undefined
    })

    await wrapper.find('.connection-connect-btn').trigger('click')
    await pick(wrapper, '.connection-peer-device', 'sw-b')
    await flushPromises()
    await pick(wrapper, '.connection-peer-port', 'Gi0/1')
    await pick(wrapper, '.connection-type', 'Витая пара')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await reviewButton(wrapper, 'Сохранить как есть').trigger('click') // расхождение с соседом — диалог перед записью
    await flushPromises()

    expect(calls.some((c) => c.url.includes('/resources/connections'))).toBe(false)
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  describe('диалог расхождения с соседом при «Сохранить»', () => {
    // Новое устройство с портом eth0 (ни «Управление», ни «Передача данных») подключено к sw-b · Gi0/1 с «Управление».
    async function connectedNewDevice() {
      const wrapper = await mountNewDeviceWithPort()
      const calls = recordingFetch((url, method) => {
        if (method === 'POST' && url.includes('/resources/devices'))
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-NEW' }), { status: 201 })
        if (method === 'PUT' && url.includes('/devices/dev-new/interfaces')) {
          // Сервер возвращает порт таким, каким его прислали (calls.at(-1) — этот самый запрос).
          const sent = (calls.at(-1)?.body as { interfaces?: Array<{ is_management?: boolean }> } | undefined)?.interfaces?.[0]
          return new Response(
            JSON.stringify({
              items: [
                {
                  id: 'if-new',
                  physical_device_id: 'dev-new',
                  name: 'eth0',
                  is_management: !!sent?.is_management,
                  is_data_transfer: false,
                  vlan_mode: 'access',
                },
              ],
              groups: [],
            }),
          )
        }
        if (method === 'GET' && /\/devices\/dev-new\/interface-connections$/.test(url)) return new Response(JSON.stringify({ items: [] }))
        if (method === 'GET' && url.includes('/resources/connections')) return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
        return undefined
      })
      await wrapper.find('.connection-connect-btn').trigger('click')
      await pick(wrapper, '.connection-peer-device', 'sw-b')
      await flushPromises()
      await pick(wrapper, '.connection-peer-port', 'Gi0/1')
      await pick(wrapper, '.connection-type', 'Витая пара')
      return { wrapper, calls }
    }

    it('«Вернуться к форме»: ничего не записано, форма остаётся открытой, «Сохранить» снова доступно', async () => {
      const { wrapper, calls } = await connectedNewDevice()
      await wrapper.find('form').trigger('submit')
      await flushPromises()
      expect(wrapper.find('.review-modal').exists()).toBe(true)

      await reviewButton(wrapper, 'Вернуться к форме').trigger('click')
      await flushPromises()

      expect(wrapper.find('.review-modal').exists()).toBe(false)
      expect(calls.filter((c) => c.method !== 'GET')).toEqual([])
      expect(wrapper.emitted('saved')).toBeFalsy()
      expect(wrapper.find('.modal-foot .btn-primary').attributes('disabled')).toBeUndefined()
    })

    it('«Применить конфигурацию соседа» в диалоге: порт получает назначение соседа, в запись уходит уже оно, уведомления о расхождении нет', async () => {
      const { wrapper, calls } = await connectedNewDevice()
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      await reviewButton(wrapper, 'Применить конфигурацию соседа').trigger('click')
      await flushPromises()
      expect(wrapper.find('.review-modal').text()).toContain('Расхождений не осталось')
      expect(calls.filter((c) => c.method !== 'GET')).toEqual([])

      await reviewButton(wrapper, 'Сохранить').trigger('click')
      await flushPromises()

      const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-new/interfaces'))
      expect(put?.body).toMatchObject({ interfaces: [{ name: 'eth0', is_management: true, is_data_transfer: false }] })
      expect(wrapper.emitted('saved')).toBeTruthy()
      // Уведомление «Порты сохранены, но конфигурация расходится…» не нужно: расхождение устранено до записи.
      expect(useToast().toasts.map((t) => t.type)).not.toContain('warning')
    })

    it('без расхождения (конфигурации совпадают) диалога нет — сохранение идёт сразу', async () => {
      const { wrapper, calls } = await connectedNewDevice()
      await wrapper.find('.iface-table .col-check input[type="checkbox"]').setValue(true) // «Управление» — как у соседа
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(wrapper.find('.review-modal').exists()).toBe(false)
      expect(calls.some((c) => c.method === 'PUT' && c.url.includes('/devices/dev-new/interfaces'))).toBe(true)
    })
  })

  it('«Подключить» без выбора порта соседа и типа линии не отправляет запросов и показывает ошибку', async () => {
    const wrapper = await mountNewDeviceWithPort()
    const calls = recordingFetch(() => undefined)

    await wrapper.find('.connection-connect-btn').trigger('click')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Для порта «eth0» выберите устройство и порт')
    expect(calls.filter((c) => c.method !== 'GET')).toEqual([])
    expect(wrapper.emitted('saved')).toBeFalsy()
  })

  describe('редактирование устройства с уже подключённым портом', () => {
    const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' } as never
    const existing = {
      id: 'c-1',
      source_interface_id: 'if-1',
      destination_interface_id: 'b-1',
      connection_type_id: 'ct-1',
      is_active: true,
      description: null,
      source_device_name: 'srv-1',
      source_interface_name: 'eth0',
      destination_device_name: 'sw-b',
      destination_interface_name: 'Gi0/1',
    }
    const port = { id: 'if-1', physical_device_id: 'dev-1', name: 'eth0', is_management: true, is_data_transfer: false, vlan_mode: 'access' }

    // devicesCold — стор устройств и общий список подключений не загружены: так видно, обращается ли к ним сама форма.
    function mountEdit(devicesCold = false) {
      seedStores([existing], [ownConnectionRow])
      if (devicesCold) {
        useDevicesStore().loaded = false
        useConnectionsStore().loaded = false
      }
      useCatalogsStore().items['interfaces'] = [
        port,
        { id: 'b-1', physical_device_id: 'dev-b', name: 'Gi0/1', is_management: true, is_data_transfer: false, vlan_mode: 'access' },
      ] as never
      const calls = recordingFetch((url, method) => {
        if (method === 'PUT' && url.includes('/devices/dev-1/interfaces')) return new Response(JSON.stringify({ items: [port], groups: [] }))
        if (method === 'PUT' && url.includes('/resources/devices/dev-1')) return new Response(JSON.stringify(device))
        if (method === 'GET' && url.includes('/resources/interfaces')) return new Response(JSON.stringify({ items: [port], total: 1, offset: 0, limit: 1000 }))
        return undefined
      })
      return { wrapper: mount(DeviceFormModal, { props: { device } }), calls }
    }

    it('при открытии на редактирование подпись соседа приходит из подключения устройства, а полный список устройств не запрашивается', async () => {
      const { wrapper, calls } = mountEdit(true)
      await flushPromises()

      expect(wrapper.find('.expand-toggle').text()).toContain('↔ sw-b · Gi0/1') // «sw-b» — peer_device_name из interface-connections
      expect(calls.some((c) => /\/api\/v1\/devices(\?|$)/.test(c.url))).toBe(false)
      expect(calls.some((c) => c.url.includes('/resources/connections'))).toBe(false)
      expect(calls.some((c) => c.url.includes('/devices/options?'))).toBe(false) // список устройств — только по открытию выпадающего списка
    })

    it('показывает текущее подключение в строке порта; без правок подключения ключ connection не отправляется и стор не перезагружается', async () => {
      const { wrapper, calls } = mountEdit()
      await flushPromises()
      expect(wrapper.find('.expand-toggle').text()).toContain('↔ sw-b · Gi0/1')

      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-1/interfaces'))
      expect(put?.body?.interfaces).toHaveLength(1)
      expect((put?.body?.interfaces as Array<Record<string, unknown>>)[0]).not.toHaveProperty('connection')
      expect(calls.some((c) => c.url.includes('/resources/connections'))).toBe(false)
      expect(wrapper.emitted('saved')).toBeTruthy()
    })

    it('«Отключить» отправляет connection: null, сохранение обновляет стор подключений', async () => {
      const { wrapper, calls } = mountEdit()
      await flushPromises()
      await wrapper.find('.expand-toggle').trigger('click')

      await wrapper.find('.connection-disconnect-btn').trigger('click')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-1/interfaces'))
      expect((put?.body?.interfaces as Array<Record<string, unknown>>)[0]).toMatchObject({ id: 'if-1', connection: null })
      expect(calls.some((c) => c.method === 'GET' && c.url.includes('/resources/connections'))).toBe(true)
    })

    it('изменение типа линии отправляет обновлённое подключение с тем же соседом', async () => {
      const { wrapper, calls } = mountEdit()
      useCatalogsStore().items['connection-types'] = [
        { id: 'ct-1', name: 'Витая пара' },
        { id: 'ct-2', name: 'Оптическое волокно' },
      ] as never
      await flushPromises()
      await wrapper.find('.expand-toggle').trigger('click')

      await pick(wrapper, '.connection-type', 'Оптическое волокно')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-1/interfaces'))
      expect((put?.body?.interfaces as Array<Record<string, unknown>>)[0].connection).toEqual({
        peer_interface_id: 'b-1',
        connection_type_id: 'ct-2',
        description: null,
      })
    })
  })

  it('копия устройства не наследует подключения донора: порты копии сохраняются без connection', async () => {
    const donor = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' } as never
    const port = { id: 'if-1', physical_device_id: 'dev-1', name: 'eth0', is_management: true, is_data_transfer: false, vlan_mode: 'access' }
    seedStores(
      [{ id: 'c-1', source_interface_id: 'if-1', destination_interface_id: 'b-1', connection_type_id: 'ct-1', is_active: true, description: null }],
      [ownConnectionRow],
    )
    useCatalogsStore().items['interfaces'] = [
      port,
      { id: 'b-1', physical_device_id: 'dev-b', name: 'Gi0/1', is_management: true, is_data_transfer: false, vlan_mode: 'access' },
    ] as never
    const calls = recordingFetch((url, method) => {
      if (method === 'POST' && url.includes('/resources/devices'))
        return new Response(JSON.stringify({ id: 'dev-copy', serial_number: 'SN-COPY' }), { status: 201 })
      if (method === 'PUT' && url.includes('/devices/dev-copy/interfaces')) return new Response(JSON.stringify({ items: [], groups: [] }))
      if (method === 'GET' && url.includes('/resources/interfaces')) return new Response(JSON.stringify({ items: [port], total: 1, offset: 0, limit: 1000 }))
      return undefined
    })

    const wrapper = mount(DeviceFormModal, { props: { device: null, copyFrom: donor } })
    await flushPromises()
    expect(wrapper.find('.expand-toggle').text()).not.toContain('↔')
    await setSerial(wrapper, 'SN-COPY')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-copy/interfaces'))
    expect((put?.body?.interfaces as Array<Record<string, unknown>>)[0]).not.toHaveProperty('connection')
  })
})

describe('сбой после создания устройства: повторное сохранение не создаёт дубль', () => {
  type Call = { url: string; method: string; body?: any }

  // Сервер, у которого PUT портов падает, пока failInterfaces=true: первый POST устройства проходит.
  function serverWithFailingInterfaces() {
    const state = { failInterfaces: true, calls: [] as Call[] }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        state.calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/devices')) {
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-R' }), { status: 201 })
        }
        if (method === 'PUT' && url.includes('/resources/devices/dev-new')) {
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-R' }))
        }
        if (method === 'PUT' && url.includes('/devices/dev-new/interfaces')) {
          if (state.failInterfaces) return new Response(JSON.stringify({ detail: 'Порт соседа уже участвует в другом подключении.' }), { status: 409 })
          return new Response(JSON.stringify({ items: [{ id: 'if-1', physical_device_id: 'dev-new', name: 'eth0', vlan_mode: 'access' }] }))
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )
    return state
  }

  async function fillNewDeviceWithPort(wrapper: Awaited<ReturnType<typeof mountWithLoadedCatalogs>>) {
    await wrapper.find('.empty button.btn-secondary').trigger('click') // + Интерфейс (список пуст)
    await wrapper.find('.iface-table input.cell-input').setValue('eth0')
    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-R')
  }

  const countCalls = (calls: Call[], method: string, urlPart: string) => calls.filter((c) => c.method === method && c.url.includes(urlPart)).length

  it('сбой сохранения портов: форма остаётся открытой, честно сообщает, что устройство уже создано, и обновляет список устройств', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    await fillNewDeviceWithPort(wrapper)
    const state = serverWithFailingInterfaces()

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.emitted('saved')).toBeFalsy()
    expect(wrapper.find('.form-error').text()).toContain(
      'Устройство создано, но остальные данные сохранить не удалось: Порт соседа уже участвует в другом подключении.',
    )
    expect(wrapper.find('.form-error').text()).toContain('будет обновлено, а не создано повторно')
    expect(state.calls.some((c) => c.method === 'GET' && /\/devices(\?|$)/.test(c.url))).toBe(true) // список устройств перезагружен
    expect(wrapper.find('h2').text()).toBe('Редактировать устройство')
    expect(wrapper.find('.modal-foot .btn-primary').text()).toBe('Сохранить')
  })

  it('повторное «Сохранить» обновляет созданное устройство (PUT), а не создаёт новое (POST), и доводит порты до конца', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    await fillNewDeviceWithPort(wrapper)
    const state = serverWithFailingInterfaces()

    await wrapper.find('form').trigger('submit')
    await flushPromises()
    state.failInterfaces = false
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(countCalls(state.calls, 'POST', '/resources/devices')).toBe(1) // единственное создание
    expect(countCalls(state.calls, 'PUT', '/resources/devices/dev-new')).toBe(1) // повтор — обновление
    expect(countCalls(state.calls, 'PUT', '/devices/dev-new/interfaces')).toBe(2)
    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(wrapper.emitted('saved')![0][0]).toMatchObject({ id: 'dev-new' })
  })

  it('связь с доменом, уже созданная первой попыткой, при повторе не создаётся второй раз', async () => {
    // Сторы VLAN и доменов заполняем ДО монтирования: иначе форма загрузит их заново и затрёт пустым ответом.
    const vlans = useVLANsStore()
    vlans.groups = []
    vlans.loaded = true
    const vlanDomains = useVLANDomainsStore()
    vlanDomains.all = [{ id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: null, auto_sync: false }]
    vlanDomains.loaded = true
    const wrapper = await mountWithLoadedCatalogs()
    await fillNewDeviceWithPort(wrapper)
    const state = serverWithFailingInterfaces()

    const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
    await vlanEditor.find('.join-domain-row select').setValue('dom-1')
    await vlanEditor.find('.join-domain-row button').trigger('click')

    await wrapper.find('form').trigger('submit')
    await flushPromises()
    state.failInterfaces = false
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(countCalls(state.calls, 'POST', '/resources/vlan-domain-devices')).toBe(1)
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })

  it('сбой самого создания устройства (до появления id) выводит исходную ошибку, форма остаётся «Добавить», повтор снова создаёт', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-R')
    const calls: Call[] = []
    let failCreate = true
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        if (method === 'POST' && url.endsWith('/resources/devices')) {
          return failCreate
            ? new Response(JSON.stringify({ detail: 'Серийный номер уже используется.' }), { status: 409 })
            : new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-R' }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('.form-error').text()).toContain('Серийный номер уже используется.')
    expect(wrapper.find('.form-error').text()).not.toContain('Устройство создано')
    expect(wrapper.find('h2').text()).toBe('Добавить устройство')

    failCreate = false
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(countCalls(calls, 'POST', '/resources/devices')).toBe(2)
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
})

describe('подключения между портами одного устройства и обмен соседями в форме устройства', () => {
  const emptyList = () => new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
  type Call = { url: string; method: string; body?: Record<string, any> }

  function seed(connections: Array<Record<string, unknown>>, ports: Array<Record<string, unknown>>) {
    const devices = useDevicesStore()
    devices.all = [
      { id: 'dev-1', system_name: 'srv-1', serial_number: 'SN-1' },
      { id: 'dev-b', system_name: 'sw-b', serial_number: 'SN-B' },
    ] as never
    devices.loaded = true
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = ports as never
    catalogs.items['connection-types'] = [{ id: 'ct-1', name: 'Витая пара' }] as never
    const store = useConnectionsStore()
    store.all = connections as never
    store.loaded = true
  }

  function recordingFetch(handlers: (url: string, method: string) => Response | undefined) {
    const calls: Call[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        return handlers(url, method) ?? deviceOptionsResponse(url) ?? emptyList()
      }),
    )
    return calls
  }

  // Поле выбора внутри блока «Подключение» строки с индексом row.
  async function pickIn(wrapper: ReturnType<typeof mount>, row: number, block: string, label: string) {
    const select = wrapper.findAll('.connection-block')[row].find(`${block} .searchable-select`)
    await select.find('input').trigger('focus')
    await flushPromises() // список устройств-соседей приходит с сервера
    const option = select.findAll('.ss-option').find((o) => o.text() === label)
    if (!option) throw new Error(`«${label}» нет в списке выбора ${block} строки ${row}`)
    await option.trigger('mousedown')
  }
  async function optionsIn(wrapper: ReturnType<typeof mount>, row: number, block: string): Promise<string[]> {
    const select = wrapper.findAll('.connection-block')[row].find(`${block} .searchable-select`)
    await select.find('input').trigger('focus')
    await flushPromises()
    return select.findAll('.ss-option').map((o) => o.text())
  }

  it('два новых порта нового устройства соединяются между собой: подключение уходит номером строки соседа (peer_row), служебный ключ не отправляется', async () => {
    stubCatalogsFetch()
    await useCatalogsStore().ensureLoaded()
    seed([], [])
    const wrapper = mount(DeviceFormModal, { props: { device: null } })
    await flushPromises()
    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-LOOP')
    await wrapper.find('.empty button.btn-secondary').trigger('click') // + Интерфейс
    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Интерфейс'))!
      .trigger('click') // + ещё один
    // В каждой строке два поля .cell-input (имя и MAC): имя первой строки — первое поле, второй — третье.
    const names = wrapper.findAll('.iface-table input.cell-input')
    await names[0].setValue('eth0')
    await names[2].setValue('eth1')
    await wrapper.findAll('.expand-toggle')[1].trigger('click')
    await wrapper.findAll('.expand-toggle')[0].trigger('click')

    const calls = recordingFetch((url, method) => {
      if (method === 'POST' && url.includes('/resources/devices'))
        return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-LOOP' }), { status: 201 })
      if (method === 'PUT' && url.includes('/devices/dev-new/interfaces')) {
        return new Response(
          JSON.stringify({
            items: [
              { id: 'if-0', physical_device_id: 'dev-new', name: 'eth0', vlan_mode: 'access' },
              { id: 'if-1', physical_device_id: 'dev-new', name: 'eth1', vlan_mode: 'access' },
            ],
            groups: [],
          }),
        )
      }
      return undefined
    })

    await wrapper.findAll('.connection-connect-btn')[0].trigger('click')
    await pickIn(wrapper, 0, '.connection-peer-device', 'Это устройство (новое)')
    await pickIn(wrapper, 0, '.connection-peer-port', 'eth1 (строка 2)')
    await pickIn(wrapper, 0, '.connection-type', 'Витая пара')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-new/interfaces'))
    expect(put?.body?.interfaces[0]).toMatchObject({ name: 'eth0', connection: { peer_row: 1, connection_type_id: 'ct-1', description: null } })
    expect(put?.body?.interfaces[0].connection).not.toHaveProperty('peer_interface_id')
    expect(put?.body?.interfaces[1]).toMatchObject({ name: 'eth1' })
    expect(put?.body?.interfaces[1]).not.toHaveProperty('connection') // кабель описан с одной стороны
    expect(put?.body?.interfaces.every((i: Record<string, unknown>) => !('key' in i))).toBe(true)
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('порты меняются соседями за одно сохранение: освобождённый одним портом сосед становится доступен другому без промежуточного сохранения', async () => {
    const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' } as never
    const own = [
      { id: 'if-1', physical_device_id: 'dev-1', name: 'eth0', is_management: false, is_data_transfer: true, vlan_mode: 'access' },
      { id: 'if-2', physical_device_id: 'dev-1', name: 'eth1', is_management: false, is_data_transfer: true, vlan_mode: 'access' },
    ]
    const theirs = [
      { id: 'b-1', physical_device_id: 'dev-b', name: 'Gi0/1', is_management: false, is_data_transfer: true, vlan_mode: 'access' },
      { id: 'b-2', physical_device_id: 'dev-b', name: 'Gi0/2', is_management: false, is_data_transfer: true, vlan_mode: 'access' },
    ]
    seed(
      [
        { id: 'c-1', source_interface_id: 'if-1', destination_interface_id: 'b-1', connection_type_id: 'ct-1', is_active: true, description: null },
        { id: 'c-2', source_interface_id: 'if-2', destination_interface_id: 'b-2', connection_type_id: 'ct-1', is_active: true, description: null },
      ],
      [...own, ...theirs],
    )
    // Сервер знает, что Gi0/1 и Gi0/2 заняты портами eth0 / eth1: занятые порты он отдаёт только по явному include.
    const occupiedByServer = new Set(['b-1', 'b-2'])
    const calls = recordingFetch((url, method) => {
      if (method === 'PUT' && url.includes('/devices/dev-1/interfaces')) return new Response(JSON.stringify({ items: own, groups: [] }))
      if (method === 'PUT' && url.includes('/resources/devices/dev-1')) return new Response(JSON.stringify(device))
      if (method === 'GET' && /\/devices\/dev-b\/free-interfaces\?/.test(url)) {
        const include = new URLSearchParams(url.split('?')[1]).getAll('include')
        const items = theirs
          .filter((p) => !occupiedByServer.has(p.id) || include.includes(p.id))
          .map((p) => ({ id: p.id, name: p.name, is_management: false, is_data_transfer: true, vlan_mode: 'access', occupied: occupiedByServer.has(p.id) }))
        return new Response(JSON.stringify({ items, total: items.length, offset: 0, limit: 200 }))
      }
      if (method === 'GET' && /\/devices\/dev-1\/interface-connections$/.test(url)) {
        const row = (iface: string, conn: string, peer: string, peerName: string) => ({
          interface_id: iface,
          connection_id: conn,
          connection_type_id: 'ct-1',
          description: null,
          peer_interface_id: peer,
          peer_interface_name: peerName,
          peer_device_id: 'dev-b',
          peer_device_name: 'sw-b',
          peer_is_management: false,
          peer_is_data_transfer: true,
          peer_vlan_mode: 'access',
        })
        return new Response(JSON.stringify({ items: [row('if-1', 'c-1', 'b-1', 'Gi0/1'), row('if-2', 'c-2', 'b-2', 'Gi0/2')] }))
      }
      if (method === 'GET' && url.includes('/resources/interfaces')) return new Response(JSON.stringify({ items: own, total: 2, offset: 0, limit: 1000 }))
      return undefined
    })
    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()
    await wrapper.findAll('.expand-toggle')[1].trigger('click')
    await wrapper.findAll('.expand-toggle')[0].trigger('click')
    await flushPromises() // порты соседа приходят с сервера

    // Пока eth1 держит Gi0/2, eth0 выбрать его не может.
    expect(await optionsIn(wrapper, 0, '.connection-peer-port')).toEqual(['Gi0/1'])

    await wrapper.findAll('.connection-disconnect-btn')[1].trigger('click') // eth1 отключён → Gi0/2 свободен
    await flushPromises() // форма просит у сервера порты с учётом освобождённых (include)
    await pickIn(wrapper, 0, '.connection-peer-port', 'Gi0/2') // eth0 → Gi0/2 → Gi0/1 свободен
    await flushPromises()
    await wrapper.findAll('.connection-connect-btn')[0].trigger('click') // у eth1 теперь «Подключить»
    await pickIn(wrapper, 1, '.connection-peer-device', 'sw-b')
    await flushPromises()
    await pickIn(wrapper, 1, '.connection-peer-port', 'Gi0/1')
    await pickIn(wrapper, 1, '.connection-type', 'Витая пара')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-1/interfaces'))
    expect(put?.body?.interfaces[0]).toMatchObject({ id: 'if-1', connection: { peer_interface_id: 'b-2', connection_type_id: 'ct-1' } })
    expect(put?.body?.interfaces[1]).toMatchObject({ id: 'if-2', connection: { peer_interface_id: 'b-1', connection_type_id: 'ct-1' } })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('порт соседа, выбранный строкой, но убранный удалением строки, не уходит на сервер: форма просит выбрать другого соседа', async () => {
    stubCatalogsFetch()
    await useCatalogsStore().ensureLoaded()
    seed([], [])
    const wrapper = mount(DeviceFormModal, { props: { device: null } })
    await flushPromises()
    await pickTypeModel(wrapper, 'Сервер')
    await setSerial(wrapper, 'SN-DEL')
    await wrapper.find('.empty button.btn-secondary').trigger('click')
    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('Интерфейс'))!
      .trigger('click')
    // В каждой строке два поля .cell-input (имя и MAC): имя первой строки — первое поле, второй — третье.
    const names = wrapper.findAll('.iface-table input.cell-input')
    await names[0].setValue('eth0')
    await names[2].setValue('eth1')
    await wrapper.findAll('.expand-toggle')[0].trigger('click')
    await wrapper.findAll('.connection-connect-btn')[0].trigger('click')
    await pickIn(wrapper, 0, '.connection-peer-device', 'Это устройство (новое)')
    await pickIn(wrapper, 0, '.connection-peer-port', 'eth1 (строка 2)')
    await pickIn(wrapper, 0, '.connection-type', 'Витая пара')

    await wrapper.findAll('button[aria-label="Удалить интерфейс"]')[1].trigger('click') // удалили eth1
    const calls = recordingFetch(() => undefined)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Для порта «eth0» выберите устройство и порт')
    expect(calls.filter((c) => c.method !== 'GET')).toEqual([])
    expect(wrapper.emitted('saved')).toBeFalsy()
  })
})

describe('уведомление о согласовании портов после изменения списка VLAN устройства', () => {
  const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-1' } as never
  const emptyList = () => new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
  const summary = (patch: Record<string, number> = {}) => ({
    connections: 1,
    applicable: 0,
    shown: 0,
    total_items: 0,
    auto: 0,
    blocked: 0,
    manual: 0,
    ignored: 0,
    none: 0,
    skipped: 0,
    ...patch,
  })
  type Call = { url: string; method: string; body?: Record<string, unknown> }

  // Устройство с одним подключением; planSummary — что ответит сервер на предпросмотр, previewStatus — его код ответа.
  async function mountDevice(planSummary = summary({ auto: 1 }), previewStatus = 200) {
    useToast().toasts.splice(0)
    usePortSyncPlanRequest().close()
    const vlans = useVLANsStore()
    vlans.groups = [
      { vlan_id: 30, definitions: [{ id: 'v-30', vlan_id: 30, name: 'VLAN 30', description: '', domain_id: null, domain_name: '', devices: [] }] },
    ] as never
    vlans.loaded = true
    const connections = useConnectionsStore()
    connections.all = []
    connections.loaded = true
    const calls: Call[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'PUT' && url.includes('/devices/dev-1/vlans')) return new Response(JSON.stringify({ items: [] }))
        if (method === 'PUT' && url.includes('/devices/dev-1/interfaces')) return new Response(JSON.stringify({ items: [] }))
        if (method === 'PUT' && url.includes('/resources/devices/dev-1')) return new Response(JSON.stringify(device))
        if (/\/devices\/dev-1\/interface-connections$/.test(url)) {
          const link = {
            interface_id: 'if-1',
            connection_id: 'c-1',
            connection_type_id: 'ct',
            description: null,
            peer_interface_id: 'p',
            peer_interface_name: 'Gi0/2',
            peer_device_id: 'dev-2',
            peer_device_name: 'sw-02',
            peer_is_management: false,
            peer_is_data_transfer: true,
            peer_vlan_mode: 'trunk',
          }
          return new Response(JSON.stringify({ items: [link] }))
        }
        if (method === 'POST' && url.endsWith('/port-sync/preview')) {
          return previewStatus === 200
            ? new Response(JSON.stringify({ items: [], summary: planSummary, plan_hash: 'h' }))
            : new Response(JSON.stringify({ detail: 'сервер недоступен' }), { status: previewStatus })
        }
        return emptyList()
      }),
    )
    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()
    return { wrapper, calls }
  }

  async function addDeviceVlan(wrapper: VueWrapper) {
    const editor = () => wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
    await editor().find('button.add-btn').trigger('click')
    await wrapper.vm.$nextTick()
    await pickVlan(editor(), '30 — VLAN 30')
  }

  async function save(wrapper: VueWrapper) {
    await wrapper.find('form').trigger('submit')
    await flushPromises()
  }

  it('список VLAN изменён и у подключения есть что согласовать: предупреждение с кнопкой «Показать план», форма уже закрыта', async () => {
    const { wrapper, calls } = await mountDevice(summary({ auto: 2, manual: 1 }))
    await addDeviceVlan(wrapper)

    await save(wrapper)

    expect(wrapper.emitted('saved')).toBeTruthy()
    const [toast] = useToast().toasts
    expect(toast.type).toBe('warning')
    expect(toast.message).toContain('расхождение портов: 3')
    expect(toast.action?.label).toBe('Показать план')
    const preview = calls.find((c) => c.url.endsWith('/port-sync/preview'))
    expect(preview?.body).toMatchObject({ connection_ids: ['c-1'], limit: 1 }) // только подключения этого устройства, одна запись
  })

  it('нажатие на «Показать план» открывает окно плана по подключениям этого устройства', async () => {
    const { wrapper } = await mountDevice()
    await addDeviceVlan(wrapper)
    await save(wrapper)

    useToast().toasts[0].action?.run()

    expect(usePortSyncPlanRequest().request.value?.scope).toEqual({ connection_ids: ['c-1'] })
  })

  it('список VLAN не менялся — ни предпросмотра, ни уведомления', async () => {
    const { wrapper, calls } = await mountDevice()

    await save(wrapper)

    expect(wrapper.emitted('saved')).toBeTruthy()
    expect(calls.some((c) => c.url.endsWith('/port-sync/preview'))).toBe(false)
    expect(useToast().toasts).toHaveLength(0)
  })

  it('VLAN изменён, но согласовывать нечего (расхождений нет или всё «исключено правилом») — уведомления нет', async () => {
    const { wrapper } = await mountDevice(summary({ skipped: 1, ignored: 1 }))
    await addDeviceVlan(wrapper)

    await save(wrapper)

    expect(wrapper.emitted('saved')).toBeTruthy()
    expect(useToast().toasts).toHaveLength(0)
  })

  it('проверка не удалась: устройство всё равно сохранено, а о сбое проверки говорит отдельное предупреждение', async () => {
    const { wrapper } = await mountDevice(summary(), 500)
    await addDeviceVlan(wrapper)

    await save(wrapper)

    expect(wrapper.emitted('saved')).toBeTruthy()
    const [toast] = useToast().toasts
    expect(toast.type).toBe('warning')
    expect(toast.message).toContain('Устройство сохранено, но проверить, нужно ли согласование портов, не удалось')
    expect(toast.action).toBeUndefined()
  })
})

describe('подинтерфейсы портов: сквозное сохранение формы устройства', () => {
  type Call = { url: string; method: string; body?: any }
  const donor = { id: 'dev-s', device_type_id: 'dt-server', serial_number: 'SN-S' } as never
  const ifaceDto = {
    id: 'if-1',
    physical_device_id: 'dev-s',
    name: 'Gi0/0',
    interface_type_id: null,
    mac_address: null,
    speed_id: null,
    is_management: false,
    is_data_transfer: false,
    description: null,
    vlan_mode: 'trunk',
  }
  const subDto = {
    id: 'sub-1',
    parent_interface_id: 'if-1',
    name: 'Gi0/0.10',
    vlan_id: 'v-10',
    is_management: false,
    is_data_transfer: true,
    description: null,
    ips: [{ id: 'sip-1', ip_address: '10.0.10.1', prefix_length: 24, purpose: null, is_management: false }],
    open_ports: [],
  }

  const vlanDef = (id: string, vlan_id: number, name: string) => ({ id, vlan_id, name, description: '', domain_id: null, domain_name: '', devices: [] })

  async function mountWithSubinterfaces(props: { device: never | null; copyFrom?: never | null }, deviceVlanIds: string[] = ['v-10']) {
    const calls: Call[] = []
    stubCatalogsFetch()
    await useCatalogsStore().ensureLoaded()
    // Подинтерфейс живёт на VLAN устройства: VLAN должен быть и в справочнике, и в «VLAN устройства» донора.
    const vlans = useVLANsStore()
    vlans.groups = [
      { vlan_id: 10, definitions: [vlanDef('v-10', 10, 'Серверы')] },
      { vlan_id: 20, definitions: [vlanDef('v-20', 20, 'Гости')] },
    ]
    vlans.loaded = true
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (url.endsWith('/devices/dev-s/subinterfaces')) return new Response(JSON.stringify({ items: [subDto] }))
        // VLAN подинтерфейса — один из VLAN порта: на порту выбраны все VLAN устройства.
        if (url.endsWith('/devices/dev-s/interface-vlans'))
          return new Response(JSON.stringify({ items: [{ interface_id: 'if-1', all_vlans: false, vlan_ids: deviceVlanIds }] }))
        if (url.includes('/resources/device-vlans') && method === 'GET') {
          const items = deviceVlanIds.map((vlan_id, i) => ({
            id: `dv-${i + 1}`,
            physical_device_id: 'dev-s',
            vlan_id,
            ip_address: null,
            prefix_length: null,
            is_management: false,
            description: null,
          }))
          return new Response(JSON.stringify({ items, total: items.length, offset: 0, limit: 1000 }))
        }
        if (url.includes('/resources/interfaces') && method === 'GET')
          return new Response(JSON.stringify({ items: [ifaceDto], total: 1, offset: 0, limit: 1000 }))
        if (method === 'PUT' && url.includes('/devices/dev-copy/interfaces')) return new Response(JSON.stringify({ items: [], groups: [] }))
        if (method === 'PUT' && url.includes('/devices/dev-s/interfaces')) return new Response(JSON.stringify({ items: [], groups: [] }))
        if (method === 'POST' && url.includes('/resources/devices'))
          return new Response(JSON.stringify({ id: 'dev-copy', serial_number: 'SN-COPY' }), { status: 201 })
        if (method === 'PUT' && url.includes('/resources/devices/dev-s')) return new Response(JSON.stringify({ id: 'dev-s', serial_number: 'SN-S' }))
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )
    const wrapper = mount(DeviceFormModal, { props })
    await flushPromises()
    return { wrapper, calls }
  }

  it('редактирование: загруженные подинтерфейсы показываются у порта и при сохранении уходят с id', async () => {
    const { wrapper, calls } = await mountWithSubinterfaces({ device: donor })

    expect(wrapper.find('.expand-toggle').text()).toContain('1 подинт.')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-s/interfaces'))
    expect(put?.body.interfaces[0].subinterfaces).toEqual([
      {
        id: 'sub-1',
        name: 'Gi0/0.10',
        vlan_id: 'v-10',
        is_management: false,
        is_data_transfer: true,
        description: null,
        ips: [{ id: 'sip-1', ip_address: '10.0.10.1', prefix_length: 24, purpose: null }],
        open_ports: [],
      },
    ])
  })

  it('копирование устройства: подинтерфейсы донора создаются заново — без id у самих строк и у их IP', async () => {
    const { wrapper, calls } = await mountWithSubinterfaces({ device: null, copyFrom: donor })

    await setSerial(wrapper, 'SN-COPY')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-copy/interfaces'))
    expect(put).toBeDefined()
    const [sub] = put!.body.interfaces[0].subinterfaces
    expect(sub).toMatchObject({ name: 'Gi0/0.10', vlan_id: 'v-10', is_data_transfer: true })
    expect(sub.id).toBeUndefined()
    expect(sub.ips[0].id).toBeUndefined()
    expect(sub.ips[0]).toMatchObject({ ip_address: '10.0.10.1', prefix_length: 24 })
  })

  describe('снятие VLAN устройства, на котором есть подинтерфейс', () => {
    async function mountAndRemoveVlan10() {
      const mounted = await mountWithSubinterfaces({ device: donor }, ['v-10', 'v-20'])
      useToast().toasts.splice(0)
      const vlanEditor = mounted.wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
      await vlanEditor.findAll('button[aria-label="Удалить VLAN"]')[0].trigger('click') // первая строка — «10 — Серверы»
      await flushPromises()
      return mounted
    }

    it('сразу предупреждает: называет VLAN и подинтерфейс; подинтерфейс не удаляется, на строке порта — значок', async () => {
      const { wrapper } = await mountAndRemoveVlan10()

      const toasts = useToast().toasts
      expect(toasts.map((t) => t.type)).toEqual(['warning'])
      expect(toasts[0].message).toContain('Сняты VLAN (10 — Серверы), но на них остались подинтерфейсы: «Gi0/0.10»')
      expect(wrapper.find('.expand-toggle').text()).toContain('1 подинт.')
      expect(wrapper.find('.expand-toggle .stale-sub-icon').exists()).toBe(true)
    })

    it('в уведомлении есть кнопка «Показать»: по ней раскрывается порт с проблемным подинтерфейсом, а перенос на другой VLAN снимает предупреждение', async () => {
      const { wrapper } = await mountAndRemoveVlan10()
      const [toast] = useToast().toasts
      expect(toast.action?.label).toBe('Показать')
      expect(wrapper.find('.iface-detail-row').exists()).toBe(false) // порт свёрнут

      toast.action!.run()
      await flushPromises()

      expect(wrapper.find('.iface-detail-row').exists()).toBe(true)
      expect(wrapper.find('.sub-warn').text()).toContain('(10 — Серверы)') // прежний VLAN назван по справочнику, хотя устройству он уже недоступен

      await wrapper.find('select[aria-label="Перенести подинтерфейс на VLAN"]').setValue('v-20')

      expect(wrapper.find('.sub-warn').exists()).toBe(false)
      expect(wrapper.find('.stale-sub-icon').exists()).toBe(false)
      expect((wrapper.find('input[aria-label="Имя подинтерфейса"]').element as HTMLInputElement).value).toBe('Gi0/0.20') // автоимя пересчитано
    })

    it('сохранение блокируется понятным текстом до запроса на сервер', async () => {
      const { wrapper, calls } = await mountAndRemoveVlan10()

      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(wrapper.find('.form-error').text()).toContain('VLAN подинтерфейса «Gi0/0.10» не назначен устройству')
      expect(calls.some((c) => c.method !== 'GET')).toBe(false)
    })

    it('если на снятом VLAN подинтерфейсов нет — предупреждения нет', async () => {
      const { wrapper } = await mountWithSubinterfaces({ device: donor }, ['v-10', 'v-20'])
      useToast().toasts.splice(0)
      const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
      await vlanEditor.findAll('button[aria-label="Удалить VLAN"]')[1].trigger('click') // «20 — Гости»
      await flushPromises()

      expect(useToast().toasts).toHaveLength(0)
      expect(wrapper.find('.stale-sub-icon').exists()).toBe(false)
    })
  })

  it('переименование порта в форме пересчитывает автоимя подинтерфейса — в запрос уходит «Gi0/1.10»', async () => {
    const { wrapper, calls } = await mountWithSubinterfaces({ device: donor })

    await wrapper.find('.iface-table input.cell-input').setValue('Gi0/1')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/devices/dev-s/interfaces'))
    expect(put?.body.interfaces[0]).toMatchObject({ name: 'Gi0/1' })
    expect(put?.body.interfaces[0].subinterfaces[0]).toMatchObject({ id: 'sub-1', name: 'Gi0/1.10' })
  })
})

// Блок «VLAN устройства»: список упорядочен по номеру, повторов нет, длинный список сворачивается по порогу из «Настроек».
describe('DeviceFormModal.vue — «VLAN устройства»: сортировка, повторы, сворачивание', () => {
  const definition = (id: string, vlanId: number, name: string) => ({
    id,
    vlan_id: vlanId,
    name,
    description: '',
    domain_id: null,
    domain_name: '',
    devices: [],
  })
  interface DeviceVlanItem {
    id: string
    physical_device_id: string
    vlan_id: string
    ip_address: string | null
    prefix_length: number | null
    is_management: boolean
    description: string | null
  }
  const deviceVlanItem = (id: string, vlanId: string): DeviceVlanItem => ({
    id,
    physical_device_id: 'dev-v',
    vlan_id: vlanId,
    ip_address: null,
    prefix_length: null,
    is_management: false,
    description: null,
  })

  // Устройство с уже сохранёнными VLAN (в порядке items) и журналом запросов; PUT /devices/dev-v/vlans отвечает пустым списком.
  async function mountDeviceWithVlans(items: DeviceVlanItem[], count = 4) {
    const vlans = useVLANsStore()
    vlans.groups = Array.from({ length: count }, (_, i) => ({
      vlan_id: (i + 1) * 10,
      definitions: [definition(`v-${(i + 1) * 10}`, (i + 1) * 10, `Сеть ${(i + 1) * 10}`)],
    }))
    vlans.loaded = true
    stubCatalogsFetch()
    await useCatalogsStore().ensureLoaded()
    const calls: { method: string; url: string }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ method, url })
        if (method === 'GET' && url.includes('/resources/device-vlans'))
          return new Response(JSON.stringify({ items, total: items.length, offset: 0, limit: 1000 }))
        if (method === 'PUT' && url.endsWith('/devices/dev-v/vlans')) return new Response(JSON.stringify({ items: [] }))
        if (method === 'PUT' && url.includes('/resources/devices/dev-v'))
          return new Response(JSON.stringify({ id: 'dev-v', device_type_id: 'dt-server', serial_number: 'SN-V-1' }))
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )
    const device = { id: 'dev-v', device_type_id: 'dt-server', serial_number: 'SN-V-1' } as never
    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()
    const editor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
    return { wrapper, editor, calls }
  }

  it('при открытии формы VLAN устройства идут по возрастанию номера, даже если с сервера пришли в другом порядке', async () => {
    const { editor } = await mountDeviceWithVlans([deviceVlanItem('dv-3', 'v-30'), deviceVlanItem('dv-1', 'v-10'), deviceVlanItem('dv-2', 'v-20')])
    expect(vlanRowLabels(editor)).toEqual(['10 — Сеть 10', '20 — Сеть 20', '30 — Сеть 30'])
  })

  it('уже добавленные VLAN не предлагаются в новой строке', async () => {
    const { editor } = await mountDeviceWithVlans([deviceVlanItem('dv-1', 'v-10'), deviceVlanItem('dv-2', 'v-20')])
    await editor.find('.add-btn').trigger('click')
    expect(await vlanChoices(editor, 2)).toEqual(['30 — Сеть 30', '40 — Сеть 40'])
  })

  it('повтор VLAN блокирует сохранение: сообщение об ошибке, запрос VLAN устройства не отправляется', async () => {
    const { wrapper, calls } = await mountDeviceWithVlans([deviceVlanItem('dv-1', 'v-10'), deviceVlanItem('dv-2', 'v-10')])
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('VLAN 10 указан несколько раз')
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
    expect(wrapper.emitted('saved')).toBeFalsy()
  })

  it('порог из «Настроек» управляет сворачиванием: при 3 строках и пороге 2 блок свёрнут, при пороге по умолчанию — развёрнут', async () => {
    usePreferencesStore().user = { device_vlan_collapse_rows: 2 } // порог из «Настроек» (хранится на сервере)
    const collapsed = await mountDeviceWithVlans([deviceVlanItem('dv-1', 'v-10'), deviceVlanItem('dv-2', 'v-20'), deviceVlanItem('dv-3', 'v-30')])
    expect(collapsed.editor.find('[data-testid="vlan-collapsed"]').exists()).toBe(true)
    expect(collapsed.editor.findAll('.nested-row')).toHaveLength(0)

    setActivePinia(createPinia()) // новое приложение: настройки пользователя не заданы — порог по умолчанию (10)
    document.body.innerHTML = ''
    const expanded = await mountDeviceWithVlans([deviceVlanItem('dv-1', 'v-10'), deviceVlanItem('dv-2', 'v-20'), deviceVlanItem('dv-3', 'v-30')])
    expect(expanded.editor.find('[data-testid="vlan-collapsed"]').exists()).toBe(false)
    expect(expanded.editor.findAll('.nested-row')).toHaveLength(3)
  })

  it('ошибка сохранения в скрытой строке раскрывает свёрнутый блок, чтобы строка была видна', async () => {
    usePreferencesStore().user = { device_vlan_collapse_rows: 2 } // порог из «Настроек» (хранится на сервере)
    const bad = { ...deviceVlanItem('dv-2', 'v-20'), ip_address: '999.1.1.1' }
    const { wrapper, editor } = await mountDeviceWithVlans([deviceVlanItem('dv-1', 'v-10'), bad, deviceVlanItem('dv-3', 'v-30')])
    expect(editor.find('[data-testid="vlan-collapsed"]').exists()).toBe(true)

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('Некорректный IP-адрес «999.1.1.1»')
    expect(editor.find('[data-testid="vlan-collapsed"]').exists()).toBe(false)
    expect(editor.findAll('.nested-row')).toHaveLength(3)
  })
})

describe('DeviceFormModal.vue — общие настройки VLAN стека на самом устройстве', () => {
  const definition = (id: string, vlanId: number, name: string) => ({
    id,
    vlan_id: vlanId,
    name,
    description: '',
    domain_id: null,
    domain_name: '',
    devices: [],
  })
  const sharedRow = (overrides: Record<string, unknown> = {}) => ({
    vlan_id: 'v-10',
    vlan_number: 10,
    vlan_name: 'Сеть 10',
    domain_id: null,
    is_shared: true as const,
    ip_address: '10.0.10.1',
    prefix_length: 24,
    is_management: true,
    is_uniform: true,
    assigned_count: 2,
    member_count: 2,
    members: [
      {
        physical_device_id: 'dev-s',
        device_name: 'sw-1',
        assigned: true,
        ip_address: '10.0.10.1',
        prefix_length: 24,
        is_management: true,
        description: 'кластер',
      },
    ],
    ...overrides,
  })
  const stackState = (items: unknown[]) => ({ stack_name: 'Ядро', member_count: 2, items, available: [] })
  const ownVlans = [
    { id: 'dv-1', physical_device_id: 'dev-s', vlan_id: 'v-10', ip_address: '10.0.10.1', prefix_length: 24, is_management: true, description: 'кластер' },
    { id: 'dv-2', physical_device_id: 'dev-s', vlan_id: 'v-20', ip_address: '10.0.20.7', prefix_length: 24, is_management: false, description: null },
  ]

  interface Call {
    method: string
    url: string
    body?: unknown
  }

  // Устройство-участник стека «Ядро» (или обычное устройство, если inStack = false); состояние стека и PUT настройки отдаёт мок.
  async function mountDevice(inStack: boolean, opts: { applied?: unknown; afterDelete?: unknown } = {}) {
    const vlans = useVLANsStore()
    vlans.groups = [10, 20].map((n) => ({ vlan_id: n, definitions: [definition(`v-${n}`, n, `Сеть ${n}`)] }))
    vlans.loaded = true
    stubCatalogsFetch()
    await useCatalogsStore().ensureLoaded()
    const calls: Call[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ method, url, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'GET' && url.includes('/resources/device-vlans'))
          return new Response(JSON.stringify({ items: ownVlans, total: 2, offset: 0, limit: 1000 }))
        if (method === 'GET' && url.includes('/device-stacks/stack-1/vlans')) return new Response(JSON.stringify(stackState([sharedRow()])))
        if (method === 'PUT' && url.includes('/device-stacks/stack-1/vlans/v-10'))
          return new Response(JSON.stringify(opts.applied ?? stackState([sharedRow()])))
        if (method === 'DELETE' && url.includes('/device-stacks/stack-1/vlans/v-10')) return new Response(JSON.stringify(opts.afterDelete ?? stackState([])))
        if (method === 'PUT' && url.endsWith('/devices/dev-s/vlans')) return new Response(JSON.stringify({ items: [] }))
        if (method === 'PUT' && url.includes('/resources/devices/dev-s'))
          return new Response(JSON.stringify({ id: 'dev-s', device_type_id: 'dt-server', serial_number: 'SN-S-1' }))
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )
    const device = {
      id: 'dev-s',
      device_type_id: 'dt-server',
      serial_number: 'SN-S-1',
      ...(inStack ? { stack_id: 'stack-1', stack_name: 'Ядро' } : {}),
    } as never
    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()
    const vlanEditor = wrapper.findAll('.nested-editor').find((e) => e.text().includes('VLAN устройства'))!
    return { wrapper, vlanEditor, calls }
  }

  it('у устройства вне стека блока общих настроек нет и настройки стека не запрашиваются', async () => {
    const { wrapper, calls } = await mountDevice(false)
    expect(wrapper.find('[data-testid="stack-vlan-ip-editor"]').exists()).toBe(false)
    expect(calls.some((c) => c.url.includes('/device-stacks/'))).toBe(false)
  })

  it('у участника стека блок показан, а общий VLAN в «VLAN устройства» заблокирован (остальные строки — нет)', async () => {
    const { wrapper, vlanEditor } = await mountDevice(true)
    expect(wrapper.find('[data-testid="stack-vlan-ip-editor"]').text()).toContain('«Ядро»')

    const [shared, own] = vlanEditor.findAll('.nested-row')
    expect(shared.attributes('data-locked')).toBe('true')
    expect((shared.find('input.col-ip').element as HTMLInputElement).disabled).toBe(true)
    expect((shared.find('input[type="checkbox"]').element as HTMLInputElement).disabled).toBe(true)
    expect(own.attributes('data-locked')).toBeUndefined()
    expect((own.find('input.col-ip').element as HTMLInputElement).disabled).toBe(false)
  })

  it('после «Применить ко всем» новые значения попадают в черновик устройства, и сохранение отправляет именно их', async () => {
    const applied = stackState([sharedRow({ ip_address: '10.0.10.5' })])
    const { wrapper, vlanEditor, calls } = await mountDevice(true, { applied })

    const block = wrapper.find('[data-testid="stack-vlan-ip-editor"]')
    await block.find('[data-testid="stack-vlan-ip"]').setValue('10.0.10.5')
    await block.find('[data-testid="stack-vlan-apply"]').trigger('click')
    await flushPromises()

    const shared = vlanEditor.findAll('.nested-row')[0]
    expect((shared.find('input.col-ip').element as HTMLInputElement).value).toBe('10.0.10.5')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const save = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/devices/dev-s/vlans'))!
    const rows = (save.body as { vlans: { vlan_id: string; ip_address: string | null }[] }).vlans
    expect(rows.find((r) => r.vlan_id === 'v-10')?.ip_address).toBe('10.0.10.5')
  })

  it('«Снять настройку» (значения остаются) разблокирует строку; «убрать и у устройств» удаляет её из черновика', async () => {
    const kept = await mountDevice(true)
    await kept.wrapper.find('[data-testid="stack-vlan-remove"]').trigger('click')
    ;(document.body.querySelector('[data-testid="stack-vlan-remove-confirm"]') as HTMLElement).click()
    await flushPromises()
    const [unlocked] = kept.vlanEditor.findAll('.nested-row')
    expect(unlocked.attributes('data-locked')).toBeUndefined()
    expect((unlocked.find('input.col-ip').element as HTMLInputElement).value).toBe('10.0.10.1') // значения на устройстве сохранены
    expect((unlocked.find('input.col-ip').element as HTMLInputElement).disabled).toBe(false)

    setActivePinia(createPinia())
    document.body.innerHTML = ''
    const removed = await mountDevice(true)
    await removed.wrapper.find('[data-testid="stack-vlan-remove"]').trigger('click')
    ;(document.body.querySelector('[data-testid="stack-vlan-remove-from-devices"]') as HTMLElement).click()
    ;(document.body.querySelector('[data-testid="stack-vlan-remove-confirm"]') as HTMLElement).click()
    await flushPromises()
    expect(removed.vlanEditor.findAll('.nested-row')).toHaveLength(1) // осталась только собственная строка VLAN 20
    expect(removed.vlanEditor.text()).not.toContain('10 — Сеть 10')
  })
})
