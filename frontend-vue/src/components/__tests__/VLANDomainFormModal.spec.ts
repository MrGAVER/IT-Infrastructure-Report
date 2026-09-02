import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import VLANDomainFormModal from '../VLANDomainFormModal.vue'
import { useDevicesStore } from '../../stores/devices'
import type { VLANDomain } from '../../api/types'

const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 1000 }

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function seedDevices() {
  const devices = useDevicesStore()
  devices.all = [
    { id: 'dev-1', system_name: 'core-sw-01', serial_number: 'SN-1' } as never,
    { id: 'dev-2', system_name: 'core-sw-02', serial_number: 'SN-2' } as never,
  ]
  devices.loaded = true
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(EMPTY_PAGE)))
})

describe('VLANDomainFormModal.vue', () => {
  it('при создании нового домена скрывает управление составом', async () => {
    seedDevices()
    const wrapper = mount(VLANDomainFormModal, { props: { domain: null } })
    await flushPromises()

    expect(wrapper.text()).toContain('Состав домена можно настроить после первого сохранения')
    expect(wrapper.find('.nested-editor').exists()).toBe(false)
  })

  it('не сохраняет домен без наименования', async () => {
    seedDevices()
    const wrapper = mount(VLANDomainFormModal, { props: { domain: null } })
    await wrapper.find('form').trigger('submit')

    expect(wrapper.text()).toContain('Укажите наименование домена')
  })

  it('создаёт домен с указанным устройством-источником', async () => {
    seedDevices()
    const wrapper = mount(VLANDomainFormModal, { props: { domain: null } })

    await wrapper.find('input[type="text"]').setValue('Ядро сети')
    await wrapper.find('select').setValue('dev-1')
    await wrapper.find('input[type="checkbox"]').setValue(true)

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/vlan-domains')) return jsonResponse({ id: 'dom-new' }, 201)
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const create = calls.find((c) => c.method === 'POST' && c.url.endsWith('/resources/vlan-domains'))
    expect(create?.body).toMatchObject({ name: 'Ядро сети', source_device_id: 'dev-1', auto_sync: true })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('при редактировании загружает и отображает состав домена', async () => {
    seedDevices()
    const domain: VLANDomain = { id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: 'dev-1', auto_sync: false }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/resources/vlan-domain-devices')) {
          return jsonResponse({ ...EMPTY_PAGE, items: [{ id: 'link-1', domain_id: 'dom-1', physical_device_id: 'dev-2' }] })
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()

    expect(wrapper.find('.member-row').text()).toContain('core-sw-02')
  })

  it('добавляет устройство в состав домена через POST .../members', async () => {
    seedDevices()
    const domain: VLANDomain = { id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: null, auto_sync: false }
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.includes('/vlan-domains/dom-1/members')) {
          return jsonResponse({ id: 'link-new', domain_id: 'dom-1', physical_device_id: 'dev-1' }, 201)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()
    await wrapper.find('.add-member-row select').setValue('dev-1')
    await wrapper.find('.add-member-row button').trigger('click')
    await flushPromises()

    const call = calls.find((c) => c.method === 'POST' && c.url.includes('/members'))
    expect(call?.body).toEqual({ physical_device_id: 'dev-1' })
    expect(wrapper.find('.member-row').text()).toContain('core-sw-01')
  })

  it('убирает устройство из состава домена', async () => {
    seedDevices()
    const domain: VLANDomain = { id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: null, auto_sync: false }
    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        if (url.includes('/resources/vlan-domain-devices') && method === 'GET') {
          return jsonResponse({ ...EMPTY_PAGE, items: [{ id: 'link-1', domain_id: 'dom-1', physical_device_id: 'dev-2' }] })
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()
    await wrapper.find('.member-row .icon-btn.danger').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/resources/vlan-domain-devices/link-1'))).toBe(true)
    expect(wrapper.find('.member-row').exists()).toBe(false)
  })
})
