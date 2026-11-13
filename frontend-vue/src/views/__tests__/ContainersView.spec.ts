import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ContainersView from '../ContainersView.vue'
import { useContainersStore } from '../../stores/containers'
import { useDevicesStore } from '../../stores/devices'
import { useVMsStore } from '../../stores/vms'
import type { Container } from '../../api/types'

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

function seedStores(containers: Container[]) {
  const store = useContainersStore()
  store.all = containers
  store.loaded = true

  const devices = useDevicesStore()
  devices.all = [{ id: 'dev-1', system_name: 'srv-01', serial_number: 'SN-1' } as never]
  devices.loaded = true

  const vms = useVMsStore()
  vms.all = [{ id: 'vm-1', name: 'app-vm-1' } as never]
  vms.loaded = true

  return store
}

describe('ContainersView.vue', () => {
  // До F-04 здесь стоял пустой реестр: тест закреплял именно дефект — «не найдено по фильтрам» при нуле записей и нуле фильтров.
  // Пустой реестр и его текст проверяет listEmptyState.spec.ts.
  it('показывает подсказку, если по фильтру ничего не найдено', async () => {
    const store = seedStores([
      { id: 'ct-1', name: 'nginx', virtual_machine_id: null, physical_device_id: null, runtime: null, runtime_version: null, purpose: null },
    ])
    const wrapper = mount(ContainersView)
    await flushPromises()
    store.search = 'нет такого'
    await flushPromises()

    expect(wrapper.text()).toContain('Ничего не найдено')
  })

  it('показывает размещение контейнера (ВМ/устройство/не указано)', async () => {
    seedStores([
      { id: 'ct-1', name: 'on-vm', virtual_machine_id: 'vm-1', physical_device_id: null, runtime: null, runtime_version: null, purpose: null },
      { id: 'ct-2', name: 'on-device', virtual_machine_id: null, physical_device_id: 'dev-1', runtime: null, runtime_version: null, purpose: null },
      { id: 'ct-3', name: 'nowhere', virtual_machine_id: null, physical_device_id: null, runtime: null, runtime_version: null, purpose: null },
    ])
    const wrapper = mount(ContainersView)
    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    expect(rows[0].text()).toContain('ВМ: app-vm-1')
    expect(rows[1].text()).toContain('Устройство: srv-01')
    expect(rows[2].text()).toContain('—')
  })

  it('открывает форму редактирования по клику на "Редактировать"', async () => {
    seedStores([{ id: 'ct-1', name: 'nginx', virtual_machine_id: null, physical_device_id: null, runtime: null, runtime_version: null, purpose: null }])
    const wrapper = mount(ContainersView)
    await flushPromises()

    await wrapper.find('[aria-label="Редактировать"]').trigger('click')

    expect(wrapper.find('.modal-head h2').text()).toContain('Редактировать контейнер')
  })

  it('удаляет контейнер после подтверждения', async () => {
    seedStores([{ id: 'ct-1', name: 'nginx', virtual_machine_id: null, physical_device_id: null, runtime: null, runtime_version: null, purpose: null }])
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

    const wrapper = mount(ContainersView)
    await flushPromises()
    await wrapper.find('[aria-label="Удалить"]').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/resources/containers/ct-1'))).toBe(true)
  })

  it('фильтрует по строке поиска', async () => {
    seedStores([
      { id: 'ct-1', name: 'nginx-proxy', virtual_machine_id: null, physical_device_id: null, runtime: 'Docker', runtime_version: null, purpose: null },
      { id: 'ct-2', name: 'redis-cache', virtual_machine_id: null, physical_device_id: null, runtime: 'Docker', runtime_version: null, purpose: null },
    ])
    const wrapper = mount(ContainersView)
    await flushPromises()

    await wrapper.find('.search-box input').setValue('redis')
    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(1)
    expect(rows[0].text()).toContain('redis-cache')
  })

  it('ввод запроса на странице > 1 возвращает на первую страницу, найденный контейнер виден', async () => {
    // 20 контейнеров → 3 страницы по 8; искомый «ct-03» лежит на 1-й странице.
    const containers = Array.from({ length: 20 }, (_, i) => ({
      id: `ct-${i + 1}`,
      name: `ct-${String(i + 1).padStart(2, '0')}`,
      virtual_machine_id: null,
      physical_device_id: null,
      runtime: null,
      runtime_version: null,
      purpose: null,
    }))
    const store = seedStores(containers)
    store.pageSize = 8
    const wrapper = mount(ContainersView)
    await flushPromises()
    store.setPage(3)
    await flushPromises()

    await wrapper.find('.search-box input').setValue('ct-03')
    await flushPromises()

    expect(store.page).toBe(1)
    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(1)
    expect(rows[0].text()).toContain('ct-03')
    expect(wrapper.text()).not.toContain('Ничего не найдено')
  })
})
