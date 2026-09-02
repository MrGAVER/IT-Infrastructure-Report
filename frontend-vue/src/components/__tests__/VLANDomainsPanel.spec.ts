import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import VLANDomainsPanel from '../VLANDomainsPanel.vue'
import { useVLANDomainsStore } from '../../stores/vlanDomains'
import { useDevicesStore } from '../../stores/devices'

const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 1000 }

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
})

function seedStores() {
  const domains = useVLANDomainsStore()
  domains.all = [
    { id: 'dom-1', name: 'Ядро сети', description: 'Основные коммутаторы', source_device_id: 'dev-1', auto_sync: true },
    { id: 'dom-2', name: 'Без синхронизации', description: null, source_device_id: null, auto_sync: false },
  ]
  domains.loaded = true

  const devices = useDevicesStore()
  devices.all = [{ id: 'dev-1', system_name: 'core-sw-01', serial_number: 'SN-1' } as never]
  devices.loaded = true
}

describe('VLANDomainsPanel.vue', () => {
  it('показывает подсказку, если доменов нет', async () => {
    const domains = useVLANDomainsStore()
    domains.loaded = true
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(EMPTY_PAGE)))

    const wrapper = mount(VLANDomainsPanel)
    await flushPromises()

    expect(wrapper.text()).toContain('VLAN-домены не созданы')
  })

  it('показывает устройство-источник, количество участников и метку автосинхронизации', async () => {
    seedStores()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ ...EMPTY_PAGE, items: [{ id: 'l1', domain_id: 'dom-1', physical_device_id: 'dev-1' }] })),
    )

    const wrapper = mount(VLANDomainsPanel)
    await flushPromises()

    const rows = wrapper.findAll('.domain-row')
    expect(rows[0].text()).toContain('core-sw-01')
    expect(rows[0].text()).toContain('Устройств: 1')
    expect(rows[0].text()).toContain('автосинхронизация')
  })

  it('кнопка "Синхронизировать" показывается только при заданном устройстве-источнике', async () => {
    seedStores()
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(EMPTY_PAGE)))

    const wrapper = mount(VLANDomainsPanel)
    await flushPromises()

    const rows = wrapper.findAll('.domain-row')
    const buttonTexts = (i: number) => rows[i].findAll('button').map((b) => b.text())
    expect(buttonTexts(0)).toContain('Синхронизировать') // dom-1: source_device_id задан
    expect(buttonTexts(1)).not.toContain('Синхронизировать') // dom-2: не задан
  })

  it('запускает синхронизацию домена по клику', async () => {
    seedStores()
    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        if (method === 'POST' && url.includes('/vlan-domains/dom-1/sync')) {
          return jsonResponse({ status: 'ok', created_definitions: 1, assigned: 3 })
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VLANDomainsPanel)
    await flushPromises()
    await wrapper.findAll('.domain-row')[0].findAll('button').find((b) => b.text() === 'Синхронизировать')!.trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.method === 'POST' && c.url.includes('/vlan-domains/dom-1/sync'))).toBe(true)
  })

  it('удаляет домен после подтверждения', async () => {
    seedStores()
    vi.stubGlobal('confirm', vi.fn(() => true))
    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VLANDomainsPanel)
    await flushPromises()
    await wrapper.findAll('.domain-row')[0].find('.icon-btn.danger').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/resources/vlan-domains/dom-1'))).toBe(true)
  })
})
