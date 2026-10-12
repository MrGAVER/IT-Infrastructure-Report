import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceStackVlanIpEditor from '../DeviceStackVlanIpEditor.vue'
import type { DeviceStackVlans, StackVlanRow } from '../../api/types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function vlanRow(overrides: Partial<StackVlanRow> = {}): StackVlanRow {
  return {
    vlan_id: 'v-10',
    vlan_number: 10,
    vlan_name: 'mgmt',
    domain_id: null,
    ip_address: '10.0.10.1',
    prefix_length: 24,
    is_uniform: true,
    assigned_count: 2,
    member_count: 2,
    members: [
      { physical_device_id: 'dev-1', device_name: 'fw-1', assigned: true, ip_address: '10.0.10.1', prefix_length: 24 },
      { physical_device_id: 'dev-2', device_name: 'fw-2', assigned: true, ip_address: '10.0.10.1', prefix_length: 24 },
    ],
    ...overrides,
  }
}

const DIVERGED = vlanRow({
  ip_address: null,
  prefix_length: null,
  is_uniform: false,
  members: [
    { physical_device_id: 'dev-1', device_name: 'fw-1', assigned: true, ip_address: '10.0.10.1', prefix_length: 24 },
    { physical_device_id: 'dev-2', device_name: 'fw-2', assigned: true, ip_address: '10.0.10.2', prefix_length: 24 },
  ],
})

interface Call {
  url: string
  method: string
  body?: unknown
}

/** fetch-мок: GET отдаёт state, PUT обрабатывает handler (по умолчанию — 200 с тем же state). */
function mockApi(state: DeviceStackVlans, handler?: (call: Call) => Response | undefined) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const call: Call = { url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body as string) : undefined }
      calls.push(call)
      return handler?.(call) ?? jsonResponse(state)
    }),
  )
  return calls
}

function mountEditor(props: Partial<{ memberCount: number; reloadToken: number }> = {}) {
  return mount(DeviceStackVlanIpEditor, { props: { stackId: 'stack-1', memberCount: 2, reloadToken: 0, ...props } })
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('DeviceStackVlanIpEditor.vue', () => {
  it('показывает VLAN стека с общим адресом и статусом «одинаково у всех»', async () => {
    mockApi({ items: [vlanRow()], available: [] })
    const wrapper = mountEditor()
    await flushPromises()

    const row = wrapper.get('[data-testid="stack-vlan-row"]')
    expect(row.text()).toContain('10 — mgmt')
    expect((row.get('[data-testid="stack-vlan-ip"]').element as HTMLInputElement).value).toBe('10.0.10.1')
    expect((row.get('[data-testid="stack-vlan-prefix"]').element as HTMLInputElement).value).toBe('24')
    expect(row.get('[data-testid="stack-vlan-status"]').text()).toBe('Одинаково у всех (2)')
    // Применять нечего: введённое совпадает с общим значением.
    expect(row.get('[data-testid="stack-vlan-apply"]').attributes('disabled')).toBeDefined()
  })

  it('при расхождении показывает, у каких устройств какие адреса', async () => {
    mockApi({ items: [DIVERGED], available: [] })
    const wrapper = mountEditor()
    await flushPromises()

    expect(wrapper.get('[data-testid="stack-vlan-status"]').text()).toBe('Адреса различаются у устройств')
    const details = wrapper.get('.by-device').text()
    expect(details).toContain('fw-1: 10.0.10.1/24')
    expect(details).toContain('fw-2: 10.0.10.2/24')
    expect(wrapper.get('[data-testid="stack-vlan-apply"]').attributes('disabled')).toBeUndefined()
  })

  it('«Применить ко всем» отправляет один PUT с адресом и префиксом, обновляет статус и сообщает родителю', async () => {
    const calls = mockApi({ items: [DIVERGED], available: [] }, (call) =>
      call.method === 'PUT' ? jsonResponse({ items: [vlanRow({ ip_address: '10.0.10.5' })], available: [] }) : undefined,
    )
    const wrapper = mountEditor()
    await flushPromises()

    await wrapper.get('[data-testid="stack-vlan-ip"]').setValue('10.0.10.5')
    await wrapper.get('[data-testid="stack-vlan-prefix"]').setValue('24')
    await wrapper.get('[data-testid="stack-vlan-apply"]').trigger('click')
    await flushPromises()

    const puts = calls.filter((c) => c.method === 'PUT')
    expect(puts).toHaveLength(1)
    expect(puts[0].url).toContain('/device-stacks/stack-1/vlans/v-10')
    expect(puts[0].body).toEqual({ ip_address: '10.0.10.5', prefix_length: 24 })
    expect(wrapper.get('[data-testid="stack-vlan-status"]').text()).toBe('Одинаково у всех (2)')
    expect(wrapper.emitted('applied')).toHaveLength(1)
  })

  it('не отправляет запрос при IP без префикса и показывает причину', async () => {
    const calls = mockApi({ items: [DIVERGED], available: [] })
    const wrapper = mountEditor()
    await flushPromises()

    await wrapper.get('[data-testid="stack-vlan-ip"]').setValue('10.0.10.5')
    await wrapper.get('[data-testid="stack-vlan-prefix"]').setValue('')

    expect(wrapper.get('[data-testid="stack-vlan-error"]').text()).toContain('префикс')
    expect(wrapper.get('[data-testid="stack-vlan-apply"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid="stack-vlan-apply"]').trigger('click')
    expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(0)
  })

  it('добавляет VLAN из доступных, отправляет его всем устройствам и убирает из списка доступных', async () => {
    const calls = mockApi({ items: [], available: [{ vlan_id: 'v-20', vlan_number: 20, vlan_name: 'users' }] }, (call) =>
      call.method === 'PUT'
        ? jsonResponse({ items: [vlanRow({ vlan_id: 'v-20', vlan_number: 20, vlan_name: 'users', ip_address: '10.0.20.1' })], available: [] })
        : undefined,
    )
    const wrapper = mountEditor()
    await flushPromises()
    expect(wrapper.text()).toContain('VLAN устройствам стека не назначены')

    wrapper.getComponent({ name: 'SearchableSelect' }).vm.$emit('update:modelValue', 'v-20')
    await flushPromises()
    await wrapper.get('[data-testid="stack-vlan-add"]').trigger('click')

    expect(wrapper.get('[data-testid="stack-vlan-status"]').text()).toBe('Не назначен устройствам стека')
    await wrapper.get('[data-testid="stack-vlan-ip"]').setValue('10.0.20.1')
    await wrapper.get('[data-testid="stack-vlan-prefix"]').setValue('24')
    await wrapper.get('[data-testid="stack-vlan-apply"]').trigger('click')
    await flushPromises()

    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ ip_address: '10.0.20.1', prefix_length: 24 })
    expect(wrapper.findAll('[data-testid="stack-vlan-row"]')).toHaveLength(1)
    expect(wrapper.get('[data-testid="stack-vlan-status"]').text()).toBe('Одинаково у всех (2)')
  })

  it('неприменённую добавленную строку можно убрать, ничего не отправляя', async () => {
    const calls = mockApi({ items: [], available: [{ vlan_id: 'v-20', vlan_number: 20, vlan_name: 'users' }] })
    const wrapper = mountEditor()
    await flushPromises()

    wrapper.getComponent({ name: 'SearchableSelect' }).vm.$emit('update:modelValue', 'v-20')
    await flushPromises()
    await wrapper.get('[data-testid="stack-vlan-add"]').trigger('click')
    await wrapper.get('[data-testid="stack-vlan-remove-draft"]').trigger('click')

    expect(wrapper.findAll('[data-testid="stack-vlan-row"]')).toHaveLength(0)
    expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(0)
  })

  it('показывает ошибку сервера в строке (например, устройство вне домена VLAN) и не теряет введённое', async () => {
    mockApi({ items: [DIVERGED], available: [] }, (call) =>
      call.method === 'PUT' ? jsonResponse({ detail: 'VLAN 10 «mgmt» принадлежит домену, в который не входят устройства стека: fw-2' }, 422) : undefined,
    )
    const wrapper = mountEditor()
    await flushPromises()

    await wrapper.get('[data-testid="stack-vlan-ip"]').setValue('10.0.10.5')
    await wrapper.get('[data-testid="stack-vlan-prefix"]').setValue('24')
    await wrapper.get('[data-testid="stack-vlan-apply"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="stack-vlan-error"]').text()).toContain('fw-2')
    expect((wrapper.get('[data-testid="stack-vlan-ip"]').element as HTMLInputElement).value).toBe('10.0.10.5')
    expect(wrapper.emitted('applied')).toBeUndefined()
  })

  it('без устройств в стеке подсказывает добавить участников и не запрашивает VLAN', async () => {
    const calls = mockApi({ items: [], available: [] })
    const wrapper = mountEditor({ memberCount: 0 })
    await flushPromises()

    expect(wrapper.text()).toContain('Добавьте устройства в стек')
    expect(wrapper.find('[data-testid="stack-vlan-add"]').exists()).toBe(false)
    // Запрос на загрузку допустим (дёшев), но блок ничего не рисует без участников.
    expect(calls.filter((c) => c.method !== 'GET')).toHaveLength(0)
  })

  it('перечитывает VLAN при смене reloadToken (изменился состав стека)', async () => {
    const calls = mockApi({ items: [vlanRow()], available: [] })
    const wrapper = mountEditor()
    await flushPromises()
    expect(calls).toHaveLength(1)

    await wrapper.setProps({ reloadToken: 1 })
    await flushPromises()

    expect(calls.filter((c) => c.url.includes('/device-stacks/stack-1/vlans') && c.method === 'GET')).toHaveLength(2)
  })
})
