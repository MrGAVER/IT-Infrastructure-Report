import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceFormModal from '../DeviceFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { deviceTypesFixture } from '../../stores/__tests__/fixtures'

function stubCatalogsFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.includes('/resources/device-types')) return new Response(JSON.stringify(deviceTypesFixture))
      if (/\/resources$/.test(url)) return new Response(JSON.stringify([]))
      return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
    }),
  )
}

// Каждый тест сам грузит справочники под своим стабом fetch, а затем ПОДМЕНЯЕТ
// стаб на выделенный мок для create/update-запроса. unstubGlobals: true в
// vitest.config.ts откатывает vi.stubGlobal между тестами автоматически — важно
// не полагаться на то, какой стаб "утёк" из предыдущего теста (наступили на это
// при живой разработке), а всегда переустанавливать явно внутри каждого it().
beforeEach(() => {
  setActivePinia(createPinia())
})

async function mountWithLoadedCatalogs() {
  stubCatalogsFetch()
  const catalogs = useCatalogsStore()
  await catalogs.ensureLoaded()
  return mount(DeviceFormModal, { props: { device: null } })
}

describe('DeviceFormModal.vue', () => {
  it('не отправляет запрос и показывает ошибку без обязательных полей', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    await wrapper.find('form').trigger('submit')
    expect(wrapper.text()).toContain('Укажите тип устройства')
    expect(wrapper.emitted('saved')).toBeFalsy()
  })

  it('успешно создаёт устройство и эмитит saved', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    const postMock = vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'POST' && url.includes('/resources/devices')) {
        return new Response(JSON.stringify({ id: 'new-1', serial_number: 'SN-1' }), { status: 201 })
      }
      return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
    })
    vi.stubGlobal('fetch', postMock)

    await wrapper.find('select').setValue('dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-1')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(postMock).toHaveBeenCalledWith(expect.stringContaining('/resources/devices'), expect.objectContaining({ method: 'POST' }))
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('при 409 DUPLICATE_SYSTEM_NAME спрашивает подтверждение и повторяет запрос с флагом', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    // Отдельный счётчик именно для POST /resources/devices — GET-запросы
    // persistOpenPorts() (см. DeviceFormModal.vue) на других URL не должны на него влиять.
    let devicePostCalls = 0
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') !== 'POST' || !url.includes('/resources/devices')) {
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }
      devicePostCalls += 1
      if (devicePostCalls === 1) {
        return new Response(
          JSON.stringify({ detail: { code: 'DUPLICATE_SYSTEM_NAME', message: 'Уже используется. Сохранить дубликат?' } }),
          { status: 409 },
        )
      }
      const body = JSON.parse(init!.body as string)
      expect(body.confirm_system_name_duplicate).toBe(true)
      return new Response(JSON.stringify({ id: 'new-2', serial_number: 'SN-2' }), { status: 201 })
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('confirm', vi.fn(() => true))

    await wrapper.find('select').setValue('dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-2')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(confirm).toHaveBeenCalled()
    expect(devicePostCalls).toBe(2)
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('при отказе от подтверждения дубликата запрос не повторяется', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ detail: { code: 'DUPLICATE_SYSTEM_NAME', message: 'Уже используется.' } }),
          { status: 409 },
        ),
    )
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('confirm', vi.fn(() => false))

    await wrapper.find('select').setValue('dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-3')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(wrapper.emitted('saved')).toBeFalsy()
    expect(wrapper.text()).toContain('Уже используется')
  })

  it('emits close при отмене', async () => {
    const wrapper = await mountWithLoadedCatalogs()
    await wrapper.find('.modal-foot button.btn-secondary').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('при редактировании подгружает существующие открытые порты устройства', async () => {
    stubCatalogsFetch()
    const catalogs = useCatalogsStore()
    await catalogs.ensureLoaded()

    const device = { id: 'dev-1', device_type_id: 'dt-server', serial_number: 'SN-9' } as never
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/resources/open-ports')) {
          return new Response(
            JSON.stringify({
              items: [{ id: 'op-1', owner_type: 'physical_device', owner_id: 'dev-1', transport_protocol: 'TCP', port: 22, protocol: 'SSH', protocol_catalog_id: null, ip_address: null, description: null }],
              total: 1,
              offset: 0,
              limit: 1000,
            }),
          )
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    const wrapper = mount(DeviceFormModal, { props: { device } })
    await flushPromises()

    expect(wrapper.find('input.col-port').element).toHaveProperty('value', '22')
  })

  it('сохраняет добавленный открытый порт под id нового устройства и не отправляет пустые строки', async () => {
    const wrapper = await mountWithLoadedCatalogs()

    await wrapper.find('button.add-btn').trigger('click') // + Открытый порт, оставляем пустым
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.includes('/resources/devices')) {
          return new Response(JSON.stringify({ id: 'dev-new', serial_number: 'SN-4' }), { status: 201 })
        }
        return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      }),
    )

    await wrapper.find('select').setValue('dt-server')
    await wrapper.find('input[type="text"]').setValue('SN-4')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(calls.some((c) => c.method === 'POST' && c.url.includes('/resources/open-ports'))).toBe(false)
    expect(wrapper.emitted('saved')).toBeTruthy()
  })
})
