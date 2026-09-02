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

  it('вложенная кнопка "+" у fk-поля создаёт запись в её каталоге и сразу подставляет её в текущую форму', async () => {
    // п.1.1.2: у "Добавить: Модель устройства" должна быть возможность завести отсутствующий
    // "Тип устройства"/"Производителя", не закрывая форму модели.
    const catalogs = useCatalogsStore()
    catalogs.items['device-types'] = [{ id: 'dt-1', name: 'Сервер' }]
    catalogs.items['manufacturers'] = [{ id: 'mf-1', name: 'Dell' }]

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/device-types')) {
          return jsonResponse({ id: 'dt-new', name: 'Коммутатор' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    mount(QuickAddModal, { props: { resource: 'device-models' } })

    const addButtons = body().findAll('button[aria-label^="Добавить:"]')
    const typeAddButton = addButtons.find((b) => b.attributes('aria-label') === 'Добавить: Тип устройства')
    expect(typeAddButton).toBeTruthy()
    await typeAddButton!.trigger('click')

    // Вложенная QuickAddModal телепортируется в тот же document.body — второй .overlay поверх первого.
    expect(body().findAll('.overlay')).toHaveLength(2)
    const nested = body().findAll('.overlay')[1]
    await nested.find('input[type="text"]').setValue('Коммутатор')
    await nested.find('form').trigger('submit')
    await flushPromises()

    // Вложенная форма закрылась сама, а её результат сразу выбран в select'е основной формы.
    expect(body().findAll('.overlay')).toHaveLength(1)
    const deviceTypeSelect = body().findAll('select')[0].element as HTMLSelectElement
    expect(deviceTypeSelect.value).toBe('dt-new')
    expect(catalogs.items['device-types']).toEqual([
      { id: 'dt-1', name: 'Сервер' },
      { id: 'dt-new', name: 'Коммутатор' },
    ])
  })

  it('поле без nestedQuickAdd (например, "Модель") не получает кнопку "+"', () => {
    mount(QuickAddModal, { props: { resource: 'device-models' } })
    expect(body().findAll('button[aria-label^="Добавить:"]')).toHaveLength(2) // только тип + производитель
  })

  it('вложенная кнопка "+" у "Добавить: VLAN" позволяет завести Домен VLAN, не закрывая форму', async () => {
    // п.1.5: та же вложенная кнопка "+", что у device-models, но необязательное fk-поле —
    // отдельно проверяем, что схема не требует domain_id для сохранения самого VLAN.
    const catalogs = useCatalogsStore()
    catalogs.items['vlan-domains'] = []

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/vlan-domains')) {
          return jsonResponse({ id: 'dom-new', name: 'Филиал-2' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    mount(QuickAddModal, { props: { resource: 'vlans' } })

    const domainAddButton = body()
      .findAll('button[aria-label^="Добавить:"]')
      .find((b) => b.attributes('aria-label') === 'Добавить: Домен VLAN')
    expect(domainAddButton).toBeTruthy()
    await domainAddButton!.trigger('click')

    const nested = body().findAll('.overlay')[1]
    await nested.find('input[type="text"]').setValue('Филиал-2')
    await nested.find('form').trigger('submit')
    await flushPromises()

    expect(body().findAll('.overlay')).toHaveLength(1)
    const domainSelect = body()
      .findAll('select')
      .find((s) => s.find('option[value="dom-new"]').exists())
    expect((domainSelect!.element as HTMLSelectElement).value).toBe('dom-new')
  })

  it('показывает сообщение, если для ресурса схема не настроена', () => {
    mount(QuickAddModal, { props: { resource: 'unknown-resource' } })
    expect(body().text()).toContain('быстрое добавление не настроено')
  })
})
