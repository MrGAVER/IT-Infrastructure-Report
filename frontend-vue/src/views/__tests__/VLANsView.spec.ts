import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import VLANsView from '../VLANsView.vue'
import { useVLANsStore } from '../../stores/vlans'
import { useDevicesStore } from '../../stores/devices'
import { useCatalogsStore } from '../../stores/catalogs'

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
