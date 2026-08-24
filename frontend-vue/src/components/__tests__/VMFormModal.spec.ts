import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import VMFormModal from '../VMFormModal.vue'
import type { VirtualMachine } from '../../api/types'

const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 1000 }

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('VMFormModal.vue', () => {
  it('при редактировании подгружает существующие IP-адреса и открытые порты ВМ', async () => {
    const vm: VirtualMachine = {
      id: 'vm-1',
      name: 'app-server-01',
      operating_system_id: null,
      physical_device_id: null,
      hypervisor_os_id: null,
      purpose: null,
      status: 'active',
      description: null,
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/resources/vm-ips')) {
          return jsonResponse({
            ...EMPTY_PAGE,
            items: [{ id: 'ip-1', virtual_machine_id: 'vm-1', ip_address: '10.20.30.5', prefix_length: 24, purpose: 'LAN', is_management: true }],
          })
        }
        if (url.includes('/resources/open-ports')) {
          return jsonResponse({
            ...EMPTY_PAGE,
            items: [{ id: 'op-1', owner_type: 'virtual_machine', owner_id: 'vm-1', transport_protocol: 'TCP', port: 443, protocol: 'HTTPS', protocol_catalog_id: null, ip_address: null, description: null }],
          })
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VMFormModal, { props: { vm } })
    await flushPromises()

    expect(wrapper.find('input[placeholder="IP-адрес"]').element).toHaveProperty('value', '10.20.30.5')
    expect(wrapper.find('input.col-port').element).toHaveProperty('value', '443')
  })

  it('создаёт новую ВМ и сохраняет добавленные IP-адрес и открытый порт под её id', async () => {
    const wrapper = mount(VMFormModal, { props: { vm: null } })

    await wrapper.find('button.add-btn').trigger('click') // + IP-адрес
    await wrapper.find('input[placeholder="IP-адрес"]').setValue('192.168.1.10')
    const addButtons = wrapper.findAll('button.add-btn')
    await addButtons[1].trigger('click') // + Открытый порт
    await wrapper.find('input.col-port').setValue('22')

    const calls: Array<{ url: string; method: string; body: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/vms')) {
          return jsonResponse({ id: 'vm-new', name: 'new-vm', operating_system_id: null, physical_device_id: null, hypervisor_os_id: null, purpose: null, status: 'active', description: null }, 201)
        }
        if (method === 'GET' && (url.includes('/resources/vm-ips') || url.includes('/resources/open-ports'))) {
          return jsonResponse(EMPTY_PAGE)
        }
        if (method === 'POST' && url.includes('/resources/vm-ips')) {
          return jsonResponse({ id: 'ip-new' }, 201)
        }
        if (method === 'POST' && url.includes('/resources/open-ports')) {
          return jsonResponse({ id: 'port-new' }, 201)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('input[required]').setValue('new-vm') // Название
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const vmIpCreate = calls.find((c) => c.method === 'POST' && c.url.includes('/resources/vm-ips'))
    expect(vmIpCreate?.body).toMatchObject({ virtual_machine_id: 'vm-new', ip_address: '192.168.1.10' })

    const openPortCreate = calls.find((c) => c.method === 'POST' && c.url.includes('/resources/open-ports'))
    expect(openPortCreate?.body).toMatchObject({ owner_type: 'virtual_machine', owner_id: 'vm-new', port: 22 })

    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('не отправляет пустые строки IP-адресов и открытых портов на сервер', async () => {
    const wrapper = mount(VMFormModal, { props: { vm: null } })

    await wrapper.find('button.add-btn').trigger('click') // + IP-адрес, оставляем пустым
    const addButtons = wrapper.findAll('button.add-btn')
    await addButtons[1].trigger('click') // + Открытый порт, оставляем пустым

    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        if (method === 'POST' && url.endsWith('/resources/vms')) {
          return jsonResponse({ id: 'vm-new', name: 'new-vm', operating_system_id: null, physical_device_id: null, hypervisor_os_id: null, purpose: null, status: 'active', description: null }, 201)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('input[required]').setValue('new-vm')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(calls.some((c) => c.method === 'POST' && c.url.includes('/resources/vm-ips'))).toBe(false)
    expect(calls.some((c) => c.method === 'POST' && c.url.includes('/resources/open-ports'))).toBe(false)
  })

  it('перед повторной вставкой удаляет ранее сохранённые IP-адреса ВМ', async () => {
    const vm: VirtualMachine = {
      id: 'vm-1',
      name: 'app-server-01',
      operating_system_id: null,
      physical_device_id: null,
      hypervisor_os_id: null,
      purpose: null,
      status: 'active',
      description: null,
    }
    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        if (method === 'GET' && url.includes('/resources/vm-ips')) {
          return jsonResponse({ ...EMPTY_PAGE, items: [{ id: 'ip-old', virtual_machine_id: 'vm-1', ip_address: '10.0.0.1', prefix_length: null, purpose: null, is_management: false }] })
        }
        if (method === 'PUT' && url.includes('/resources/vms/vm-1')) {
          return jsonResponse({ ...vm })
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VMFormModal, { props: { vm } })
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/resources/vm-ips/ip-old'))).toBe(true)
  })
})
