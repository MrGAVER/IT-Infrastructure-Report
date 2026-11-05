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
    mount(QuickAddModal, { props: { resource: 'manufacturers' } })
    expect(body().text()).toContain('Добавить: Производитель')
    expect(body().findAll('input[type="text"]')).toHaveLength(1)
  })

  it('не сохраняет запись без заполненного обязательного поля', async () => {
    mount(QuickAddModal, { props: { resource: 'device-types' } })
    await body().find('form').trigger('submit')

    expect(body().text()).toContain('Заполните поле «Наименование»')
  })

  it('правка "иконка вместо текстового блока в Добавить: Модель устройства": поле diagram_icon_id — DeviceIconPicker, а не текстовый input', () => {
    const catalogs = useCatalogsStore()
    catalogs.items['device-types'] = [{ id: 'dt-1', name: 'Сервер' }]
    catalogs.items['manufacturers'] = [{ id: 'mf-1', name: 'Dell' }]
    catalogs.items['diagram-icons'] = [{ id: 'icon-1', name: 'Сервер (кастом)', svg_markup: '<svg></svg>' } as never]

    mount(QuickAddModal, { props: { resource: 'device-models' } })

    // DeviceIconPicker.vue рендерит корневой .icon-picker и собственный <select> с опцией
    // "Автоматически — по категории устройства" — этого достаточно, чтобы отличить его от
    // обычного текстового <input>, в который поле проваливалось раньше (falling through в
    // общий v-else).
    expect(body().find('.icon-picker').exists()).toBe(true)
    expect(body().text()).toContain('Автоматически — по категории устройства')
    expect(body().text()).toContain('Иконка на диаграмме топологии сети')
    // DeviceIconPicker — <select>, а не текстовый <input> (в который поле проваливалось раньше,
    // falling through в общий v-else) — сам факт наличия .icon-picker .icon-select это уже
    // покрывает; здесь дополнительно убеждаемся, что внутри .icon-picker нет ничего похожего
    // на текстовое поле ввода названия иконки руками.
    expect(body().find('.icon-picker input[type="text"]').exists()).toBe(false)
    expect(body().find('.icon-picker .icon-select').exists()).toBe(true)
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
    catalogs.items['manufacturers'] = []

    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
        if (method === 'POST' && url.endsWith('/resources/manufacturers')) {
          return jsonResponse({ id: 'mfr-new', name: 'Cisco' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    const wrapper = mount(QuickAddModal, { props: { resource: 'manufacturers' } })
    await body().find('input[type="text"]').setValue('Cisco')
    await body().find('form').trigger('submit')
    await flushPromises()

    expect(calls[0].body).toEqual({ name: 'Cisco' })
    expect(wrapper.emitted('created')?.[0][0]).toEqual({ id: 'mfr-new', name: 'Cisco' })
    expect(catalogs.items['manufacturers']).toEqual([{ id: 'mfr-new', name: 'Cisco' }])
  })

  it('точечно добавляет запись, даже если каталог ещё не был загружен (не пустой массив, а undefined)', async () => {
    // Регрессия: items[key] был undefined (не []), если форма открылась раньше
    // catalogs.ensureLoaded() — точечное добавление молча пропускалось, и value без
    // соответствующего <option> в вызывающем select'е просто игнорировался браузером/jsdom.
    const catalogs = useCatalogsStore()

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/manufacturers')) {
          return jsonResponse({ id: 'mfr-new', name: 'Cisco' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    mount(QuickAddModal, { props: { resource: 'manufacturers' } })
    await body().find('input[type="text"]').setValue('Cisco')
    await body().find('form').trigger('submit')
    await flushPromises()

    expect(catalogs.items['manufacturers']).toEqual([{ id: 'mfr-new', name: 'Cisco' }])
  })

  it('вложенная кнопка "+" у fk-поля создаёт запись в её каталоге и сразу подставляет её в текущую форму', async () => {
    // п.1.1.2: у "Добавить: Модель устройства" должна быть возможность завести отсутствующий
    // "Тип устройства"/"Производителя", не закрывая форму модели.
    const catalogs = useCatalogsStore()
    catalogs.items['device-types'] = [{ id: 'dt-1', name: 'Сервер' }]
    catalogs.items['manufacturers'] = [{ id: 'mf-1', name: 'Dell' }]
    // Интеграционный фикс (слияние feature/network-topology-diagram + fix/usability-batch4):
    // category_id стал обязательным полем самого device-types (см. схему выше) — вложенной
    // форме нужен хотя бы один вариант категории, иначе её собственный submit не пройдёт.
    catalogs.items['device-categories'] = [{ id: 'cat-1', name: 'Сетевая инфраструктура' }]

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/device-types')) {
          return jsonResponse({ id: 'dt-new', name: 'Коммутатор', category_id: 'cat-1' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    mount(QuickAddModal, { props: { resource: 'device-models' } })

    const addButtons = body().findAll('button[aria-label^="Добавить:"]')
    const typeAddButton = addButtons.find((b) => b.attributes('aria-label') === 'Добавить: Тип устройства')
    expect(typeAddButton).toBeTruthy()
    await typeAddButton!.trigger('click')

    // Вложенная QuickAddModal телепортируется в тот же document.body — второй .modal-overlay поверх первого.
    expect(body().findAll('.modal-overlay')).toHaveLength(2)
    const nested = body().findAll('.modal-overlay')[1]
    await nested.find('input[type="text"]').setValue('Коммутатор')
    // Категория — обязательное fk-поле вложенной формы; выбираем единственный доступный вариант.
    await nested.find('.searchable-select input').trigger('focus')
    await nested.find('.ss-option').trigger('mousedown')
    await nested.find('form').trigger('submit')
    await flushPromises()

    // Вложенная форма закрылась сама, а её результат сразу выбран в SearchableSelect основной
    // формы — проверяем через показанную подпись (id -> label резолвится внутри SearchableSelect
    // по modelValue by поиску в options), а не через несуществующий теперь HTMLSelectElement.value.
    expect(body().findAll('.modal-overlay')).toHaveLength(1)
    const deviceTypeInput = body().findAll('.searchable-select input')[0].element as HTMLInputElement
    expect(deviceTypeInput.value).toBe('Коммутатор')
    expect(catalogs.items['device-types']).toEqual([
      { id: 'dt-new', name: 'Коммутатор', category_id: 'cat-1' },
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

    const nested = body().findAll('.modal-overlay')[1]
    await nested.find('input[type="text"]').setValue('Филиал-2')
    await nested.find('form').trigger('submit')
    await flushPromises()

    expect(body().findAll('.modal-overlay')).toHaveLength(1)
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

  it('«Добавить: Стойка»: расширенное окно, поля «Помещение», «Наименование», «Высота» идут друг под другом в одну колонку', () => {
    const catalogs = useCatalogsStore()
    catalogs.items['rooms'] = [{ id: 'room-1', name: 'Серверная комната на третьем этаже главного корпуса' }]

    mount(QuickAddModal, { props: { resource: 'racks' } })

    expect(body().find('.modal').classes()).toContain('modal-wide')
    expect(body().find('form').classes()).toContain('form-grid-single')
    const labels = body()
      .findAll('form > label.field')
      .map((l) => l.find('span').text())
    expect(labels).toEqual(['Помещение *', 'Наименование *', 'Высота, U'])
    // Ни одно поле не растянуто на две колонки — раскладку задаёт единственная колонка самой формы.
    expect(body().findAll('form > label.field-wide')).toHaveLength(0)
  })

  it('остальные формы быстрого добавления остаются в стандартном окне с двумя колонками', () => {
    mount(QuickAddModal, { props: { resource: 'manufacturers' } })

    expect(body().find('.modal').classes()).not.toContain('modal-wide')
    expect(body().find('form').classes()).not.toContain('form-grid-single')
  })

  it('показывает сообщение, если для ресурса схема не настроена', () => {
    mount(QuickAddModal, { props: { resource: 'unknown-resource' } })
    expect(body().text()).toContain('быстрое добавление не настроено')
  })
})
