import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import VMFormModal from '../VMFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import type { VirtualMachine } from '../../api/types'

const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 1000 }

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

// QuickAddModal.vue телепортируется в document.body — см. QuickAddModal.spec.ts.
function body(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
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
    const catalogs = useCatalogsStore()
    // Правка "убрать текстовые поля Порт/Протокол": подпись выбранной записи в SearchableSelect
    // резолвится по catalogs.protocolPortCatalog (см. OpenPortListEditor.vue:catalogOptions) —
    // без записи в сторе id 'cat-https' был бы виден только как пустой плейсхолдер.
    catalogs.protocolPortCatalog = [{ id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null }]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/resources/ip-addresses')) {
          return jsonResponse({
            ...EMPTY_PAGE,
            items: [{ id: 'ip-1', owner_type: 'virtual_machine', owner_id: 'vm-1', ip_address: '10.20.30.5', prefix_length: 24, purpose: 'LAN', is_management: true }],
          })
        }
        if (url.includes('/resources/open-ports')) {
          return jsonResponse({
            ...EMPTY_PAGE,
            items: [{ id: 'op-1', owner_type: 'virtual_machine', owner_id: 'vm-1', transport_protocol: 'TCP', port: 443, protocol: 'HTTPS', protocol_catalog_id: 'cat-https', ip_address: null, description: null }],
          })
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VMFormModal, { props: { vm } })
    await flushPromises()

    expect(wrapper.find('input[placeholder="IP-адрес"]').element).toHaveProperty('value', '10.20.30.5')
    expect(wrapper.find('.col-catalog .searchable-select input').element).toHaveProperty('value', '443 / HTTPS')
  })

  it('создаёт новую ВМ и сохраняет добавленные IP-адрес и открытый порт под её id', async () => {
    const catalogs = useCatalogsStore()
    catalogs.protocolPortCatalog = [{ id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null }]
    const wrapper = mount(VMFormModal, { props: { vm: null } })

    await wrapper.find('button.add-btn').trigger('click') // + IP-адрес
    await wrapper.find('input[placeholder="IP-адрес"]').setValue('192.168.1.10')
    const addButtons = wrapper.findAll('button.add-btn')
    await addButtons[1].trigger('click') // + Открытый порт
    await wrapper.find('.col-catalog .searchable-select input').trigger('focus')
    await wrapper.find('.col-catalog .ss-option').trigger('mousedown') // единственная опция — "22 / SSH"

    const calls: Array<{ url: string; method: string; body: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/vms')) {
          return jsonResponse({ id: 'vm-new', name: 'new-vm', operating_system_id: null, physical_device_id: null, hypervisor_os_id: null, purpose: null, status: 'active', description: null }, 201)
        }
        if (method === 'GET' && (url.includes('/resources/ip-addresses') || url.includes('/resources/open-ports'))) {
          return jsonResponse(EMPTY_PAGE)
        }
        if (method === 'POST' && url.includes('/resources/ip-addresses')) {
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

    const vmIpCreate = calls.find((c) => c.method === 'POST' && c.url.includes('/resources/ip-addresses'))
    expect(vmIpCreate?.body).toMatchObject({ owner_type: 'virtual_machine', owner_id: 'vm-new', ip_address: '192.168.1.10' })

    const openPortCreate = calls.find((c) => c.method === 'POST' && c.url.includes('/resources/open-ports'))
    // port/protocol больше не отправляются — сервер сам выводит их из protocol_catalog_id.
    expect(openPortCreate?.body).toMatchObject({ owner_type: 'virtual_machine', owner_id: 'vm-new', protocol_catalog_id: 'cat-ssh' })
    expect(openPortCreate?.body).not.toHaveProperty('port')
    expect(openPortCreate?.body).not.toHaveProperty('protocol')

    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('фикс п.3: не сохраняет ВМ с некорректным IP-адресом', async () => {
    const wrapper = mount(VMFormModal, { props: { vm: null } })
    await wrapper.find('button.add-btn').trigger('click') // + IP-адрес
    await wrapper.find('input[placeholder="IP-адрес"]').setValue('не ip адрес')
    await wrapper.find('input[required]').setValue('new-vm')

    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(fetchMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Некорректный IP-адрес')
    expect(wrapper.emitted('saved')).toBeFalsy()
  })

  it('фикс п.3: не сохраняет ВМ с некорректным префиксом', async () => {
    const wrapper = mount(VMFormModal, { props: { vm: null } })
    await wrapper.find('button.add-btn').trigger('click') // + IP-адрес
    await wrapper.find('input[placeholder="IP-адрес"]').setValue('10.0.0.1')
    await wrapper.find('input.col-prefix').setValue('999')
    await wrapper.find('input[required]').setValue('new-vm')

    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(fetchMock).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Некорректный префикс')
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

    expect(calls.some((c) => c.method === 'POST' && c.url.includes('/resources/ip-addresses'))).toBe(false)
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
        if (method === 'GET' && url.includes('/resources/ip-addresses')) {
          return jsonResponse({ ...EMPTY_PAGE, items: [{ id: 'ip-old', owner_type: 'virtual_machine', owner_id: 'vm-1', ip_address: '10.0.0.1', prefix_length: null, purpose: null, is_management: false }] })
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

    expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/resources/ip-addresses/ip-old'))).toBe(true)
  })

  it('сохраняет добавленный программный актив под id новой ВМ', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['software-assets'] = [{ id: 'sa-1c', name: '1С:Предприятие' }]
    const wrapper = mount(VMFormModal, { props: { vm: null } })

    const addButtons = wrapper.findAll('button.add-btn')
    await addButtons[2].trigger('click') // + Программный актив
    await wrapper.find('.col-asset select').setValue('sa-1c')
    await wrapper.find('input.col-version').setValue('8.3.20')

    const calls: Array<{ url: string; method: string; body: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/vms')) {
          return jsonResponse({ id: 'vm-new', name: 'new-vm', operating_system_id: null, physical_device_id: null, hypervisor_os_id: null, purpose: null, status: 'active', description: null }, 201)
        }
        if (method === 'POST' && url.includes('/resources/deployed-software')) {
          return jsonResponse({ id: 'sw-new' }, 201)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('input[required]').setValue('new-vm')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const softwareCreate = calls.find((c) => c.method === 'POST' && c.url.includes('/resources/deployed-software'))
    expect(softwareCreate?.body).toMatchObject({ owner_type: 'virtual_machine', owner_id: 'vm-new', software_asset_id: 'sa-1c', version: '8.3.20' })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('быстрое добавление операционной системы подставляет её в форму', async () => {
    const wrapper = mount(VMFormModal, { props: { vm: null } })
    const catalogs = useCatalogsStore()
    catalogs.items['os-categories'] = [{ id: 'cat-1', name: 'Серверные ОС' }]
    catalogs.items['operating-systems'] = []

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/operating-systems')) {
          return jsonResponse({ id: 'os-new', name: 'Astra Linux 1.7' }, 201)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('.lookup-row button').trigger('click')
    // operating-systems: [category_id (fk, SearchableSelect), name (text), version (text),
    // vendor (text), description (textarea)] — после поискового поля SearchableSelect'а идёт
    // "Наименование ОС" вторым по счёту input[type="text"] (index 1), не последним — после него
    // ещё "Версия" и "Производитель", тоже текстовые поля.
    await body().find('.searchable-select input').trigger('focus')
    await body().find('.ss-option').trigger('mousedown') // единственный вариант — cat-1 "Серверные ОС"
    await body().findAll('input[type="text"]')[1].setValue('Astra Linux 1.7')
    await body().find('form').trigger('submit')
    await flushPromises()

    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('os-new')
  })

  describe('фикс п.2: копирование ВМ ("copyFrom")', () => {
    const sourceVM: VirtualMachine = {
      id: 'vm-src',
      name: 'app-server-01',
      operating_system_id: 'os-1',
      physical_device_id: null,
      hypervisor_os_id: null,
      purpose: 'веб-сервер',
      status: 'active',
      description: null,
    }

    it('аудит fix/usability-batch4 (находка №5): одновременная передача vm и copyFrom — предупреждение в консоль, побеждает vm (edit)', async () => {
      const catalogs = useCatalogsStore()
      catalogs.items['operating-systems'] = [{ id: 'os-1', name: 'Astra Linux' }]
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

      const editedVM: VirtualMachine = { ...sourceVM, id: 'vm-edit', name: 'app-server-edit' }
      const wrapper = mount(VMFormModal, { props: { vm: editedVM, copyFrom: sourceVM } })
      await flushPromises()

      expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('используется vm'))
      expect(wrapper.find('h2').text()).toContain('Редактировать') // vm выигрывает — это по-прежнему edit
      expect(wrapper.find('input[required]').element).toHaveProperty('value', 'app-server-edit')
    })

    it('форма открывается в режиме создания, поля донора подставлены, name (уникален) очищен', async () => {
      const catalogs = useCatalogsStore()
      catalogs.items['operating-systems'] = [{ id: 'os-1', name: 'Astra Linux' }]
      const wrapper = mount(VMFormModal, { props: { vm: null, copyFrom: sourceVM } })
      await flushPromises()

      expect(wrapper.find('h2').text()).not.toContain('Редактировать')
      expect(wrapper.find('input[required]').element).toHaveProperty('value', '') // Название — уникально, очищено
      expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('os-1') // ОС скопирована как есть
    })

    it('IP-адреса и открытые порты донора подгружаются, но сохраняются без его id', async () => {
      const calls: Array<{ url: string; method: string; body?: unknown }> = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
          if (method === 'GET' && url.includes('/resources/ip-addresses')) {
            return jsonResponse({ ...EMPTY_PAGE, items: [{ id: 'ip-src', owner_type: 'virtual_machine', owner_id: 'vm-src', ip_address: '10.20.30.5', prefix_length: 24, purpose: 'LAN', is_management: true }] })
          }
          if (method === 'POST' && url.endsWith('/resources/vms')) {
            return jsonResponse({ id: 'vm-new', name: 'app-server-02', operating_system_id: 'os-1', physical_device_id: null, hypervisor_os_id: null, purpose: 'веб-сервер', status: 'active', description: null }, 201)
          }
          return jsonResponse(EMPTY_PAGE)
        }),
      )

      const wrapper = mount(VMFormModal, { props: { vm: null, copyFrom: sourceVM } })
      await flushPromises()
      expect(wrapper.find('input[placeholder="IP-адрес"]').element).toHaveProperty('value', '10.20.30.5')

      await wrapper.find('input[required]').setValue('app-server-02')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const ipCreate = calls.find((c) => c.method === 'POST' && c.url.includes('/resources/ip-addresses'))
      expect(ipCreate?.body).toMatchObject({ owner_type: 'virtual_machine', owner_id: 'vm-new', ip_address: '10.20.30.5' })
      // Копия создаёт НОВУЮ ВМ (POST), а не обновляет донора.
      expect(calls.some((c) => c.method === 'PUT' && c.url.includes('/resources/vms/vm-src'))).toBe(false)
    })
  })
})
