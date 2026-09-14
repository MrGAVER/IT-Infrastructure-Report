import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import CatalogRecordFormModal from '../CatalogRecordFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

// Телепортируется в document.body — тот же принцип, что в QuickAddModal.spec.ts.
function body(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
})

describe('CatalogRecordFormModal.vue', () => {
  it('режим создания: заголовок "Добавить: X", поля пустые', () => {
    mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: null } })
    expect(body().text()).toContain('Добавить: Тип устройства')
    expect((body().find('input[type="text"]').element as HTMLInputElement).value).toBe('')
    expect(body().text()).not.toContain('Удалить')
  })

  it('режим редактирования: заголовок "Редактировать: X", поля предзаполнены из item, есть кнопка "Удалить"', () => {
    mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: { id: 'dt-1', name: 'Сервер' } } })
    expect(body().text()).toContain('Редактировать: Тип устройства')
    expect((body().find('input[type="text"]').element as HTMLInputElement).value).toBe('Сервер')
    expect(body().text()).toContain('Удалить')
  })

  it('не сохраняет запись без заполненного обязательного поля', async () => {
    mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: null } })
    await body().find('form').trigger('submit')
    expect(body().text()).toContain('Заполните поле «Наименование»')
  })

  it('создание: POST на ресурс, emit saved с ответом сервера', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['device-categories'] = [{ id: 'cat-1', name: 'Сетевая инфраструктура' }]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        expect(init?.method).toBe('POST')
        expect(url).toContain('/resources/device-types')
        expect(JSON.parse(init!.body as string)).toEqual({ name: 'Коммутатор', category_id: 'cat-1' })
        return jsonResponse({ id: 'dt-new', name: 'Коммутатор', category_id: 'cat-1' }, 201)
      }),
    )
    const wrapper = mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: null } })
    await body().find('input[type="text"]').setValue('Коммутатор')
    // category_id — обязательное fk-поле (интеграционный фикс слияния с диаграммой топологии).
    await body().find('.searchable-select input').trigger('focus')
    await body().find('.ss-option').trigger('mousedown')
    await body().find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.emitted('saved')?.[0]).toEqual([{ id: 'dt-new', name: 'Коммутатор', category_id: 'cat-1' }])
  })

  it('редактирование: PUT на ресурс/id, emit saved', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['device-categories'] = [{ id: 'cat-1', name: 'Сетевая инфраструктура' }]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        expect(init?.method).toBe('PUT')
        expect(url).toContain('/resources/device-types/dt-1')
        expect(JSON.parse(init!.body as string)).toEqual({ name: 'Сервер (переименован)', category_id: 'cat-1' })
        return jsonResponse({ id: 'dt-1', name: 'Сервер (переименован)', category_id: 'cat-1' })
      }),
    )
    const wrapper = mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: { id: 'dt-1', name: 'Сервер', category_id: 'cat-1' } } })
    await body().find('input[type="text"]').setValue('Сервер (переименован)')
    await body().find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.emitted('saved')?.[0]).toEqual([{ id: 'dt-1', name: 'Сервер (переименован)', category_id: 'cat-1' }])
  })

  it('ошибка сохранения показывается в форме, а не проглатывается', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['device-categories'] = [{ id: 'cat-1', name: 'Сетевая инфраструктура' }]
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Запись с таким именем уже существует' }, 409)))
    mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: { id: 'dt-1', name: 'Сервер', category_id: 'cat-1' } } })
    await body().find('input[type="text"]').setValue('Сервер')
    await body().find('form').trigger('submit')
    await flushPromises()

    expect(body().text()).toContain('Запись с таким именем уже существует')
  })

  it('удаление: подтверждение confirm(), DELETE на ресурс/id, emit deleted', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        expect(init?.method).toBe('DELETE')
        expect(url).toContain('/resources/device-types/dt-1')
        return jsonResponse({ status: 'deleted', id: 'dt-1' })
      }),
    )
    const wrapper = mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: { id: 'dt-1', name: 'Сервер' } } })
    const deleteButton = body()
      .findAll('button')
      .find((b) => b.text() === 'Удалить')!
    await deleteButton.trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalled()
    expect(wrapper.emitted('deleted')?.[0]).toEqual(['dt-1'])
  })

  it('отказ от подтверждения удаления не отправляет запрос', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false))
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: { id: 'dt-1', name: 'Сервер' } } })
    const deleteButton = body()
      .findAll('button')
      .find((b) => b.text() === 'Удалить')!
    await deleteButton.trigger('click')

    expect(fetchMock).not.toHaveBeenCalled()
    expect(wrapper.emitted('deleted')).toBeFalsy()
  })

  it('ошибка удаления (например, запись используется в других записях) показывается в форме', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Запись используется в 3 моделях устройств' }, 409)))
    const wrapper = mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: { id: 'dt-1', name: 'Сервер' } } })
    const deleteButton = body()
      .findAll('button')
      .find((b) => b.text() === 'Удалить')!
    await deleteButton.trigger('click')
    await flushPromises()

    expect(body().text()).toContain('Запись используется в 3 моделях устройств')
    expect(wrapper.emitted('deleted')).toBeFalsy()
  })

  it('fk-поле — SearchableSelect с опциями из уже загруженного каталога', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['os-categories'] = [{ id: 'cat-1', name: 'Серверные ОС' }]
    mount(CatalogRecordFormModal, { props: { resource: 'operating-systems', item: null } })

    await body().find('.searchable-select input').trigger('focus')
    expect(body().find('.searchable-select').text()).toContain('Серверные ОС')
  })

  it('self-referencing fk (departments.parent_id): при редактировании исключает саму запись из списка родителей', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['departments'] = [
      { id: 'dep-1', name: 'Дирекция' },
      { id: 'dep-2', name: 'ИТ-отдел' },
    ]
    mount(CatalogRecordFormModal, { props: { resource: 'departments', item: { id: 'dep-2', name: 'ИТ-отдел' } } })

    await body().find('.searchable-select input').trigger('focus')
    const optionsText = body().find('.searchable-select').text()
    expect(optionsText).toContain('Дирекция')
    expect(optionsText).not.toContain('ИТ-отдел')
  })

  it('self-referencing fk (departments.parent_id): при создании показывает все существующие подразделения без исключений', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['departments'] = [
      { id: 'dep-1', name: 'Дирекция' },
      { id: 'dep-2', name: 'ИТ-отдел' },
    ]
    mount(CatalogRecordFormModal, { props: { resource: 'departments', item: null } })

    await body().find('.searchable-select input').trigger('focus')
    const optionsText = body().find('.searchable-select').text()
    expect(optionsText).toContain('Дирекция')
    expect(optionsText).toContain('ИТ-отдел')
  })

  it('кнопка "Закрыть" эмитит close без сохранения', async () => {
    const wrapper = mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: null } })
    await body().find('button[aria-label="Закрыть"]').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('показывает сообщение, если для ресурса схема не настроена', () => {
    mount(CatalogRecordFormModal, { props: { resource: 'unknown-resource', item: null } })
    expect(body().text()).toContain('форма не настроена')
  })

  describe('device-models: иконка на диаграмме (раздел 11/13 ТЗ)', () => {
    it('показывает пункт выбора иконки без дублирования подписи', () => {
      mount(CatalogRecordFormModal, { props: { resource: 'device-models', item: null } })
      expect(body().find('.icon-picker').exists()).toBe(true)
      // .text(), не .html(): у CatalogRecordFormModal.vue в шаблоне есть поясняющий HTML-
      // комментарий с той же фразой для документации — .html() засчитал бы и его как "второе"
      // вхождение, хотя реально рендерится только один видимый заголовок поля.
      // Заголовок поля рендерит только сам DeviceIconPicker — внешний <span> схемы для этого
      // типа поля намеренно подавлен (см. CatalogRecordFormModal.vue), иначе подпись дублировалась.
      const matches = body().text().match(/Иконка на диаграмме/g) ?? []
      expect(matches).toHaveLength(1)
    })

    it('при редактировании подставляет уже выбранную иконку модели', () => {
      const catalogs = useCatalogsStore()
      catalogs.items['diagram-icons'] = [{ id: 'icon-1', name: 'Cisco 2960', svg_markup: '<svg/>' }]
      mount(CatalogRecordFormModal, {
        props: { resource: 'device-models', item: { id: 'model-1', device_type_id: 'dt-1', manufacturer_id: 'mf-1', model: 'Catalyst', diagram_icon_id: 'icon-1' } },
      })
      const select = body().find('.icon-select')
      expect((select.element as HTMLSelectElement).value).toBe('icon-1')
    })

    /** device-models требует ещё 2 обязательных fk-поля (Тип устройства/Производитель) до
     * "Модели" — без них submit() останавливается на валидации раньше, чем дойдёт до fetch. Тот
     * же приём (focus -> mousedown по .ss-option), что уже используется для SearchableSelect в
     * DeviceFormModal.spec.ts. */
    async function fillRequiredFkFields(catalogs: ReturnType<typeof useCatalogsStore>) {
      catalogs.items['device-types'] = [{ id: 'dt-1', name: 'Коммутатор L2' }]
      catalogs.items['manufacturers'] = [{ id: 'mf-1', name: 'Cisco' }]
      const selects = body().findAll('.searchable-select input')
      await selects[0].trigger('focus')
      await body().findAll('.searchable-select')[0].find('.ss-option').trigger('mousedown')
      await selects[1].trigger('focus')
      await body().findAll('.searchable-select')[1].find('.ss-option').trigger('mousedown')
    }

    it('выбор своей иконки в форме модели устройства сохраняет diagram_icon_id в payload сохранения', async () => {
      const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/device-models')) {
          return jsonResponse({ id: 'model-new' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      })
      vi.stubGlobal('fetch', fetchMock)
      const catalogs = useCatalogsStore()
      catalogs.items['diagram-icons'] = [{ id: 'icon-1', name: 'Cisco 2960', svg_markup: '<svg/>' }]

      mount(CatalogRecordFormModal, { props: { resource: 'device-models', item: null } })
      await fillRequiredFkFields(catalogs)
      // Индекс 2: до поля "Модель" в DOM идут 2 поисковых input SearchableSelect (Тип/
      // Производитель) — тот же порядок, что уже задокументирован в DeviceFormModal.spec.ts.
      await body().findAll('input[type="text"]')[2].setValue('Catalyst 2960')
      await body().find('.icon-select').setValue('icon-1')
      await body().find('form').trigger('submit')
      await flushPromises()

      const postCall = fetchMock.mock.calls.find(([u, init]) => (init?.method ?? 'GET') === 'POST' && (u as string).endsWith('/resources/device-models'))
      expect(postCall).toBeTruthy()
      const payload = JSON.parse((postCall![1] as RequestInit).body as string)
      expect(payload.diagram_icon_id).toBe('icon-1')
    })

    it('пустой выбор иконки (авто по категории) сохраняет diagram_icon_id как null', async () => {
      const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/device-models')) {
          return jsonResponse({ id: 'model-new' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      })
      vi.stubGlobal('fetch', fetchMock)
      const catalogs = useCatalogsStore()

      mount(CatalogRecordFormModal, { props: { resource: 'device-models', item: null } })
      await fillRequiredFkFields(catalogs)
      await body().findAll('input[type="text"]')[2].setValue('Без своей иконки')
      await body().find('form').trigger('submit')
      await flushPromises()

      const postCall = fetchMock.mock.calls.find(([u, init]) => (init?.method ?? 'GET') === 'POST' && (u as string).endsWith('/resources/device-models'))
      expect(postCall).toBeTruthy()
      const payload = JSON.parse((postCall![1] as RequestInit).body as string)
      expect(payload.diagram_icon_id).toBeNull()
    })
  })
})
