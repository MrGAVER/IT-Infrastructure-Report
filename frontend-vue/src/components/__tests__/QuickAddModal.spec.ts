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

  it('fk-поле берёт опции из уже загруженного каталога стора', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['device-types'] = [{ id: 'dt-1', name: 'Сервер' }]
    catalogs.items['manufacturers'] = [{ id: 'mf-1', name: 'Dell' }]

    mount(QuickAddModal, { props: { resource: 'device-models' } })

    // п.4: fk-поле — SearchableSelect, а не нативный select; открываем список кликом по полю
    // и проверяем показанные варианты, как их увидел бы пользователь.
    const searchInputs = body().findAll('.searchable-select input')
    await searchInputs[0].trigger('focus')
    expect(body().findAll('.searchable-select')[0].text()).toContain('Сервер')
    await searchInputs[0].trigger('blur')

    await searchInputs[1].trigger('focus')
    expect(body().findAll('.searchable-select')[1].text()).toContain('Dell')
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

    // Вложенная форма закрылась сама, а её результат сразу выбран в SearchableSelect основной
    // формы — проверяем через показанную подпись (id -> label резолвится внутри SearchableSelect
    // по modelValue by поиску в options), а не через несуществующий теперь HTMLSelectElement.value.
    expect(body().findAll('.overlay')).toHaveLength(1)
    const deviceTypeInput = body().findAll('.searchable-select input')[0].element as HTMLInputElement
    expect(deviceTypeInput.value).toBe('Коммутатор')
    expect(catalogs.items['device-types']).toEqual([
      { id: 'dt-new', name: 'Коммутатор' },
      { id: 'dt-1', name: 'Сервер' },
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
    const domainInput = body().find('.searchable-select input').element as HTMLInputElement
    expect(domainInput.value).toBe('Филиал-2')
  })

  it('п.3: длинное значение в текстовом поле показывает подсказку через секунду наведения', async () => {
    vi.useFakeTimers()
    try {
      mount(QuickAddModal, { props: { resource: 'device-models' } })
      // device-models: [device_type_id (fk, SearchableSelect), manufacturer_id (fk,
      // SearchableSelect), model (text)] — берём последний текстовый input, т.к. первые два
      // input[type="text"] в DOM принадлежат поисковым полям SearchableSelect'ов, не полю "Модель".
      const textInputs = body().findAll('input[type="text"]')
      const modelInput = textInputs[textInputs.length - 1]
      Object.defineProperty(modelInput.element, 'scrollWidth', { value: 300, configurable: true })
      Object.defineProperty(modelInput.element, 'clientWidth', { value: 100, configurable: true })
      await modelInput.setValue('Очень длинное название модели устройства, которое не влезает')

      await modelInput.trigger('mouseenter')
      vi.advanceTimersByTime(1000)
      const tip = document.querySelector('.truncate-tooltip-popup')
      expect(tip?.textContent).toBe('Очень длинное название модели устройства, которое не влезает')
    } finally {
      vi.useRealTimers()
    }
  })

  it('п.4: fk-поле — SearchableSelect с поиском по подстроке, выбор опции работает', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['device-types'] = [
      { id: 'dt-1', name: 'Сервер' },
      { id: 'dt-2', name: 'Сетевой коммутатор' },
      { id: 'dt-3', name: 'Межсетевой экран' },
    ]
    catalogs.items['manufacturers'] = []

    mount(QuickAddModal, { props: { resource: 'device-models' } })
    const typeSearch = body().findAll('.searchable-select input')[0]
    await typeSearch.trigger('focus')
    await typeSearch.setValue('сетев') // без учёта регистра совпадает и с "Сетевой", и с "Межсетевой"

    const options = body().findAll('.searchable-select')[0].findAll('.ss-option')
    expect(options.map((o) => o.text())).toEqual(['Сетевой коммутатор', 'Межсетевой экран'])

    await options[0].trigger('mousedown')
    expect((typeSearch.element as HTMLInputElement).value).toBe('Сетевой коммутатор')
  })

  it('показывает сообщение, если для ресурса схема не настроена', () => {
    mount(QuickAddModal, { props: { resource: 'unknown-resource' } })
    expect(body().text()).toContain('быстрое добавление не настроено')
  })
})
