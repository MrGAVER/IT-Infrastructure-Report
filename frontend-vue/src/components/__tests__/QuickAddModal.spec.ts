import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import QuickAddModal from '../QuickAddModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

// QuickAddModal.vue телепортируется в document.body (иначе получился бы <form> внутри <form>
// вызывающего компонента — HTML не допускает вложенные формы, см. комментарий в самом
// компоненте), поэтому mount()'нутый wrapper его не содержит — работаем через body напрямую.
function body(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
})

describe('QuickAddModal.vue', () => {
  it('строит форму по схеме простого справочника (только текстовое поле)', () => {
    mount(QuickAddModal, { props: { resource: 'device-types' } })
    expect(body().text()).toContain('Добавить: Тип устройства')
    expect(body().findAll('input[type="text"]')).toHaveLength(1)
  })

  it('не сохраняет запись без заполненного обязательного поля', async () => {
    mount(QuickAddModal, { props: { resource: 'device-types' } })
    await body().find('form').trigger('submit')

    expect(body().text()).toContain('Заполните поле «Наименование»')
  })

  it('fk-поле берёт опции из уже загруженного каталога стора', () => {
    const catalogs = useCatalogsStore()
    catalogs.items['device-types'] = [{ id: 'dt-1', name: 'Сервер' }]
    catalogs.items['manufacturers'] = [{ id: 'mf-1', name: 'Dell' }]

    mount(QuickAddModal, { props: { resource: 'device-models' } })

    const selects = body().findAll('select')
    expect(selects[0].text()).toContain('Сервер')
    expect(selects[1].text()).toContain('Dell')
  })

  it('сохраняет запись, эмитит created и точечно добавляет её в каталог стора', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['device-types'] = []

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/device-types')) {
          return jsonResponse({ id: 'dt-new', name: 'Маршрутизатор' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    const wrapper = mount(QuickAddModal, { props: { resource: 'device-types' } })
    await body().find('input[type="text"]').setValue('Маршрутизатор')
    await body().find('form').trigger('submit')
    await flushPromises()

    expect(calls[0].body).toEqual({ name: 'Маршрутизатор' })
    expect(wrapper.emitted('created')?.[0][0]).toEqual({ id: 'dt-new', name: 'Маршрутизатор' })
    expect(catalogs.items['device-types']).toEqual([{ id: 'dt-new', name: 'Маршрутизатор' }])
  })

  it('точечно добавляет запись, даже если каталог ещё не был загружен (не пустой массив, а undefined)', async () => {
    // Регрессия: items[key] был undefined (не []), если форма открылась раньше
    // catalogs.ensureLoaded() — точечное добавление молча пропускалось, и value без
    // соответствующего <option> в вызывающем select'е просто игнорировался браузером/jsdom.
    const catalogs = useCatalogsStore()

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/device-types')) {
          return jsonResponse({ id: 'dt-new', name: 'Маршрутизатор' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    mount(QuickAddModal, { props: { resource: 'device-types' } })
    await body().find('input[type="text"]').setValue('Маршрутизатор')
    await body().find('form').trigger('submit')
    await flushPromises()

    expect(catalogs.items['device-types']).toEqual([{ id: 'dt-new', name: 'Маршрутизатор' }])
  })

  it('показывает сообщение, если для ресурса схема не настроена', () => {
    mount(QuickAddModal, { props: { resource: 'unknown-resource' } })
    expect(body().text()).toContain('быстрое добавление не настроено')
  })
})
