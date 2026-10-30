import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceStacksView from '../DeviceStacksView.vue'
import { useDeviceStacksStore } from '../../stores/deviceStacks'
import type { DeviceStack } from '../../api/types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })),
  )
})

function seedStacks(stacks: DeviceStack[]) {
  const store = useDeviceStacksStore()
  store.all = stacks
  store.loaded = true
  return store
}

describe('DeviceStacksView.vue', () => {
  it('показывает подсказку, если стеков ещё нет', async () => {
    seedStacks([])
    const wrapper = mount(DeviceStacksView)
    await flushPromises()

    expect(wrapper.text()).toContain('Стеки устройств не созданы')
  })

  it('рендерит список стеков с описанием', async () => {
    seedStacks([
      { id: 'stack-1', name: 'Стек ядра', description: '2 коммутатора Cisco' },
      { id: 'stack-2', name: 'Стек доступа', description: null },
    ])
    const wrapper = mount(DeviceStacksView)
    await flushPromises()

    const rows = wrapper.findAll('.stack-row')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('Стек ядра')
    expect(rows[0].text()).toContain('2 коммутатора Cisco')
  })

  it('кнопка "Стек" открывает форму создания', async () => {
    seedStacks([])
    const wrapper = mount(DeviceStacksView)
    await flushPromises()

    await wrapper.find('.stacks-head button').trigger('click')

    expect(wrapper.find('.modal-head h2').text()).toBe('Добавить стек устройств')
  })

  it('кнопка "Открыть" открывает форму редактирования выбранного стека', async () => {
    seedStacks([{ id: 'stack-1', name: 'Стек ядра', description: null }])
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/device-stacks/stack-1/detail')) {
          return jsonResponse({ stack: { id: 'stack-1', name: 'Стек ядра', description: null }, members: [], connections: [] })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )
    const wrapper = mount(DeviceStacksView)
    await flushPromises()

    await wrapper.find('.stack-row .btn-secondary').trigger('click')
    await flushPromises()

    expect(wrapper.find('.modal-head h2').text()).toBe('Редактировать стек устройств')
  })

  it('удаляет стек после подтверждения', async () => {
    seedStacks([{ id: 'stack-1', name: 'Стек ядра', description: null }])
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    )
    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    const wrapper = mount(DeviceStacksView)
    await flushPromises()
    await wrapper.find('.stack-row .icon-btn.danger').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/resources/device-stacks/stack-1'))).toBe(true)
  })

  it('отмена подтверждения не отправляет запрос на удаление', async () => {
    seedStacks([{ id: 'stack-1', name: 'Стек ядра', description: null }])
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    )
    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    const wrapper = mount(DeviceStacksView)
    await flushPromises()
    await wrapper.find('.stack-row .icon-btn.danger').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  })
})
