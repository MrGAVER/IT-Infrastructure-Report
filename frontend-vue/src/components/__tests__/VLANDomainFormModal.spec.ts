import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import VLANDomainFormModal from '../VLANDomainFormModal.vue'
import { useDevicesStore } from '../../stores/devices'
import type { VLANDomain } from '../../api/types'

const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 1000 }

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function seedDevices() {
  const devices = useDevicesStore()
  devices.all = [
    { id: 'dev-1', system_name: 'core-sw-01', serial_number: 'SN-1' } as never,
    { id: 'dev-2', system_name: 'core-sw-02', serial_number: 'SN-2' } as never,
  ]
  devices.loaded = true
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => jsonResponse(EMPTY_PAGE)),
  )
})

describe('VLANDomainFormModal.vue', () => {
  it('при создании нового домена скрывает управление составом', async () => {
    seedDevices()
    const wrapper = mount(VLANDomainFormModal, { props: { domain: null } })
    await flushPromises()

    expect(wrapper.text()).toContain('Состав домена можно настроить после первого сохранения')
    expect(wrapper.find('.nested-editor').exists()).toBe(false)
  })

  it('не сохраняет домен без наименования', async () => {
    seedDevices()
    const wrapper = mount(VLANDomainFormModal, { props: { domain: null } })
    await wrapper.find('form').trigger('submit')

    expect(wrapper.text()).toContain('Укажите наименование домена')
  })

  it('создаёт домен с указанным устройством-источником', async () => {
    seedDevices()
    const wrapper = mount(VLANDomainFormModal, { props: { domain: null } })

    await wrapper.find('input[type="text"]').setValue('Ядро сети')
    await wrapper.find('select').setValue('dev-1')
    await wrapper.find('input[type="checkbox"]').setValue(true)

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/vlan-domains')) return jsonResponse({ id: 'dom-new' }, 201)
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const create = calls.find((c) => c.method === 'POST' && c.url.endsWith('/resources/vlan-domains'))
    expect(create?.body).toMatchObject({ name: 'Ядро сети', source_device_id: 'dev-1', auto_sync: true })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('при редактировании загружает и отображает состав домена', async () => {
    seedDevices()
    const domain: VLANDomain = { id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: 'dev-1', auto_sync: false }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/resources/vlan-domain-devices')) {
          return jsonResponse({ ...EMPTY_PAGE, items: [{ id: 'link-1', domain_id: 'dom-1', physical_device_id: 'dev-2' }] })
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()

    expect(wrapper.find('.member-row').text()).toContain('core-sw-02')
  })

  it('добавляет устройство в состав домена через POST .../members', async () => {
    seedDevices()
    const domain: VLANDomain = { id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: null, auto_sync: false }
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.includes('/vlan-domains/dom-1/members')) {
          return jsonResponse({ id: 'link-new', domain_id: 'dom-1', physical_device_id: 'dev-1' }, 201)
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()
    await wrapper.find('.add-member-row select').setValue('dev-1')
    await wrapper.find('.add-member-row button').trigger('click')
    await flushPromises()

    const call = calls.find((c) => c.method === 'POST' && c.url.includes('/members'))
    expect(call?.body).toEqual({ physical_device_id: 'dev-1' })
    expect(wrapper.find('.member-row').text()).toContain('core-sw-01')
  })

  it('убирает устройство из состава домена', async () => {
    seedDevices()
    const domain: VLANDomain = { id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: null, auto_sync: false }
    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method })
        if (url.includes('/resources/vlan-domain-devices') && method === 'GET') {
          return jsonResponse({ ...EMPTY_PAGE, items: [{ id: 'link-1', domain_id: 'dom-1', physical_device_id: 'dev-2' }] })
        }
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()
    await wrapper.find('.member-row .icon-btn.danger').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/resources/vlan-domain-devices/link-1'))).toBe(true)
    expect(wrapper.find('.member-row').exists()).toBe(false)
  })

  it('пункт 1 правки "домен VLAN": редактирование без смены устройства-источника не спрашивает подтверждение и не запускает replace-синхронизацию', async () => {
    seedDevices()
    const domain: VLANDomain = { id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: 'dev-1', auto_sync: false }
    const confirmSpy = vi.fn((_message?: string) => true)
    vi.stubGlobal('confirm', confirmSpy)
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()
    await wrapper.find('textarea').setValue('просто новое описание')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirmSpy).not.toHaveBeenCalled()
    expect(calls.some((c) => c.url.includes('/sync'))).toBe(false)
    expect(calls.some((c) => c.method === 'PUT' && c.url.endsWith('/resources/vlan-domains/dom-1'))).toBe(true)
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('пункт 1: смена устройства-источника спрашивает подтверждение и, если подтверждено, перезаписывает VLAN участников (POST .../sync с replace: true)', async () => {
    seedDevices()
    const domain: VLANDomain = { id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: 'dev-1', auto_sync: false }
    const confirmSpy = vi.fn((_message?: string) => true)
    vi.stubGlobal('confirm', confirmSpy)
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()
    await wrapper.find('select').setValue('dev-2')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(confirmSpy.mock.calls[0][0]).toContain('core-sw-02')
    expect(confirmSpy.mock.calls[0][0]).toContain('перезаписаны')
    const update = calls.find((c) => c.method === 'PUT' && c.url.endsWith('/resources/vlan-domains/dom-1'))
    expect(update?.body).toMatchObject({ source_device_id: 'dev-2' })
    const sync = calls.find((c) => c.method === 'POST' && c.url.includes('/vlan-domains/dom-1/sync'))
    expect(sync?.body).toEqual({ replace: true })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('пункт 1: отказ от подтверждения отменяет сохранение целиком — устройство-источник не меняется', async () => {
    seedDevices()
    const domain: VLANDomain = { id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: 'dev-1', auto_sync: false }
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    )
    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, method: init?.method ?? 'GET' })
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()
    await wrapper.find('select').setValue('dev-2')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(calls.some((c) => c.method === 'PUT' || (c.method === 'POST' && c.url.includes('/sync')))).toBe(false)
    expect(wrapper.emitted('saved')).toBeFalsy()
  })

  it('пункт 1: первое задание источника (было пусто) тоже спрашивает подтверждение', async () => {
    seedDevices()
    const domain: VLANDomain = { id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: null, auto_sync: false }
    const confirmSpy = vi.fn((_message?: string) => true)
    vi.stubGlobal('confirm', confirmSpy)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(EMPTY_PAGE)),
    )

    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()
    await wrapper.find('select').setValue('dev-1')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirmSpy).toHaveBeenCalledTimes(1)
  })

  it('пункт 1: снятие источника (на пусто) НЕ спрашивает подтверждение и не запускает синхронизацию — перезаписывать нечего', async () => {
    seedDevices()
    const domain: VLANDomain = { id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: 'dev-1', auto_sync: false }
    const confirmSpy = vi.fn((_message?: string) => true)
    vi.stubGlobal('confirm', confirmSpy)
    const calls: Array<{ url: string; method: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, method: init?.method ?? 'GET' })
        return jsonResponse(EMPTY_PAGE)
      }),
    )

    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()
    await wrapper.find('select').setValue('')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirmSpy).not.toHaveBeenCalled()
    expect(calls.some((c) => c.url.includes('/sync'))).toBe(false)
    expect(wrapper.emitted('saved')).toBeTruthy()
  })
})

// B-02 (ревью merge/review-r1-r2-executors): состав домена загружен не целиком — об этом сказано постоянным сообщением, а добавление
// устройств отключено (по неполному составу нельзя исключить повторное добавление). Убирать видимых участников по-прежнему можно.
describe('VLANDomainFormModal.vue — усечённый состав домена (B-02)', () => {
  const domain: VLANDomain = { id: 'dom-1', name: 'Ядро', description: null, source_device_id: null, auto_sync: false } as VLANDomain
  const link = { id: 'l-1', domain_id: 'dom-1', physical_device_id: 'dev-1' }

  /** total больше, чем отдано: на вторую страницу сервер отвечает пустой, и listAllResource возвращает truncated=true. */
  function stubMembers(total: number) {
    const calls: Array<{ method: string; url: string }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ method, url })
        if (method === 'GET' && url.includes('/resources/vlan-domain-devices')) {
          const offset = Number(new URL(url, 'http://localhost').searchParams.get('offset'))
          return jsonResponse({ items: offset === 0 ? [link] : [], total, offset, limit: 1000 })
        }
        return jsonResponse({ status: 'ok' })
      }),
    )
    return calls
  }

  it('усечённый состав: сообщение «загружено 1 из 2 000», выбор устройства и кнопка «Добавить» отключены', async () => {
    seedDevices()
    stubMembers(2000)
    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()

    const notice = wrapper.find('.load-notice')
    expect(notice.exists()).toBe(true)
    expect(notice.attributes('data-kind')).toBe('incomplete')
    expect(notice.text().replace(/\s+/g, ' ')).toContain('загружено 1 из 2 000')
    expect(notice.text()).toContain('Добавление устройств отключено')
    expect((wrapper.find('.add-member-row select').element as HTMLSelectElement).disabled).toBe(true)
    expect((wrapper.find('.add-member-row button').element as HTMLButtonElement).disabled).toBe(true)
  })

  it('усечённый состав: попытка добавить участника (в обход disabled) не отправляет запрос', async () => {
    seedDevices()
    const calls = stubMembers(2000)
    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()

    const select = wrapper.find('.add-member-row select')
    ;(select.element as HTMLSelectElement).disabled = false
    await select.setValue('dev-2')
    ;(wrapper.find('.add-member-row button').element as HTMLButtonElement).disabled = false
    await wrapper.find('.add-member-row button').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.method === 'POST' && c.url.includes('/members'))).toBe(false)
  })

  it('усечённый состав: видимого участника по-прежнему можно убрать', async () => {
    seedDevices()
    const calls = stubMembers(2000)
    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()

    await wrapper.find('.member-row button').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.method === 'DELETE' && c.url.endsWith('/resources/vlan-domain-devices/l-1'))).toBe(true)
  })

  it('полный состав: сообщения нет, добавление доступно', async () => {
    seedDevices()
    stubMembers(1)
    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()

    expect(wrapper.find('.load-notice').exists()).toBe(false)
    expect((wrapper.find('.add-member-row select').element as HTMLSelectElement).disabled).toBe(false)
  })

  it('смена домена сбрасывает признак усечения предыдущего', async () => {
    seedDevices()
    stubMembers(2000)
    const wrapper = mount(VLANDomainFormModal, { props: { domain } })
    await flushPromises()
    expect(wrapper.find('.load-notice').exists()).toBe(true)

    stubMembers(1)
    await wrapper.setProps({ domain: { ...domain, id: 'dom-2', name: 'Периметр' } as VLANDomain })
    await flushPromises()

    expect(wrapper.find('.load-notice').exists()).toBe(false)
  })
})
