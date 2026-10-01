import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import VMsView from '../VMsView.vue'
import { useVMsStore } from '../../stores/vms'
import { useCatalogsStore } from '../../stores/catalogs'
import { useDevicesStore } from '../../stores/devices'
import type { VirtualMachine } from '../../api/types'

function vm(i: number, overrides: Partial<VirtualMachine> = {}): VirtualMachine {
  return {
    id: `vm-${i}`,
    name: `VM-${String(i).padStart(2, '0')}`,
    operating_system_id: null,
    physical_device_id: null,
    hypervisor_os_id: null,
    purpose: null,
    status: 'active',
    description: null,
    ...overrides,
  }
}

function seed(vms: VirtualMachine[]) {
  const store = useVMsStore()
  store.all = vms
  store.total = vms.length
  store.loaded = true
  store.pageSize = 8
  useCatalogsStore().loaded = true
  useDevicesStore().loaded = true
  return store
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0 }))))
})

describe('VMsView.vue — поиск', () => {
  it('ввод запроса на странице > 1 возвращает на первую страницу, найденные ВМ видны', async () => {
    // 20 ВМ → 3 страницы по 8; искомая «VM-03» лежит на 1-й странице.
    const store = seed(Array.from({ length: 20 }, (_, i) => vm(i + 1)))
    const wrapper = mount(VMsView)
    store.setPage(3)
    await wrapper.vm.$nextTick()

    await wrapper.find('.search-box input').setValue('VM-03')

    expect(store.page).toBe(1)
    const names = wrapper.findAll('td.vmname').map((c) => c.text())
    expect(names).toEqual(['VM-03'])
    expect(wrapper.text()).not.toContain('Ничего не найдено')
  })

  it('очистка запроса тоже возвращает на первую страницу', async () => {
    const store = seed(Array.from({ length: 20 }, (_, i) => vm(i + 1)))
    const wrapper = mount(VMsView)
    await wrapper.find('.search-box input').setValue('VM-1')
    store.setPage(2)
    await wrapper.vm.$nextTick()

    await wrapper.find('.search-box input').setValue('')

    expect(store.page).toBe(1)
    expect(wrapper.findAll('td.vmname')).toHaveLength(8)
  })
})
