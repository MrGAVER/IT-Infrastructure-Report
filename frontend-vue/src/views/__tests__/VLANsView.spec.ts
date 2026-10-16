import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import VLANsView from '../VLANsView.vue'
import { useVLANsStore } from '../../stores/vlans'
import { useDevicesStore } from '../../stores/devices'
import { useCatalogsStore } from '../../stores/catalogs'
import DeviceFormModal from '../../components/DeviceFormModal.vue'
import { useToast } from '../../composables/useToast'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
})

function seedStores() {
  const vlans = useVLANsStore()
  vlans.groups = [{ vlan_id: 10, definitions: [{ id: 'v-10', vlan_id: 10, name: 'Мониторинг', description: '', domain_id: null, domain_name: '', devices: [] }] }]
  vlans.loaded = true

  const devices = useDevicesStore()
  devices.all = [
    { id: 'dev-1', device_type_id: 'dt-server', system_name: 'srv-01', serial_number: 'SN-1' } as never,
    { id: 'dev-2', device_type_id: 'dt-server', system_name: 'srv-02', serial_number: 'SN-2' } as never,
  ]
  devices.loaded = true

  const catalogs = useCatalogsStore()
  catalogs.loaded = true
}

describe('VLANsView.vue — массовое назначение VLAN', () => {
  it('панель скрыта по умолчанию и открывается по клику', async () => {
    seedStores()
    const wrapper = mount(VLANsView)
    await flushPromises()

    expect(wrapper.find('.bulk-panel').exists()).toBe(false)
    await wrapper.findAll('button').find((b) => b.text().includes('Массовое назначение VLAN'))!.trigger('click')
    expect(wrapper.find('.bulk-panel').exists()).toBe(true)
  })

  it('"Выбрать все" отмечает все чекбоксы устройств', async () => {
    seedStores()
    const wrapper = mount(VLANsView)
    await flushPromises()
    await wrapper.findAll('button').find((b) => b.text().includes('Массовое назначение VLAN'))!.trigger('click')

    await wrapper.find('.bulk-device-all input').setValue(true)

    const deviceChecks = wrapper.findAll('.bulk-device input[type="checkbox"]')
    expect(deviceChecks.every((c) => (c.element as HTMLInputElement).checked)).toBe(true)
  })

  it('назначает выбранный VLAN отмеченным устройствам', async () => {
    seedStores()
    const wrapper = mount(VLANsView)
    await flushPromises()
    await wrapper.findAll('button').find((b) => b.text().includes('Массовое назначение VLAN'))!.trigger('click')

    await wrapper.find('.bulk-fields select').setValue('v-10')
    await wrapper.find('.bulk-device-all input').setValue(true)

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.includes('/device-vlans/bulk-assign')) {
          return jsonResponse({ status: 'ok', assigned: 2, skipped_existing: 0 })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    await wrapper.find('.bulk-panel button.btn-primary').trigger('click')
    await flushPromises()

    const call = calls.find((c) => c.method === 'POST' && c.url.includes('/device-vlans/bulk-assign'))
    expect(call?.body).toMatchObject({ physical_device_ids: ['dev-1', 'dev-2'], vlan_id: 'v-10', description: null })
    // Панель закрывается и сбрасывается после успешного назначения.
    expect(wrapper.find('.bulk-panel').exists()).toBe(false)
  })

  it('не отправляет запрос, если не выбрано ни одного устройства', async () => {
    seedStores()
    const wrapper = mount(VLANsView)
    await flushPromises()
    await wrapper.findAll('button').find((b) => b.text().includes('Массовое назначение VLAN'))!.trigger('click')
    await wrapper.find('.bulk-fields select').setValue('v-10')

    const fetchSpy = vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 }))
    vi.stubGlobal('fetch', fetchSpy)

    await wrapper.find('.bulk-panel button.btn-primary').trigger('click')
    await flushPromises()

    expect(fetchSpy).not.toHaveBeenCalled()
    expect(wrapper.find('.bulk-panel').exists()).toBe(true) // панель осталась открытой
  })
})

describe('VLANsView.vue — подинтерфейсы на недоступных VLAN', () => {
  const staleItem = { subinterface_id: 's-1', subinterface_name: 'Gi0/0.30', port_id: 'p-1', port_name: 'Gi0/0', device_id: 'dev-2', device_name: 'srv-02', vlan_id: 'v-30', vlan_number: 30, vlan_name: 'Резерв' }

  function stubIntegrity(items: unknown[]) {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/integrity/stale-subinterfaces')) return jsonResponse({ ok: items.length === 0, total: items.length, subinterfaces: items })
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
    })
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }
  const staleCalls = (fetchMock: ReturnType<typeof stubIntegrity>) => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/integrity/stale-subinterfaces')).length

  async function mountView() {
    seedStores()
    useToast().toasts.splice(0)
    const wrapper = mount(VLANsView, { global: { stubs: { DeviceFormModal: true } } })
    await flushPromises()
    return wrapper
  }

  it('без проблемных подинтерфейсов панели на экране нет', async () => {
    stubIntegrity([])
    const wrapper = await mountView()
    expect(wrapper.find('.stale-panel').exists()).toBe(false)
  })

  it('с проблемными подинтерфейсами панель показана; «Открыть устройство» открывает форму этого устройства', async () => {
    stubIntegrity([staleItem])
    const wrapper = await mountView()
    expect(wrapper.find('.stale-panel').text()).toContain('srv-02')
    expect(wrapper.findComponent(DeviceFormModal).exists()).toBe(false)

    await wrapper.find('.stale-device-head button').trigger('click')

    const modal = wrapper.findComponent(DeviceFormModal)
    expect(modal.exists()).toBe(true)
    expect((modal.props('device') as { id: string }).id).toBe('dev-2')
  })

  it('устройства нет в загруженном списке — понятная ошибка, форма не открывается', async () => {
    stubIntegrity([{ ...staleItem, device_id: 'dev-gone' }])
    const wrapper = await mountView()

    await wrapper.find('.stale-device-head button').trigger('click')

    expect(wrapper.findComponent(DeviceFormModal).exists()).toBe(false)
    expect(useToast().toasts.map((t) => t.message)).toEqual(['Устройство не найдено — обновите список устройств'])
  })

  it('после сохранения устройства форма закрывается, а панель перечитывается', async () => {
    const fetchMock = stubIntegrity([staleItem])
    const wrapper = await mountView()
    await wrapper.find('.stale-device-head button').trigger('click')
    expect(staleCalls(fetchMock)).toBe(1)

    stubIntegrity([]) // подинтерфейс перенесён
    wrapper.findComponent(DeviceFormModal).vm.$emit('saved', { id: 'dev-2' })
    await flushPromises()

    expect(wrapper.findComponent(DeviceFormModal).exists()).toBe(false)
    expect(wrapper.find('.stale-panel').exists()).toBe(false)
    expect(useToast().toasts.map((t) => t.message)).toContain('Устройство обновлено')
  })

  it('кнопка «Обновить» экрана перечитывает и панель', async () => {
    const fetchMock = stubIntegrity([staleItem])
    const wrapper = await mountView()
    expect(staleCalls(fetchMock)).toBe(1)

    await wrapper.findAll('button').find((b) => b.text().includes('Обновить'))!.trigger('click')
    await flushPromises()

    expect(staleCalls(fetchMock)).toBe(2)
  })
})


describe('VLANsView.vue — пагинация', () => {
  const group = (id: number) => ({
    vlan_id: id,
    definitions: [{ id: `v-${id}`, vlan_id: id, name: `vlan-${id}`, description: '', domain_id: null, domain_name: '', devices: [] }],
  })

  function stubApi() {
    const puts: unknown[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith('/integrity/stale-subinterfaces')) return jsonResponse({ ok: true, total: 0, subinterfaces: [] })
        if (url.endsWith('/preferences/user') && init?.method === 'PUT') {
          puts.push(JSON.parse(init.body as string))
          return jsonResponse({ global: {}, user: {} })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )
    return puts
  }

  async function mountWith(count: number) {
    seedStores()
    useVLANsStore().groups = Array.from({ length: count }, (_, i) => group(i + 1))
    const wrapper = mount(VLANsView, { global: { stubs: { DeviceFormModal: true } } })
    await flushPromises()
    return wrapper
  }

  const cards = (wrapper: Awaited<ReturnType<typeof mountWith>>) => wrapper.findAll('.group.card')
  const range = (wrapper: Awaited<ReturnType<typeof mountWith>>) => wrapper.find('.paged-foot .range').text()

  it('длинный список режется на страницы: 10 групп на первой, подвал с диапазоном и номерами страниц', async () => {
    stubApi()
    const wrapper = await mountWith(25)

    expect(cards(wrapper)).toHaveLength(10)
    expect(cards(wrapper)[0].text()).toContain('VLAN 1')
    expect(range(wrapper)).toBe('Показано 1–10 из 25')
    expect(wrapper.findAll('.pager button[aria-label^="Страница"]')).toHaveLength(3)
  })

  it('переход на последнюю страницу показывает остаток', async () => {
    stubApi()
    const wrapper = await mountWith(25)

    await wrapper.find('.pager button[aria-label="Страница 3"]').trigger('click')

    expect(cards(wrapper)).toHaveLength(5)
    expect(cards(wrapper)[0].text()).toContain('VLAN 21')
    expect(range(wrapper)).toBe('Показано 21–25 из 25')
  })

  it('смена размера страницы меняет число групп и запоминается', async () => {
    const puts = stubApi()
    const wrapper = await mountWith(25)

    await wrapper.find('.page-size select').setValue('20')
    await flushPromises()

    expect(cards(wrapper)).toHaveLength(20)
    expect(range(wrapper)).toBe('Показано 1–20 из 25')
    expect(puts).toEqual([{ page_sizes: { vlans: 20 } }])
  })

  it('поиск возвращает на первую страницу, а не оставляет на несуществующей', async () => {
    stubApi()
    const wrapper = await mountWith(25)
    await wrapper.find('.pager button[aria-label="Страница 3"]').trigger('click')

    useVLANsStore().search = '1' // VLAN 1, 10–19 и 21 — 12 групп, две страницы
    await flushPromises()

    expect(range(wrapper)).toBe('Показано 1–10 из 12')
    expect(cards(wrapper)[0].text()).toContain('VLAN 1')
  })

  it('короткий список — одна страница, пейджер без лишних кнопок', async () => {
    stubApi()
    const wrapper = await mountWith(3)

    expect(cards(wrapper)).toHaveLength(3)
    expect(range(wrapper)).toBe('Показано 1–3 из 3')
    expect(wrapper.findAll('.pager button[aria-label^="Страница"]')).toHaveLength(1)
  })

  it('когда ничего не найдено — сообщение вместо списка и без подвала пагинации', async () => {
    stubApi()
    const wrapper = await mountWith(25)

    useVLANsStore().search = 'такого-нет'
    await flushPromises()

    expect(wrapper.find('.empty-banner').exists()).toBe(true)
    expect(wrapper.find('.paged-foot').exists()).toBe(false)
  })
})
