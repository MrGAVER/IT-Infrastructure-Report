import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ContainerFormModal from '../ContainerFormModal.vue'
import { useDevicesStore } from '../../stores/devices'
import { useVMsStore } from '../../stores/vms'
import { useCatalogsStore } from '../../stores/catalogs'
import type { Container } from '../../api/types'

const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 1000 }

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function seedStores() {
  const devices = useDevicesStore()
  devices.all = [{ id: 'dev-1', device_type_id: 'dt-server', system_name: 'srv-01', serial_number: 'SN-1' } as never]
  devices.loaded = true

  const vms = useVMsStore()
  vms.all = [{ id: 'vm-1', name: 'app-vm-1' } as never]
  vms.loaded = true

  const catalogs = useCatalogsStore()
  catalogs.items['device-types'] = [{ id: 'dt-server', name: 'Сервер' }]
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(EMPTY_PAGE)))
})

describe('ContainerFormModal.vue', () => {
  it('поля ВМ/устройства отключены, пока не выбран тип размещения', () => {
    seedStores()
    const wrapper = mount(ContainerFormModal, { props: { container: null } })

    const selects = wrapper.findAll('select')
    expect((selects[1].element as HTMLSelectElement).disabled).toBe(true) // ВМ
    expect((selects[2].element as HTMLSelectElement).disabled).toBe(true) // Устройство
  })

  it('выбор типа размещения "Виртуальная машина" включает соответствующий select', async () => {
    seedStores()
    const wrapper = mount(ContainerFormModal, { props: { container: null } })

    await wrapper.find('select').setValue('vm')

    const selects = wrapper.findAll('select')
    expect((selects[1].element as HTMLSelectElement).disabled).toBe(false)
    expect((selects[2].element as HTMLSelectElement).disabled).toBe(true)
  })

  it('не сохраняет контейнер без наименования', async () => {
    seedStores()
    const wrapper = mount(ContainerFormModal, { props: { container: null } })
    await wrapper.find('form').trigger('submit')

    expect(wrapper.text()).toContain('Укажите наименование контейнера')
  })

  it('создаёт контейнер на ВМ с корректным payload (physical_device_id всегда null)', async () => {
    seedStores()
    const wrapper = mount(ContainerFormModal, { props: { container: null } })

    await wrapper.find('input[type="text"]').setValue('nginx-proxy')
    await wrapper.find('select').setValue('vm')
    const selects = wrapper.findAll('select')
    await selects[1].setValue('vm-1')

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/containers')) {
          return jsonResponse({ id: 'ct-new', name: 'nginx-proxy', virtual_machine_id: 'vm-1', physical_device_id: null, runtime: null, runtime_version: null, purpose: null }, 201)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const create = calls.find((c) => c.method === 'POST')
    expect(create?.body).toMatchObject({ name: 'nginx-proxy', virtual_machine_id: 'vm-1', physical_device_id: null })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('при переключении с "устройство" на "ВМ" сбрасывает выбранное устройство', async () => {
    seedStores()
    const container: Container = { id: 'ct-1', name: 'old', virtual_machine_id: null, physical_device_id: 'dev-1', runtime: null, runtime_version: null, purpose: null }
    const wrapper = mount(ContainerFormModal, { props: { container } })

    await wrapper.find('select').setValue('vm')

    const selects = wrapper.findAll('select')
    expect((selects[2].element as HTMLSelectElement).value).toBe('') // Устройство сброшено
  })

  // Фикс п.2: "копировать контейнер для создания на его основе нового". container.name не
  // уникален (в отличие от serial_number/name у остальных трёх сущностей) — очищать нечего,
  // копия сохраняется с тем же именем, что и донор, если пользователь сам не изменит.
  it('копирование: форма открывается в режиме создания с полями донора, включая размещение', async () => {
    seedStores()
    const source: Container = { id: 'ct-src', name: 'nginx-proxy', virtual_machine_id: 'vm-1', physical_device_id: null, runtime: 'docker', runtime_version: '24.0', purpose: 'reverse proxy' }
    const wrapper = mount(ContainerFormModal, { props: { container: null, copyFrom: source } })

    expect(wrapper.find('input[type="text"]').element).toHaveProperty('value', 'nginx-proxy')
    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('vm')
    expect((wrapper.findAll('select')[1].element as HTMLSelectElement).value).toBe('vm-1')

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        if (method === 'POST' && url.endsWith('/resources/containers')) {
          return jsonResponse({ id: 'ct-new', name: 'nginx-proxy', virtual_machine_id: 'vm-1', physical_device_id: null, runtime: 'docker', runtime_version: '24.0', purpose: 'reverse proxy' }, 201)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // Копия создаёт НОВУЮ запись (POST), а не обновляет донора (PUT ct-src).
    expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/resources/containers'))).toBe(true)
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
  })
})
