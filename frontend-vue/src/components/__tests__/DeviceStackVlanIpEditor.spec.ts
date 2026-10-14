import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceStackVlanIpEditor from '../DeviceStackVlanIpEditor.vue'
import type { DeviceStackVlans, StackVlanOption, StackVlanRow } from '../../api/types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function sharedRow(overrides: Partial<StackVlanRow> = {}): StackVlanRow {
  return {
    vlan_id: 'v-10',
    vlan_number: 10,
    vlan_name: 'mgmt',
    domain_id: null,
    is_shared: true,
    ip_address: '10.0.10.1',
    prefix_length: 24,
    is_management: true,
    is_uniform: true,
    assigned_count: 2,
    member_count: 2,
    members: [
      { physical_device_id: 'dev-1', device_name: 'fw-1', assigned: true, ip_address: '10.0.10.1', prefix_length: 24, is_management: true, description: null },
      { physical_device_id: 'dev-2', device_name: 'fw-2', assigned: true, ip_address: '10.0.10.1', prefix_length: 24, is_management: true, description: null },
    ],
    ...overrides,
  }
}

const DIVERGED = sharedRow({
  is_uniform: false,
  members: [
    { physical_device_id: 'dev-1', device_name: 'fw-1', assigned: true, ip_address: '10.0.10.1', prefix_length: 24, is_management: true, description: null },
    { physical_device_id: 'dev-2', device_name: 'fw-2', assigned: true, ip_address: '10.0.10.2', prefix_length: 24, is_management: false, description: null },
  ],
})

function state(items: StackVlanRow[], available: StackVlanOption[] = [], memberCount = 2): DeviceStackVlans {
  return { stack_name: 'Кластер МЭ', member_count: memberCount, items, available }
}

const OPTION_20: StackVlanOption = { vlan_id: 'v-20', vlan_number: 20, vlan_name: 'users', ip_address: '10.0.20.1', prefix_length: 24, is_management: true, assigned_count: 1 }

interface Call {
  url: string
  method: string
  body?: unknown
}

/** fetch-мок: GET отдаёт initial, остальные методы обрабатывает handler (по умолчанию — 200 с тем же состоянием). */
function mockApi(initial: DeviceStackVlans, handler?: (call: Call) => Response | undefined) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const call: Call = { url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body as string) : undefined }
      calls.push(call)
      return handler?.(call) ?? jsonResponse(initial)
    }),
  )
  return calls
}

function mountEditor(reloadToken = 0) {
  return mount(DeviceStackVlanIpEditor, { props: { stackId: 'stack-1', reloadToken } })
}

const byId = (id: string) => document.body.querySelector(`[data-testid="${id}"]`) as HTMLElement | null

beforeEach(() => {
  setActivePinia(createPinia())
})
afterEach(() => {
  document.body.innerHTML = ''
})

describe('DeviceStackVlanIpEditor.vue', () => {
  it('показывает общие настройки с адресом, префиксом, флагом «Управление» и статусом «применено ко всем»', async () => {
    mockApi(state([sharedRow()]))
    const wrapper = mountEditor()
    await flushPromises()

    const row = wrapper.get('[data-testid="stack-vlan-row"]')
    expect(row.text()).toContain('10 — mgmt')
    expect((row.get('[data-testid="stack-vlan-ip"]').element as HTMLInputElement).value).toBe('10.0.10.1')
    expect((row.get('[data-testid="stack-vlan-prefix"]').element as HTMLInputElement).value).toBe('24')
    expect((row.get('[data-testid="stack-vlan-management"]').element as HTMLInputElement).checked).toBe(true)
    expect(row.get('[data-testid="stack-vlan-status"]').text()).toBe('Применено ко всем (2)')
    expect(wrapper.text()).toContain('Кластер МЭ')
    expect(row.get('[data-testid="stack-vlan-apply"]').attributes('disabled')).toBeDefined() // применять нечего
  })

  it('при расхождении показывает по устройствам адреса и «Управление»', async () => {
    mockApi(state([DIVERGED]))
    const wrapper = mountEditor()
    await flushPromises()

    expect(wrapper.get('[data-testid="stack-vlan-status"]').text()).toBe('У некоторых устройств значения отличаются от настройки')
    const details = wrapper.get('.by-device').text()
    expect(details).toContain('fw-1: 10.0.10.1/24, «Управление»')
    expect(details).toContain('fw-2: 10.0.10.2/24')
    expect(wrapper.get('[data-testid="stack-vlan-apply"]').attributes('disabled')).toBeUndefined() // «Применить ко всем» чинит расхождение
  })

  it('«Применить ко всем» шлёт один PUT с адресом, префиксом и флагом, обновляет статус и сообщает родителю', async () => {
    const applied = state([sharedRow({ ip_address: '10.0.10.5' })])
    const calls = mockApi(state([DIVERGED]), (call) => (call.method === 'PUT' ? jsonResponse(applied) : undefined))
    const wrapper = mountEditor()
    await flushPromises()

    await wrapper.get('[data-testid="stack-vlan-ip"]').setValue('10.0.10.5')
    await wrapper.get('[data-testid="stack-vlan-apply"]').trigger('click')
    await flushPromises()

    const puts = calls.filter((c) => c.method === 'PUT')
    expect(puts).toHaveLength(1)
    expect(puts[0].url).toContain('/device-stacks/stack-1/vlans/v-10')
    expect(puts[0].body).toEqual({ ip_address: '10.0.10.5', prefix_length: 24, is_management: true })
    expect(wrapper.get('[data-testid="stack-vlan-status"]').text()).toBe('Применено ко всем (2)')
    expect(wrapper.emitted('applied')?.[0]).toEqual([applied])
    expect(wrapper.emitted('update:state')?.at(-1)).toEqual([applied])
  })

  it('смена одной галочки «Управление» включает «Применить» и уходит в запросе', async () => {
    const calls = mockApi(state([sharedRow()]), (call) => (call.method === 'PUT' ? jsonResponse(state([sharedRow({ is_management: false })])) : undefined))
    const wrapper = mountEditor()
    await flushPromises()
    expect(wrapper.get('[data-testid="stack-vlan-apply"]').attributes('disabled')).toBeDefined()

    await wrapper.get('[data-testid="stack-vlan-management"]').setValue(false)
    expect(wrapper.get('[data-testid="stack-vlan-apply"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="stack-vlan-apply"]').trigger('click')
    await flushPromises()

    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ ip_address: '10.0.10.1', prefix_length: 24, is_management: false })
  })

  it('не отправляет запрос при IP без префикса и показывает причину', async () => {
    const calls = mockApi(state([DIVERGED]))
    const wrapper = mountEditor()
    await flushPromises()

    await wrapper.get('[data-testid="stack-vlan-prefix"]').setValue('')

    expect(wrapper.get('[data-testid="stack-vlan-error"]').text()).toContain('префикс')
    expect(wrapper.get('[data-testid="stack-vlan-apply"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid="stack-vlan-apply"]').trigger('click')
    expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(0)
  })

  it('новый VLAN добавляется с подсказкой от устройств (адрес, префикс, «Управление» у одного = у всех) и применяется всем', async () => {
    const applied = state([sharedRow({ vlan_id: 'v-20', vlan_number: 20, vlan_name: 'users', ip_address: '10.0.20.1' })], [])
    const calls = mockApi(state([], [OPTION_20]), (call) => (call.method === 'PUT' ? jsonResponse(applied) : undefined))
    const wrapper = mountEditor()
    await flushPromises()
    expect(wrapper.text()).toContain('Общие настройки VLAN не заданы')

    wrapper.getComponent({ name: 'SearchableSelect' }).vm.$emit('update:modelValue', 'v-20')
    await flushPromises()
    await wrapper.get('[data-testid="stack-vlan-add"]').trigger('click')

    expect((wrapper.get('[data-testid="stack-vlan-ip"]').element as HTMLInputElement).value).toBe('10.0.20.1')
    expect((wrapper.get('[data-testid="stack-vlan-prefix"]').element as HTMLInputElement).value).toBe('24')
    expect((wrapper.get('[data-testid="stack-vlan-management"]').element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.get('[data-testid="stack-vlan-status"]').text()).toBe('Ещё не применено к устройствам стека')
    await wrapper.get('[data-testid="stack-vlan-apply"]').trigger('click')
    await flushPromises()

    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ ip_address: '10.0.20.1', prefix_length: 24, is_management: true })
    expect(wrapper.get('[data-testid="stack-vlan-status"]').text()).toBe('Применено ко всем (2)')
  })

  it('неприменённую строку можно убрать без запросов и без диалога', async () => {
    const calls = mockApi(state([], [OPTION_20]))
    const wrapper = mountEditor()
    await flushPromises()
    wrapper.getComponent({ name: 'SearchableSelect' }).vm.$emit('update:modelValue', 'v-20')
    await flushPromises()
    await wrapper.get('[data-testid="stack-vlan-add"]').trigger('click')

    await wrapper.get('[data-testid="stack-vlan-remove"]').trigger('click')

    expect(wrapper.findAll('[data-testid="stack-vlan-row"]')).toHaveLength(0)
    expect(byId('stack-vlan-remove-dialog')).toBeNull()
    expect(calls.filter((c) => c.method !== 'GET')).toHaveLength(0)
  })

  it('показывает ошибку сервера в строке (например, устройство вне домена VLAN) и не теряет введённое', async () => {
    mockApi(state([DIVERGED]), (call) => (call.method === 'PUT' ? jsonResponse({ detail: 'VLAN 10 «mgmt» принадлежит домену, в который не входят устройства стека: fw-2' }, 422) : undefined))
    const wrapper = mountEditor()
    await flushPromises()

    await wrapper.get('[data-testid="stack-vlan-ip"]').setValue('10.0.10.5')
    await wrapper.get('[data-testid="stack-vlan-apply"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="stack-vlan-error"]').text()).toContain('fw-2')
    expect((wrapper.get('[data-testid="stack-vlan-ip"]').element as HTMLInputElement).value).toBe('10.0.10.5')
    expect(wrapper.emitted('applied')).toBeUndefined()
  })

  it('в списке выбора — только VLAN, добавленные на устройства стека; пока таких нет, подсказывает, где их добавить', async () => {
    mockApi(state([], [], 2))
    const wrapper = mountEditor()
    await flushPromises()

    await wrapper.get('.add-row .searchable-select input').trigger('focus')

    expect(wrapper.get('.add-row .ss-empty').text()).toBe('На устройства стека пока не добавлено ни одного VLAN — добавьте его в блоке «VLAN устройства»')
  })

  it('когда все VLAN устройств стека уже добавлены в блок, список выбора так и говорит', async () => {
    mockApi(state([], [OPTION_20]))
    const wrapper = mountEditor()
    await flushPromises()
    wrapper.getComponent({ name: 'SearchableSelect' }).vm.$emit('update:modelValue', 'v-20')
    await flushPromises()
    await wrapper.get('[data-testid="stack-vlan-add"]').trigger('click') // единственный VLAN устройств стека перенесён в строку настройки

    await wrapper.get('.add-row .searchable-select input').trigger('focus')

    expect(wrapper.get('.add-row .ss-empty').text()).toBe('Все VLAN устройств стека уже добавлены')
  })

  it('в стеке без устройств подсказывает добавить участников', async () => {
    mockApi(state([], [], 0))
    const wrapper = mountEditor()
    await flushPromises()
    expect(wrapper.get('[data-testid="stack-vlan-no-members"]').text()).toContain('Добавьте устройства в стек')
    expect(wrapper.find('[data-testid="stack-vlan-add"]').exists()).toBe(false)
  })

  it('перечитывает настройки при смене reloadToken (изменился состав стека)', async () => {
    const calls = mockApi(state([sharedRow()]))
    const wrapper = mountEditor()
    await flushPromises()
    await wrapper.setProps({ reloadToken: 1 })
    await flushPromises()
    expect(calls.filter((c) => c.method === 'GET' && c.url.includes('/device-stacks/stack-1/vlans'))).toHaveLength(2)
  })

  describe('снятие настройки', () => {
    const afterRemoval = state([], [{ ...OPTION_20, vlan_id: 'v-10', vlan_number: 10, vlan_name: 'mgmt' }])

    it('по умолчанию снимает только настройку: DELETE без удаления VLAN у устройств, строка исчезает, VLAN снова доступен', async () => {
      const calls = mockApi(state([sharedRow()]), (call) => (call.method === 'DELETE' ? jsonResponse(afterRemoval) : undefined))
      const wrapper = mountEditor()
      await flushPromises()

      await wrapper.get('[data-testid="stack-vlan-remove"]').trigger('click')
      expect(byId('stack-vlan-remove-dialog')).not.toBeNull()
      expect(byId('stack-vlan-remove-keep-note')?.textContent).toContain('останутся')
      byId('stack-vlan-remove-confirm')!.click()
      await flushPromises()

      expect(calls.find((c) => c.method === 'DELETE')?.url).toContain('/device-stacks/stack-1/vlans/v-10?remove_from_devices=false')
      expect(wrapper.findAll('[data-testid="stack-vlan-row"]')).toHaveLength(0)
      expect(byId('stack-vlan-remove-dialog')).toBeNull()
      expect(wrapper.emitted('removed')?.[0]).toEqual([{ vlanId: 'v-10', fromDevices: false, state: afterRemoval }])
    })

    it('с галочкой «Также убрать VLAN у всех устройств» шлёт remove_from_devices=true и предупреждает об этом', async () => {
      const calls = mockApi(state([sharedRow()]), (call) => (call.method === 'DELETE' ? jsonResponse(afterRemoval) : undefined))
      const wrapper = mountEditor()
      await flushPromises()

      await wrapper.get('[data-testid="stack-vlan-remove"]').trigger('click')
      const checkbox = byId('stack-vlan-remove-from-devices') as HTMLInputElement
      checkbox.click()
      await flushPromises()
      expect(byId('stack-vlan-remove-warn-note')).not.toBeNull()
      byId('stack-vlan-remove-confirm')!.click()
      await flushPromises()

      expect(calls.find((c) => c.method === 'DELETE')?.url).toContain('remove_from_devices=true')
      expect(wrapper.emitted('removed')?.[0]?.[0]).toMatchObject({ vlanId: 'v-10', fromDevices: true })
    })

    it('«Отмена» закрывает диалог и ничего не удаляет', async () => {
      const calls = mockApi(state([sharedRow()]))
      const wrapper = mountEditor()
      await flushPromises()
      await wrapper.get('[data-testid="stack-vlan-remove"]').trigger('click')

      byId('stack-vlan-remove-cancel')!.click()
      await flushPromises()

      expect(byId('stack-vlan-remove-dialog')).toBeNull()
      expect(calls.filter((c) => c.method === 'DELETE')).toHaveLength(0)
      expect(wrapper.findAll('[data-testid="stack-vlan-row"]')).toHaveLength(1)
    })

    it('отказ сервера (VLAN используется на портах) показывается в диалоге, настройка остаётся', async () => {
      mockApi(state([sharedRow()]), (call) => (call.method === 'DELETE' ? jsonResponse({ detail: 'VLAN 10 «mgmt» нельзя убрать с устройств стека: он используется на портах (fw-1 (2))' }, 409) : undefined))
      const wrapper = mountEditor()
      await flushPromises()
      await wrapper.get('[data-testid="stack-vlan-remove"]').trigger('click')
      ;(byId('stack-vlan-remove-from-devices') as HTMLInputElement).click()
      byId('stack-vlan-remove-confirm')!.click()
      await flushPromises()

      expect(byId('stack-vlan-remove-error')?.textContent).toContain('fw-1 (2)')
      expect(byId('stack-vlan-remove-dialog')).not.toBeNull()
      expect(wrapper.findAll('[data-testid="stack-vlan-row"]')).toHaveLength(1)
      expect(wrapper.emitted('removed')).toBeUndefined()
    })
  })
})
