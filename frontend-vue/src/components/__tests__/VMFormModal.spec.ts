import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import VMFormModal from '../VMFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { usePreferencesStore } from '../../stores/preferences'
import { useToast } from '../../composables/useToast'
import { useDevicesStore } from '../../stores/devices'
import type { Device, VirtualMachine } from '../../api/types'

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
  useToast().toasts.splice(0)
})

describe('VMFormModal.vue', () => {
  it('R2-01: усечённая загрузка вложенного списка ВМ не молчит — предупреждение о неполных данных', async () => {
    const vm: VirtualMachine = {
      id: 'vm-1',
      name: 'app-server-01',
      operating_system_id: null,
      physical_device_id: null,
      hypervisor_os_id: null,
      purpose: null,
      description: null,
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        // у ВМ «2000» IP-адресов, но сервер отдаёт только первую страницу, а на следующие отвечает пустыми
        if (url.includes('/resources/ip-addresses')) {
          const offset = Number(new URL(url, 'http://localhost').searchParams.get('offset'))
          const items =
            offset === 0
              ? [
                  {
                    id: 'ip-1',
                    owner_type: 'virtual_machine',
                    owner_id: 'vm-1',
                    ip_address: '10.0.0.1',
                    prefix_length: 24,
                    purpose: null,
                    is_management: false,
                  },
                ]
              : []
          return jsonResponse({ items, total: 2000, offset, limit: 1000 })
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    mount(VMFormModal, { props: { vm } })
    await flushPromises()

    const warnings = useToast().toasts.filter((t) => t.type === 'warning')
    expect(warnings).toHaveLength(1)
    expect(warnings[0].message).toContain('IP-адресов ВМ')
  })

  it('при редактировании подгружает существующие IP-адреса и открытые порты ВМ', async () => {
    const vm: VirtualMachine = {
      id: 'vm-1',
      name: 'app-server-01',
      operating_system_id: null,
      physical_device_id: null,
      hypervisor_os_id: null,
      purpose: null,
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
            items: [
              { id: 'ip-1', owner_type: 'virtual_machine', owner_id: 'vm-1', ip_address: '10.20.30.5', prefix_length: 24, purpose: 'LAN', is_management: true },
            ],
          })
        }
        if (url.includes('/resources/open-ports')) {
          return jsonResponse({
            ...EMPTY_PAGE,
            items: [
              {
                id: 'op-1',
                owner_type: 'virtual_machine',
                owner_id: 'vm-1',
                transport_protocol: 'TCP',
                port: 443,
                protocol: 'HTTPS',
                protocol_catalog_id: 'cat-https',
                ip_address: null,
                description: null,
              },
            ],
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
          return jsonResponse(
            { id: 'vm-new', name: 'new-vm', operating_system_id: null, physical_device_id: null, hypervisor_os_id: null, purpose: null, description: null },
            201,
          )
        }
        if (method === 'GET' && (url.includes('/resources/ip-addresses') || url.includes('/resources/open-ports'))) {
          return jsonResponse(EMPTY_PAGE)
        }
        if (method === 'PUT' && url.endsWith('/vms/vm-new/ip-addresses')) {
          return jsonResponse({ items: [{ id: 'ip-new' }] })
        }
        if (method === 'PUT' && url.endsWith('/vms/vm-new/open-ports')) {
          return jsonResponse({ items: [{ id: 'port-new' }] })
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('input[required]').setValue('new-vm') // Название
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // IP-адреса и порты уходят одним PUT на список под id новой ВМ, а не отдельными POST /resources/*.
    const ipSync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/vms/vm-new/ip-addresses'))
    expect(ipSync?.body).toEqual({ ip_addresses: [{ ip_address: '192.168.1.10', prefix_length: null, purpose: null, is_management: false }] })
    const portSync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/vms/vm-new/open-ports'))
    // port/protocol больше не отправляются — сервер сам выводит их из protocol_catalog_id.
    expect(portSync?.body).toEqual({ open_ports: [{ protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: null }] })
    expect(calls.some((c) => /\/resources\/(ip-addresses|open-ports)/.test(c.url) && c.method !== 'GET')).toBe(false)

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
          return jsonResponse(
            { id: 'vm-new', name: 'new-vm', operating_system_id: null, physical_device_id: null, hypervisor_os_id: null, purpose: null, description: null },
            201,
          )
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('input[required]').setValue('new-vm')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    // Новой ВМ без заполненных строк синхронизировать нечего — запросов к спискам нет вовсе.
    expect(calls.some((c) => c.method !== 'GET' && /ip-addresses|open-ports|deployed-software/.test(c.url))).toBe(false)
  })

  describe('IP-адреса и программные активы существующей ВМ сохраняются без удаления и пересоздания', () => {
    const vm: VirtualMachine = {
      id: 'vm-1',
      name: 'app-server-01',
      operating_system_id: null,
      physical_device_id: null,
      hypervisor_os_id: null,
      purpose: null,
      description: null,
    }
    const apiIp = (id: string, ip: string) => ({
      id,
      owner_type: 'virtual_machine',
      owner_id: 'vm-1',
      ip_address: ip,
      prefix_length: null,
      purpose: null,
      is_management: false,
    })
    const apiSoftware = (id: string, assetId: string, version: string | null) => ({
      id,
      owner_type: 'virtual_machine',
      owner_id: 'vm-1',
      software_asset_id: assetId,
      version,
    })

    type Call = { url: string; method: string; body: unknown }
    function stubApi(ips: unknown[], software: unknown[]): Call[] {
      const calls: Call[] = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
          if (method === 'GET' && url.includes('/resources/ip-addresses')) return jsonResponse({ ...EMPTY_PAGE, items: ips })
          if (method === 'GET' && url.includes('/resources/deployed-software')) return jsonResponse({ ...EMPTY_PAGE, items: software })
          if (method === 'PUT' && /\/vms\/vm-1\/(ip-addresses|open-ports|deployed-software)$/.test(url)) return jsonResponse({ items: [] })
          if (method === 'PUT' && url.includes('/resources/vms/vm-1')) return jsonResponse({ ...vm })
          return jsonResponse(EMPTY_PAGE)
        }),
      )
      return calls
    }
    const writes = (calls: Call[]) => calls.filter((c) => c.method !== 'GET').map((c) => `${c.method} ${c.url}`)

    it('IP-адреса: один PUT с id сохранённого адреса, без DELETE и POST', async () => {
      const calls = stubApi([apiIp('ip-old', '10.0.0.1')], [])
      const wrapper = mount(VMFormModal, { props: { vm } })
      await flushPromises()

      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(writes(calls)).toContain('PUT /api/v1/vms/vm-1/ip-addresses')
      expect(writes(calls).some((w) => /^(DELETE|POST) .*\/resources\/ip-addresses/.test(w))).toBe(false)
      const sync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/vms/vm-1/ip-addresses'))
      expect(sync?.body).toEqual({ ip_addresses: [{ id: 'ip-old', ip_address: '10.0.0.1', prefix_length: null, purpose: null, is_management: false }] })
      expect(wrapper.emitted('saved')).toBeTruthy()
    })

    it('IP-адрес, убранный в форме, в запрос не попадает — сервер его удалит', async () => {
      const calls = stubApi([apiIp('ip-1', '10.0.0.1'), apiIp('ip-2', '10.0.0.2')], [])
      const wrapper = mount(VMFormModal, { props: { vm } })
      await flushPromises()

      await wrapper.findAll('button[aria-label="Удалить IP-адрес"]')[0].trigger('click')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const sync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/vms/vm-1/ip-addresses'))
      expect(sync?.body).toEqual({ ip_addresses: [{ id: 'ip-2', ip_address: '10.0.0.2', prefix_length: null, purpose: null, is_management: false }] })
      expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    })

    it('ВМ без IP-адресов в форме: PUT с пустым списком снимает ранее сохранённые адреса', async () => {
      const calls = stubApi([apiIp('ip-1', '10.0.0.1')], [])
      const wrapper = mount(VMFormModal, { props: { vm } })
      await flushPromises()

      await wrapper.find('button[aria-label="Удалить IP-адрес"]').trigger('click')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const sync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/vms/vm-1/ip-addresses'))
      expect(sync?.body).toEqual({ ip_addresses: [] })
    })

    it('программные активы: один PUT с id сохранённой записи, без DELETE и POST', async () => {
      const calls = stubApi([], [apiSoftware('sw-old', 'sa-1c', '8.3.20')])
      const wrapper = mount(VMFormModal, { props: { vm } })
      await flushPromises()

      await wrapper.find('form').trigger('submit')
      await flushPromises()

      expect(writes(calls).some((w) => /^(DELETE|POST) .*\/resources\/deployed-software/.test(w))).toBe(false)
      const sync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/vms/vm-1/deployed-software'))
      expect(sync?.body).toEqual({ deployed_software: [{ id: 'sw-old', software_asset_id: 'sa-1c', version: '8.3.20' }] })
      expect(wrapper.emitted('saved')).toBeTruthy()
    })

    it('ПО, убранное в форме, в запрос не попадает — сервер его удалит', async () => {
      const calls = stubApi([], [apiSoftware('sw-1', 'sa-1c', null), apiSoftware('sw-2', 'sa-nginx', '1.25')])
      const wrapper = mount(VMFormModal, { props: { vm } })
      await flushPromises()

      await wrapper.findAll('button[aria-label="Удалить программный актив"]')[0].trigger('click')
      await wrapper.find('form').trigger('submit')
      await flushPromises()

      const sync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/vms/vm-1/deployed-software'))
      expect(sync?.body).toEqual({ deployed_software: [{ id: 'sw-2', software_asset_id: 'sa-nginx', version: '1.25' }] })
      expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    })
  })

  it('сохраняет добавленный программный актив под id новой ВМ', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['software-assets'] = [{ id: 'sa-1c', name: '1С:Предприятие' }]
    const wrapper = mount(VMFormModal, { props: { vm: null } })

    const addButtons = wrapper.findAll('button.add-btn')
    await addButtons[2].trigger('click') // + Программный актив
    await wrapper.find('.col-asset .searchable-select input').trigger('focus')
    await wrapper.find('.col-asset .ss-option').trigger('mousedown') // единственная опция — "1С:Предприятие"
    await wrapper.find('input.col-version').setValue('8.3.20')

    const calls: Array<{ url: string; method: string; body: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/vms')) {
          return jsonResponse(
            { id: 'vm-new', name: 'new-vm', operating_system_id: null, physical_device_id: null, hypervisor_os_id: null, purpose: null, description: null },
            201,
          )
        }
        if (method === 'PUT' && url.endsWith('/vms/vm-new/deployed-software')) {
          return jsonResponse({ items: [{ id: 'sw-new' }] })
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('input[required]').setValue('new-vm')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const softwareSync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/vms/vm-new/deployed-software'))
    expect(softwareSync?.body).toEqual({ deployed_software: [{ software_asset_id: 'sa-1c', version: '8.3.20' }] })
    expect(calls.some((c) => c.method === 'POST' && c.url.includes('/resources/deployed-software'))).toBe(false)
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

    // Поле «Операционная система» — SearchableSelect: выбранное значение показывается подписью опции
    // («название версия»), а не id, как у нативного <select>.
    expect(wrapper.find('select').exists()).toBe(false)
    expect((wrapper.find('.lookup-row .searchable-select input').element as HTMLInputElement).value).toBe('Astra Linux 1.7')
  })

  describe('фикс п.2: копирование ВМ ("copyFrom")', () => {
    const sourceVM: VirtualMachine = {
      id: 'vm-src',
      name: 'app-server-01',
      operating_system_id: 'os-1',
      physical_device_id: null,
      hypervisor_os_id: null,
      purpose: 'веб-сервер',
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
      // ОС скопирована как есть: SearchableSelect показывает подпись выбранной ОС, а не её id
      expect((wrapper.find('.lookup-row .searchable-select input').element as HTMLInputElement).value).toBe('Astra Linux')
    })

    it('IP-адреса и открытые порты донора подгружаются, но сохраняются без его id', async () => {
      const calls: Array<{ url: string; method: string; body?: unknown }> = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
          if (method === 'GET' && url.includes('/resources/ip-addresses')) {
            return jsonResponse({
              ...EMPTY_PAGE,
              items: [
                {
                  id: 'ip-src',
                  owner_type: 'virtual_machine',
                  owner_id: 'vm-src',
                  ip_address: '10.20.30.5',
                  prefix_length: 24,
                  purpose: 'LAN',
                  is_management: true,
                },
              ],
            })
          }
          if (method === 'POST' && url.endsWith('/resources/vms')) {
            return jsonResponse(
              {
                id: 'vm-new',
                name: 'app-server-02',
                operating_system_id: 'os-1',
                physical_device_id: null,
                hypervisor_os_id: null,
                purpose: 'веб-сервер',
                description: null,
              },
              201,
            )
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

      // Адрес донора уходит под новой ВМ и без id донора — иначе сервер принял бы его за чужую запись (422).
      const ipSync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/vms/vm-new/ip-addresses'))
      expect(ipSync?.body).toEqual({ ip_addresses: [{ ip_address: '10.20.30.5', prefix_length: 24, purpose: 'LAN', is_management: true }] })
      expect(JSON.stringify(calls.map((c) => c.body))).not.toContain('ip-src')
      // Копия создаёт НОВУЮ ВМ (POST), а не обновляет донора.
      expect(calls.some((c) => c.method === 'PUT' && c.url.includes('/resources/vms/vm-src'))).toBe(false)
    })
  })
})

describe('VMFormModal.vue — открытые порты: сортировка и уникальность', () => {
  const portCatalog = [
    { id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null },
    { id: 'cat-http', port: 80, protocol_type: 'HTTP', description: null },
    { id: 'cat-http-alt', port: 80, protocol_type: 'HTTP-Proxy', description: null },
    { id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null },
  ]
  const existingVm: VirtualMachine = {
    id: 'vm-1',
    name: 'app-server-01',
    operating_system_id: null,
    physical_device_id: null,
    hypervisor_os_id: null,
    purpose: null,
    description: null,
  }
  const apiPort = (id: string, catalogId: string) => ({
    id,
    owner_type: 'virtual_machine',
    owner_id: 'vm-1',
    transport_protocol: 'TCP',
    protocol_catalog_id: catalogId,
    ip_address: null,
    description: null,
  })

  type Call = { url: string; method: string; body: unknown }
  function stubApi(openPortsFromServer: unknown[]): Call[] {
    const calls: Call[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'GET' && url.includes('/resources/open-ports')) return jsonResponse({ ...EMPTY_PAGE, items: openPortsFromServer })
        if (method === 'POST' && url.endsWith('/resources/vms')) return jsonResponse({ ...existingVm, id: 'vm-new' }, 201)
        if (method === 'PUT' && url.includes('/open-ports')) return jsonResponse({ items: [] })
        if (method === 'PUT' && url.includes('/resources/vms/')) return jsonResponse(existingVm)
        if (method === 'POST') return jsonResponse({ id: 'new' }, 201)
        return jsonResponse(EMPTY_PAGE)
      }),
    )
    return calls
  }
  const shownPorts = (wrapper: ReturnType<typeof mount>) =>
    wrapper.findAll('.col-catalog .searchable-select input').map((i) => (i.element as HTMLInputElement).value)

  it('ранее сохранённые порты открываются отсортированными по номеру порта', async () => {
    useCatalogsStore().protocolPortCatalog = portCatalog
    stubApi([apiPort('op-1', 'cat-https'), apiPort('op-2', 'cat-ssh'), apiPort('op-3', 'cat-http')])

    const wrapper = mount(VMFormModal, { props: { vm: existingVm } })
    await flushPromises()

    expect(shownPorts(wrapper)).toEqual(['22 / SSH', '80 / HTTP', '443 / HTTPS'])
  })

  it('не сохраняет ВМ с повторяющимися номерами портов и объясняет причину', async () => {
    useCatalogsStore().protocolPortCatalog = portCatalog
    // Разные записи справочника, но один номер порта — 80.
    const calls = stubApi([apiPort('op-1', 'cat-http'), apiPort('op-2', 'cat-http-alt')])

    const wrapper = mount(VMFormModal, { props: { vm: existingVm } })
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('.form-error').text()).toContain('Номера открытых портов не должны повторяться: 80')
    expect(calls.some((c) => c.method !== 'GET')).toBe(false) // ни PUT ВМ, ни пересоздания портов
    expect(wrapper.emitted('saved')).toBeFalsy()
  })

  it('список сортируется при добавлении следующего порта, а не при выборе записи в строке', async () => {
    useCatalogsStore().protocolPortCatalog = portCatalog
    const calls = stubApi([])
    const wrapper = mount(VMFormModal, { props: { vm: null } })
    await flushPromises()

    const pick = async (rowIndex: number, label: string) => {
      await wrapper.findAll('.col-catalog .searchable-select input')[rowIndex].trigger('focus')
      await wrapper
        .findAll('.col-catalog .ss-option')
        .find((o) => o.text() === label)!
        .trigger('mousedown')
    }
    await wrapper.findAll('button.add-btn')[1].trigger('click') // + Открытый порт
    await pick(0, '443 / HTTPS')
    await wrapper.findAll('button.add-btn')[1].trigger('click')
    await pick(1, '22 / SSH')

    // Выбранный порт остаётся на месте — только что добавленную строку удобно дозаполнять.
    expect(shownPorts(wrapper)).toEqual(['443 / HTTPS', '22 / SSH'])

    await wrapper.findAll('button.add-btn')[1].trigger('click') // следующий порт — вот тогда сортировка
    expect(shownPorts(wrapper)).toEqual(['22 / SSH', '443 / HTTPS', ''])

    await wrapper.find('input[required]').setValue('new-vm')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const sync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/vms/vm-new/open-ports'))
    expect((sync?.body as { open_ports: Array<{ protocol_catalog_id: string }> }).open_ports.map((p) => p.protocol_catalog_id)).toEqual([
      'cat-ssh',
      'cat-https',
    ])
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('сохранение ВМ не удаляет и не пересоздаёт порты: один PUT, id сохранённых портов в запросе', async () => {
    useCatalogsStore().protocolPortCatalog = portCatalog
    const calls = stubApi([apiPort('op-1', 'cat-https'), apiPort('op-2', 'cat-ssh')])
    const wrapper = mount(VMFormModal, { props: { vm: existingVm } })
    await flushPromises()

    await wrapper.findAll('button.add-btn')[1].trigger('click') // + Открытый порт
    await wrapper.findAll('.col-catalog .searchable-select input')[2].trigger('focus')
    await wrapper
      .findAll('.col-catalog .ss-option')
      .find((o) => o.text() === '80 / HTTP')!
      .trigger('mousedown')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(calls.filter((c) => c.url.includes('/open-ports') && c.method !== 'GET').map((c) => `${c.method} ${c.url}`)).toEqual([
      'PUT /api/v1/vms/vm-1/open-ports',
    ])
    const sync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/vms/vm-1/open-ports'))
    expect(sync?.body).toEqual({
      open_ports: [
        { id: 'op-2', protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: null },
        { id: 'op-1', protocol_catalog_id: 'cat-https', transport_protocol: 'TCP', description: null },
        { protocol_catalog_id: 'cat-http', transport_protocol: 'TCP', description: null }, // новый — без id
      ],
    })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('порт, убранный в форме, в запрос не попадает — сервер его удалит', async () => {
    useCatalogsStore().protocolPortCatalog = portCatalog
    const calls = stubApi([apiPort('op-1', 'cat-https'), apiPort('op-2', 'cat-ssh')])
    const wrapper = mount(VMFormModal, { props: { vm: existingVm } })
    await flushPromises()

    await wrapper.findAll('button[aria-label="Удалить открытый порт"]')[0].trigger('click') // первая строка — 22 / SSH
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const sync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/vms/vm-1/open-ports'))
    expect(sync?.body).toEqual({ open_ports: [{ id: 'op-1', protocol_catalog_id: 'cat-https', transport_protocol: 'TCP', description: null }] })
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  })

  it('ВМ без портов в форме: PUT с пустым списком снимает ранее сохранённые порты', async () => {
    useCatalogsStore().protocolPortCatalog = portCatalog
    const calls = stubApi([apiPort('op-1', 'cat-https')])
    const wrapper = mount(VMFormModal, { props: { vm: existingVm } })
    await flushPromises()

    await wrapper.find('button[aria-label="Удалить открытый порт"]').trigger('click')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const sync = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/vms/vm-1/open-ports'))
    expect(sync?.body).toEqual({ open_ports: [] })
  })
})

describe('VMFormModal.vue — открытые порты сворачиваются по общему порогу из «Настроек»', () => {
  const catalog = Array.from({ length: 4 }, (_, i) => ({ id: `cat-${i}`, port: 8000 + i, protocol_type: `P${i}`, description: null }))
  const vm: VirtualMachine = {
    id: 'vm-1',
    name: 'app-server-01',
    operating_system_id: null,
    physical_device_id: null,
    hypervisor_os_id: null,
    purpose: null,
    description: null,
  }
  const apiPort = (i: number) => ({
    id: `op-${i}`,
    owner_type: 'virtual_machine',
    owner_id: 'vm-1',
    transport_protocol: 'TCP',
    protocol_catalog_id: `cat-${i}`,
    ip_address: null,
    description: null,
  })
  function stubPorts(items: unknown[]) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        if (method === 'GET' && url.includes('/resources/open-ports')) return jsonResponse({ ...EMPTY_PAGE, items })
        return jsonResponse(EMPTY_PAGE)
      }),
    )
  }

  it('при 3 портах и пороге 2 список свёрнут, а при пороге по умолчанию (10) — развёрнут', async () => {
    useCatalogsStore().protocolPortCatalog = catalog
    stubPorts([apiPort(0), apiPort(1), apiPort(2)])
    usePreferencesStore().user = { device_vlan_collapse_rows: 2 }
    const collapsed = mount(VMFormModal, { props: { vm } })
    await flushPromises()
    expect(collapsed.find('[data-testid="ports-collapsed"]').exists()).toBe(true)
    expect(collapsed.findAll('.col-catalog').length).toBe(0)
    collapsed.unmount()

    setActivePinia(createPinia())
    useCatalogsStore().protocolPortCatalog = catalog
    document.body.innerHTML = ''
    const expanded = mount(VMFormModal, { props: { vm } })
    await flushPromises()
    expect(expanded.find('[data-testid="ports-collapsed"]').exists()).toBe(false)
    expect(expanded.findAll('.col-catalog').length).toBe(3)
  })
})

describe('VMFormModal.vue — «Операционная система» и «Физическое устройство (хост)»: поиск и сортировка', () => {
  const serverDevice = (id: string, systemName: string | null, serial = `SN-${id}`, typeId = 'dt-server'): Device =>
    ({ id, device_type_id: typeId, system_name: systemName, serial_number: serial, operating_system_id: null }) as Device

  function seedCatalogs() {
    const catalogs = useCatalogsStore()
    catalogs.items['device-types'] = [
      { id: 'dt-server', name: 'Сервер' },
      { id: 'dt-storage', name: 'Система хранения данных' },
      { id: 'dt-switch', name: 'Коммутатор' },
    ]
    // Намеренно НЕ по алфавиту: форма не должна полагаться на порядок, в котором справочник пришёл в стор.
    catalogs.items['operating-systems'] = [
      { id: 'os-win', name: 'Windows Server', version: '2019' },
      { id: 'os-astra', name: 'Astra Linux', version: '1.7' },
      { id: 'os-ubuntu', name: 'Ubuntu', version: '22.04' },
      { id: 'os-alt', name: 'Альт Сервер', version: '10' },
    ]
  }

  /** SearchableSelect внутри <label class="field">, в заголовке которого есть title. */
  function fieldSelect(wrapper: ReturnType<typeof mount>, title: string) {
    const field = wrapper.findAll('label.field').find((l) => l.find('span').text().startsWith(title))
    if (!field) throw new Error(`Поле «${title}» не найдено`)
    return field.find('.searchable-select')
  }
  async function openAndList(select: ReturnType<typeof fieldSelect>): Promise<string[]> {
    await select.find('input').trigger('focus')
    return select.findAll('.ss-option').map((o) => o.text())
  }

  it('«Операционная система» — SearchableSelect, а не нативный select', () => {
    seedCatalogs()
    const wrapper = mount(VMFormModal, { props: { vm: null } })
    expect(fieldSelect(wrapper, 'Операционная система').exists()).toBe(true)
    expect(wrapper.find('select').exists()).toBe(false)
  })

  it('«Операционная система»: список отсортирован по подписи независимо от порядка в справочнике', async () => {
    seedCatalogs()
    const wrapper = mount(VMFormModal, { props: { vm: null } })
    // Порядок — общий RU_COLLATOR приложения (как в остальных списках): кириллица раньше латиницы.
    expect(await openAndList(fieldSelect(wrapper, 'Операционная система'))).toEqual([
      'Альт Сервер 10',
      'Astra Linux 1.7',
      'Ubuntu 22.04',
      'Windows Server 2019',
    ])
  })

  it('«Операционная система»: ввод текста оставляет только подходящие варианты, выбор записывает ОС в ВМ', async () => {
    seedCatalogs()
    const calls: { url: string; method: string; body: Record<string, unknown> | undefined }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/vms')) return jsonResponse({ id: 'vm-new', name: 'vm' }, 201)
        return jsonResponse(EMPTY_PAGE)
      }),
    )
    const wrapper = mount(VMFormModal, { props: { vm: null } })
    const select = fieldSelect(wrapper, 'Операционная система')
    await select.find('input').trigger('focus')
    await select.find('input').setValue('win')
    expect(select.findAll('.ss-option').map((o) => o.text())).toEqual(['Windows Server 2019'])

    await select.find('.ss-option').trigger('mousedown')
    await wrapper.find('input[maxlength="255"]').setValue('vm')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const create = calls.find((c) => c.method === 'POST' && c.url.endsWith('/resources/vms'))
    expect(create?.body?.operating_system_id).toBe('os-win')
  })

  it('«Физическое устройство (хост)» — SearchableSelect, в нём только серверы и СХД, отсортированные по подписи', async () => {
    seedCatalogs()
    // Порядок как в ответе API — не алфавитный; srv-10 должен идти после srv-2 (натуральная сортировка).
    useDevicesStore().all = [
      serverDevice('d10', 'srv-10'),
      serverDevice('d-sw', 'sw-core-01', 'SN-SW', 'dt-switch'),
      serverDevice('d2', 'srv-2'),
      serverDevice('d-nas', 'nas-01', 'SN-NAS', 'dt-storage'),
      serverDevice('d-noname', null, 'ABC-123'), // без системного имени — подпись по серийному номеру
    ]
    const wrapper = mount(VMFormModal, { props: { vm: null } })
    const select = fieldSelect(wrapper, 'Физическое устройство')
    expect(wrapper.findAll('select').length).toBe(0)
    expect(await openAndList(select)).toEqual(['ABC-123', 'nas-01', 'srv-2', 'srv-10'])
  })

  it('«Физическое устройство (хост)»: поиск вводом текста и выбор хоста, подпись выбранного остаётся в поле', async () => {
    seedCatalogs()
    useDevicesStore().all = [serverDevice('d10', 'srv-10'), serverDevice('d2', 'srv-2'), serverDevice('d3', 'db-01')]
    const calls: { url: string; method: string; body: Record<string, unknown> | undefined }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/vms')) return jsonResponse({ id: 'vm-new', name: 'vm' }, 201)
        return jsonResponse(EMPTY_PAGE)
      }),
    )
    const wrapper = mount(VMFormModal, { props: { vm: null } })
    const select = fieldSelect(wrapper, 'Физическое устройство')
    await select.find('input').trigger('focus')
    await select.find('input').setValue('srv')
    expect(select.findAll('.ss-option').map((o) => o.text())).toEqual(['srv-2', 'srv-10'])

    await select.findAll('.ss-option')[1].trigger('mousedown')
    expect((select.find('input').element as HTMLInputElement).value).toBe('srv-10')

    await wrapper.find('input[maxlength="255"]').setValue('vm')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const create = calls.find((c) => c.method === 'POST' && c.url.endsWith('/resources/vms'))
    expect(create?.body?.physical_device_id).toBe('d10')
  })

  describe('выбранный хост, который не входит в список допустимых', () => {
    // Тип «Коммутатор» не проходит фильтр хостов, но у ВМ он мог остаться в БД (сменили тип устройства).
    const staleVm: VirtualMachine = {
      id: 'vm-1',
      name: 'app-01',
      operating_system_id: null,
      physical_device_id: 'd-sw',
      hypervisor_os_id: null,
      purpose: null,
      description: null,
    }
    function seedDevices() {
      seedCatalogs()
      useDevicesStore().all = [serverDevice('d2', 'srv-2'), serverDevice('d-sw', 'sw-core-01', 'SN-SW', 'dt-switch'), serverDevice('d10', 'srv-10')]
    }

    it('сохранённый хост вне фильтра показывается в поле с пометкой, а не пустым полем', async () => {
      seedDevices()
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => jsonResponse(EMPTY_PAGE)),
      )
      const wrapper = mount(VMFormModal, { props: { vm: staleVm } })
      await flushPromises()
      const select = fieldSelect(wrapper, 'Физическое устройство')
      expect((select.find('input').element as HTMLInputElement).value).toBe('sw-core-01 (вне списка хостов)')
      // В списке он стоит на своём месте по сортировке вместе с допустимыми хостами.
      expect(await openAndList(select)).toEqual(['srv-2', 'srv-10', 'sw-core-01 (вне списка хостов)'])
    })

    it('после выбора допустимого хоста «лишний» вариант исчезает из списка', async () => {
      seedDevices()
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => jsonResponse(EMPTY_PAGE)),
      )
      const wrapper = mount(VMFormModal, { props: { vm: staleVm } })
      await flushPromises()
      const select = fieldSelect(wrapper, 'Физическое устройство')
      await select.find('input').trigger('focus')
      await select
        .findAll('.ss-option')
        .find((o) => o.text() === 'srv-2')!
        .trigger('mousedown')
      expect(await openAndList(select)).toEqual(['srv-2', 'srv-10'])
    })

    it('допустимый хост пометки не получает; id, которого нет в реестре устройств, ничего не добавляет и не ломает форму', async () => {
      seedDevices()
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => jsonResponse(EMPTY_PAGE)),
      )
      const okVm = mount(VMFormModal, { props: { vm: { ...staleVm, physical_device_id: 'd2' } } })
      await flushPromises()
      expect((fieldSelect(okVm, 'Физическое устройство').find('input').element as HTMLInputElement).value).toBe('srv-2')
      okVm.unmount()

      const ghostVm = mount(VMFormModal, { props: { vm: { ...staleVm, physical_device_id: 'd-missing' } } })
      await flushPromises()
      const select = fieldSelect(ghostVm, 'Физическое устройство')
      expect(await openAndList(select)).toEqual(['srv-2', 'srv-10'])
    })
  })

  it('«Физическое устройство (хост)»: подсказка «нет доступных серверов» остаётся, пока в реестре нет серверов/СХД', () => {
    seedCatalogs()
    useDevicesStore().all = [serverDevice('d-sw', 'sw-core-01', 'SN-SW', 'dt-switch')]
    const wrapper = mount(VMFormModal, { props: { vm: null } })
    expect(wrapper.text()).toContain('Нет доступных серверов/СХД в реестре устройств.')
  })
})

// Пункт 3 предложений по улучшению (ревью merge/review-f06-stage2-f05-executors): вложенные списки ВМ сохраняются PUT-ом ЦЕЛИКОМ —
// сервер удаляет записи, которых нет в списке. Пока список не получен целиком, «пусто» — это «нет данных», а не «пользователь всё убрал».
describe('VMFormModal.vue — список, который не загрузился или загружен не целиком, не затирается при сохранении', () => {
  const vm: VirtualMachine = {
    id: 'vm-1',
    name: 'app-server-01',
    operating_system_id: null,
    physical_device_id: null,
    hypervisor_os_id: null,
    purpose: null,
    description: null,
  }
  const savedIp = {
    id: 'ip-1',
    owner_type: 'virtual_machine',
    owner_id: 'vm-1',
    ip_address: '10.0.0.1',
    prefix_length: 24,
    purpose: null,
    is_management: false,
  }
  type Call = { method: string; url: string; body: unknown }
  const NESTED_PUT = /\/vms\/vm-1\/(ip-addresses|open-ports|deployed-software)$/

  /** Мокает API: onList решает ответ на GET списка (по ресурсу и номеру запроса), остальное — пустые страницы и успешные PUT. */
  function stubApi(onList: (resource: string, attempt: number, url: string) => Response | Promise<Response>) {
    const calls: Call[] = []
    const attempts = new Map<string, number>()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ method, url, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'PUT' && url.endsWith('/resources/vms/vm-1')) return jsonResponse(vm)
        if (method === 'PUT') return jsonResponse({ items: [] })
        const resource = /\/resources\/(ip-addresses|open-ports|deployed-software)\b/.exec(url)?.[1]
        if (!resource) return jsonResponse(EMPTY_PAGE)
        const attempt = (attempts.get(resource) ?? 0) + 1
        attempts.set(resource, attempt)
        return onList(resource, attempt, url)
      }),
    )
    return calls
  }
  const nestedPuts = (calls: Call[]) => calls.filter((c) => c.method === 'PUT' && NESTED_PUT.test(c.url))
  const saveButton = () => document.body.querySelector('.btn-primary') as HTMLButtonElement
  const notices = () => [...document.body.querySelectorAll('.load-notice')]

  async function mountEdit() {
    const wrapper = mount(VMFormModal, { props: { vm }, attachTo: document.body })
    await flushPromises()
    return wrapper
  }

  it('загрузка IP упала: редактор IP заменён сообщением, PUT IP не уходит, остальные списки и сама ВМ сохраняются', async () => {
    const calls = stubApi((resource) => (resource === 'ip-addresses' ? jsonResponse({ detail: 'сервер недоступен' }, 503) : jsonResponse(EMPTY_PAGE)))
    const wrapper = await mountEdit()

    expect(notices()).toHaveLength(1)
    expect(notices()[0].getAttribute('data-kind')).toBe('failed')
    expect(notices()[0].textContent).toContain('IP-адресов ВМ')
    expect(wrapper.findComponent({ name: 'VmIpListEditor' }).exists()).toBe(false)
    expect(document.body.querySelector('.form-error')?.textContent).toContain('сервер недоступен')

    saveButton().click()
    await flushPromises()

    expect(nestedPuts(calls).map((c) => c.url.replace(/^.*\/vms\/vm-1/, ''))).toEqual(['/open-ports', '/deployed-software'])
    expect(calls.some((c) => c.method === 'PUT' && c.url.endsWith('/resources/vms/vm-1'))).toBe(true)
    expect(wrapper.emitted('saved')).toBeTruthy()
    wrapper.unmount()
  })

  it('«Повторить загрузку» перечитывает только упавший список и возвращает редактор; затем сохраняется то, что было в БД', async () => {
    const calls = stubApi((resource, attempt) => {
      if (resource !== 'ip-addresses') return jsonResponse(EMPTY_PAGE)
      return attempt === 1 ? jsonResponse({ detail: 'сбой' }, 503) : jsonResponse({ items: [savedIp], total: 1, offset: 0, limit: 1000 })
    })
    const wrapper = await mountEdit()
    const getsBeforeRetry = calls.filter((c) => c.method === 'GET' && c.url.includes('/resources/open-ports')).length

    ;(document.body.querySelector('[data-action="retry-load"]') as HTMLButtonElement).click()
    await flushPromises()

    expect(notices()).toHaveLength(0)
    expect(document.body.querySelector('.form-error')).toBeNull()
    expect(wrapper.findComponent({ name: 'VmIpListEditor' }).exists()).toBe(true)
    expect([...document.body.querySelectorAll('input')].map((i) => i.value)).toContain('10.0.0.1')
    // порты, загруженные с первого раза, повторно не запрашивались
    expect(calls.filter((c) => c.method === 'GET' && c.url.includes('/resources/open-ports'))).toHaveLength(getsBeforeRetry)

    saveButton().click()
    await flushPromises()
    const ipPut = nestedPuts(calls).find((c) => c.url.endsWith('/ip-addresses'))
    expect(ipPut?.body).toMatchObject({ ip_addresses: [{ id: 'ip-1', ip_address: '10.0.0.1' }] })
    wrapper.unmount()
  })

  it('«Сохранить» неактивна, пока списки грузятся; отправка формы в этот момент ничего не пишет на сервер', async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => (release = resolve))
    const calls = stubApi(async (resource) => {
      if (resource === 'ip-addresses') await gate
      return jsonResponse(resource === 'ip-addresses' ? { items: [savedIp], total: 1, offset: 0, limit: 1000 } : EMPTY_PAGE)
    })
    const wrapper = mount(VMFormModal, { props: { vm }, attachTo: document.body })
    await flushPromises()

    expect(document.body.querySelector('.loading-hint')).not.toBeNull()
    expect(saveButton().disabled).toBe(true)
    await wrapper.find('form').trigger('submit') // не через кнопку: Enter в поле формы
    await flushPromises()
    expect(calls.filter((c) => c.method !== 'GET')).toEqual([])

    release()
    await flushPromises()
    expect(saveButton().disabled).toBe(false)
    wrapper.unmount()
  })

  it('усечённый список IP: сообщение с «n из N», PUT IP не уходит (невидимые записи не удаляются)', async () => {
    const calls = stubApi((resource, _attempt, url) => {
      if (resource !== 'ip-addresses') return jsonResponse(EMPTY_PAGE)
      const offset = Number(new URL(url, 'http://localhost').searchParams.get('offset'))
      return jsonResponse({ items: offset === 0 ? [savedIp] : [], total: 2000, offset, limit: 1000 })
    })
    const wrapper = await mountEdit()

    const partial = notices().find((n) => n.getAttribute('data-kind') === 'partial')
    expect(partial?.textContent).toContain('1 из 2')
    expect(partial?.querySelector('[data-action="retry-load"]')).toBeNull() // повтор дал бы то же самое

    saveButton().click()
    await flushPromises()
    expect(nestedPuts(calls).some((c) => c.url.endsWith('/ip-addresses'))).toBe(false)
    wrapper.unmount()
  })

  it('без проблем загрузки поведение прежнее: пустой список существующей ВМ по-прежнему отправляется (пользователь всё убрал)', async () => {
    const calls = stubApi(() => jsonResponse(EMPTY_PAGE))
    const wrapper = await mountEdit()

    expect(notices()).toHaveLength(0)
    saveButton().click()
    await flushPromises()
    expect(nestedPuts(calls)).toHaveLength(3)
    wrapper.unmount()
  })
})
