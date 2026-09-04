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
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        expect(init?.method).toBe('POST')
        expect(url).toContain('/resources/device-types')
        expect(JSON.parse(init!.body as string)).toEqual({ name: 'Коммутатор' })
        return jsonResponse({ id: 'dt-new', name: 'Коммутатор' }, 201)
      }),
    )
    const wrapper = mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: null } })
    await body().find('input[type="text"]').setValue('Коммутатор')
    await body().find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.emitted('saved')?.[0]).toEqual([{ id: 'dt-new', name: 'Коммутатор' }])
  })

  it('редактирование: PUT на ресурс/id, emit saved', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        expect(init?.method).toBe('PUT')
        expect(url).toContain('/resources/device-types/dt-1')
        expect(JSON.parse(init!.body as string)).toEqual({ name: 'Сервер (переименован)' })
        return jsonResponse({ id: 'dt-1', name: 'Сервер (переименован)' })
      }),
    )
    const wrapper = mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: { id: 'dt-1', name: 'Сервер' } } })
    await body().find('input[type="text"]').setValue('Сервер (переименован)')
    await body().find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.emitted('saved')?.[0]).toEqual([{ id: 'dt-1', name: 'Сервер (переименован)' }])
  })

  it('ошибка сохранения показывается в форме, а не проглатывается', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'Запись с таким именем уже существует' }, 409)))
    mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: null } })
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

  it('кнопка "Закрыть" эмитит close без сохранения', async () => {
    const wrapper = mount(CatalogRecordFormModal, { props: { resource: 'device-types', item: null } })
    await body().find('button[aria-label="Закрыть"]').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('показывает сообщение, если для ресурса схема не настроена', () => {
    mount(CatalogRecordFormModal, { props: { resource: 'unknown-resource', item: null } })
    expect(body().text()).toContain('форма не настроена')
  })
})
