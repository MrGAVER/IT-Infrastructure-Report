import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PortConfigReviewModal from '../PortConfigReviewModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useToast } from '../../composables/useToast'
import type { Connection } from '../../api/types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function connection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: 'c-1',
    source_interface_id: 'if-srv',
    destination_interface_id: 'if-sw',
    connection_type_id: 'ct-1',
    is_active: true,
    description: null,
    source_device_name: 'srv-01',
    source_interface_name: 'idrac',
    destination_device_name: 'sw-01',
    destination_interface_name: 'Gi0/5',
    connection_type_name: 'Медь',
    source_port_role: 'management',
    destination_port_role: 'data',
    port_config_status: 'mismatch',
    ...overrides,
  }
}

interface Call { url: string; method: string; body?: Record<string, unknown> }
let calls: Call[]

function stubApi(handler: (call: Call) => Response | undefined = () => undefined) {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const call: Call = { url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body as string) : undefined }
      calls.push(call)
      return handler(call) ?? jsonResponse({ items: [], total: 0, offset: 0, limit: 1000, summary: { total: 0, active: 0, inactive: 0, mismatch: 0, approved: 0 } })
    }),
  )
}

function mountModal(conn: Connection) {
  return mount(PortConfigReviewModal, { props: { connection: conn } })
}

// Страница дашборда (/api/v1/connections?…) и общий кэш (/api/v1/resources/connections?…) — разные запросы.
const pageRequests = () => calls.filter((c) => c.method === 'GET' && /\/api\/v1\/connections\?/.test(c.url))
const cacheRequests = () => calls.filter((c) => c.method === 'GET' && c.url.includes('/resources/connections'))

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  useToast().toasts.splice(0)
  stubApi()
})

describe('PortConfigReviewModal.vue', () => {
  it('показывает обе стороны подключения с ролями портов и предупреждением о расхождении', () => {
    const wrapper = mountModal(connection())

    expect(wrapper.text()).toContain('srv-01')
    expect(wrapper.text()).toContain('idrac')
    expect(wrapper.find('[data-side="source"]').text()).toBe('Управление активами')
    expect(wrapper.find('[data-side="destination"]').text()).toBe('Передача данных')
    expect(wrapper.find('.status.warn').exists()).toBe(true)
  })

  it('при расхождении предлагает одобрить или выровнять любой из портов, но не отзывать', () => {
    const wrapper = mountModal(connection())

    expect(wrapper.find('[data-action="approve"]').exists()).toBe(true)
    expect(wrapper.find('[data-action="keep-source"]').text()).toContain('Порту «Gi0/5» задать роль как у «idrac»')
    expect(wrapper.find('[data-action="keep-destination"]').text()).toContain('Порту «idrac» задать роль как у «Gi0/5»')
    expect(wrapper.find('[data-action="revoke"]').exists()).toBe(false)
  })

  it('«Одобрить» отправляет id подключения, перечитывает страницу и кэш и закрывает модалку', async () => {
    stubApi((call) =>
      call.url.endsWith('/connections/port-config/approve')
        ? jsonResponse({ items: [connection({ port_config_status: 'approved' })], skipped_ids: [], approved_count: 1 })
        : undefined,
    )
    const wrapper = mountModal(connection())

    await wrapper.find('[data-action="approve"]').trigger('click')
    await flushPromises()

    expect(calls.find((c) => c.url.endsWith('/connections/port-config/approve'))!.body).toEqual({ connection_ids: ['c-1'] })
    expect(pageRequests()).toHaveLength(1)
    expect(cacheRequests()).toHaveLength(1)
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(useToast().toasts.some((t) => t.type === 'success')).toBe(true)
  })

  it('для одобренного расхождения показывает «Отозвать одобрение»; после отзыва снова предлагает одобрить (даже если строки уже нет на странице)', async () => {
    stubApi((call) => (call.method === 'DELETE' ? jsonResponse(connection({ port_config_status: 'mismatch' })) : undefined))
    const wrapper = mountModal(connection({ port_config_status: 'approved' }))

    expect(wrapper.find('.status.approved').exists()).toBe(true)
    expect(wrapper.find('[data-action="approve"]').exists()).toBe(false)

    await wrapper.find('[data-action="revoke"]').trigger('click')
    await flushPromises()

    expect(calls.find((c) => c.method === 'DELETE')!.url).toContain('/connections/c-1/port-config/approval')
    // Страница после отзыва перечитана пустой (строка не подходит под фильтр), но окно показывает
    // актуальную запись из ответа сервера, а не стёртую строку.
    expect(pageRequests()).toHaveLength(1)
    expect(wrapper.emitted('close')).toBeUndefined() // модалка остаётся открытой, статус обновился
    expect(wrapper.find('[data-action="approve"]').exists()).toBe(true)
  })

  it('«Порту назначения задать роль как у источника» меняет порт назначения, обновляет кэш и перечитывает подключения', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = [{ id: 'if-sw', name: 'Gi0/5', physical_device_id: 'dev-sw', is_management: false, is_data_transfer: true }]
    stubApi((call) => {
      if (call.method === 'PUT' && call.url.includes('/interfaces/if-sw/port-role')) {
        return jsonResponse({ id: 'if-sw', name: 'Gi0/5', physical_device_id: 'dev-sw', is_management: true, is_data_transfer: false })
      }
      return undefined
    })
    const wrapper = mountModal(connection())

    await wrapper.find('[data-action="keep-source"]').trigger('click')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT')!
    expect(put.body).toEqual({ is_management: true, is_data_transfer: false })
    expect(catalogs.items['interfaces'][0]).toMatchObject({ is_management: true, is_data_transfer: false })
    expect(pageRequests()).toHaveLength(1)
    expect(cacheRequests()).toHaveLength(1)
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('«Порту источника задать роль как у назначения» меняет порт источника', async () => {
    stubApi((call) =>
      call.method === 'PUT' ? jsonResponse({ id: 'if-srv', name: 'idrac', physical_device_id: 'dev-srv', is_management: false, is_data_transfer: true }) : undefined,
    )
    const wrapper = mountModal(connection())

    await wrapper.find('[data-action="keep-destination"]').trigger('click')
    await flushPromises()

    const put = calls.find((c) => c.method === 'PUT')!
    expect(put.url).toContain('/interfaces/if-srv/port-role')
    expect(put.body).toEqual({ is_management: false, is_data_transfer: true })
  })

  it('ошибка API показывается в модалке, модалка остаётся открытой, кнопки снова доступны', async () => {
    stubApi((call) => (call.url.endsWith('/connections/port-config/approve') ? jsonResponse({ detail: 'Подключение не найдено: c-1' }, 404) : undefined))
    const wrapper = mountModal(connection())

    await wrapper.find('[data-action="approve"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('.form-error').text()).toContain('Подключение не найдено')
    expect(wrapper.emitted('close')).toBeUndefined()
    expect((wrapper.find('[data-action="approve"]').element as HTMLButtonElement).disabled).toBe(false)
  })

  it('если роли уже совпадают, действий по расхождению нет — только сообщение', () => {
    const wrapper = mountModal(connection({ destination_port_role: 'management', port_config_status: 'ok' }))

    expect(wrapper.text()).toContain('Роли портов совпадают')
    expect(wrapper.find('[data-action]').exists()).toBe(false)
  })
})
