import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import OtherCatalogsView from '../OtherCatalogsView.vue'
import CatalogRecordFormModal from '../../components/CatalogRecordFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import { useDevicesStore } from '../../stores/devices'
import { useToast } from '../../composables/useToast'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

/** reload() дёргает все 21 каталог + /resources + protocol-port-catalog одним пакетом (см.
 * stores/catalogs.ts) — для тестов, где reload() вызывается (после сохранения/удаления), нужен
 * catch-all стаб, отвечающий пустым списком на любой URL; сам факт корректного round-trip'а
 * данных уже покрыт стором catalogs отдельно, здесь важно только что view вызывает reload(). */
function stubCatalogsReload() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/resources')) return jsonResponse([])
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
    }),
  )
}

beforeEach(() => {
  setActivePinia(createPinia())
})

function seedCatalogs() {
  const catalogs = useCatalogsStore()
  catalogs.items['device-types'] = [
    { id: 'dt-1', name: 'Сервер' },
    { id: 'dt-2', name: 'Коммутатор' },
  ]
  catalogs.items['manufacturers'] = [{ id: 'mf-1', name: 'Dell' }]
  catalogs.protocolPortCatalog = [{ id: 'pp-1', port: 443, protocol_type: 'HTTPS', description: '' }]
  catalogs.loaded = true
  // OtherCatalogsView.vue теперь дожидается и devicesStore.ensureLoaded() (нужен для
  // отображения/выбора "Физическое устройство" у crypto-protection-means) — помечаем
  // предзагруженным, чтобы тесты этого файла проверяли поведение самого view, а не факт
  // дополнительного сетевого запроса к /devices при монтировании.
  useDevicesStore().loaded = true
  return catalogs
}

describe('OtherCatalogsView.vue', () => {
  it('по умолчанию выбран первый справочник списка ("Тип устройства"), показаны его записи', async () => {
    seedCatalogs()
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()

    expect(wrapper.find('.catalog-item.active').text()).toContain('Тип устройства')
    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('Сервер')
  })

  it('счётчик записей у каждого справочника в списке соответствует количеству загруженных записей', async () => {
    seedCatalogs()
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()

    const deviceTypesItem = wrapper.findAll('.catalog-item').find((i) => i.text().includes('Тип устройства'))!
    expect(deviceTypesItem.find('.count').text()).toBe('2')
    const manufacturersItem = wrapper.findAll('.catalog-item').find((i) => i.text().includes('Производитель'))!
    expect(manufacturersItem.find('.count').text()).toBe('1')
  })

  it('клик по другому справочнику в списке переключает содержимое таблицы', async () => {
    seedCatalogs()
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()

    await wrapper
      .findAll('.catalog-item')
      .find((i) => i.text().includes('Производитель'))!
      .trigger('click')
    expect(wrapper.find('.catalog-item.active').text()).toContain('Производитель')
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.find('tbody').text()).toContain('Dell')
  })

  describe('проп catalog (переход по ссылке с дашборда)', () => {
    it('открывает справочник, заданный пропом, а не первый в списке', async () => {
      const catalogs = seedCatalogs()
      catalogs.items['software-assets'] = [{ id: 'sa-1', name: 'PostgreSQL' } as never]
      const wrapper = mount(OtherCatalogsView, { props: { catalog: 'software-assets' } })
      await flushPromises()

      expect(wrapper.find('.catalog-item.active').text()).toContain('Программный актив')
      expect(wrapper.find('tbody').text()).toContain('PostgreSQL')
    })

    it('неизвестное значение игнорируется: открывается первый справочник', async () => {
      seedCatalogs()
      const wrapper = mount(OtherCatalogsView, { props: { catalog: 'no-such-catalog' } })
      await flushPromises()

      expect(wrapper.find('.catalog-item.active').text()).toContain('Тип устройства')
    })

    it('смена пропа на уже открытом экране переключает справочник; неизвестное значение выбор не сбрасывает', async () => {
      seedCatalogs()
      const wrapper = mount(OtherCatalogsView, { props: { catalog: 'manufacturers' } })
      await flushPromises()
      expect(wrapper.find('.catalog-item.active').text()).toContain('Производитель')

      await wrapper.setProps({ catalog: 'device-types' })
      expect(wrapper.find('.catalog-item.active').text()).toContain('Тип устройства')

      await wrapper.setProps({ catalog: 'bogus' })
      expect(wrapper.find('.catalog-item.active').text()).toContain('Тип устройства')
    })
  })

  it('справочник без записей показывает пустое состояние вместо таблицы', async () => {
    const catalogs = useCatalogsStore()
    catalogs.loaded = true // всё остальное — пустые массивы по умолчанию
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()

    expect(wrapper.find('table').exists()).toBe(false)
    expect(wrapper.text()).toContain('Записей пока нет')
  })

  it('protocol-port-catalog (без поля name) рендерится по собственным полям — порт/протокол', async () => {
    const catalogs = seedCatalogs()
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()

    await wrapper
      .findAll('.catalog-item')
      .find((i) => i.text().includes('Протокол / порт'))!
      .trigger('click')
    expect(wrapper.find('tbody').text()).toContain('443')
    expect(wrapper.find('tbody').text()).toContain('HTTPS')
    expect(catalogs.protocolPortCatalog).toHaveLength(1) // не мутировали стор при рендере
  })

  it('fk-поле в таблице показывает имя связанной записи, а не сырой id', async () => {
    const catalogs = seedCatalogs()
    catalogs.items['os-categories'] = [{ id: 'cat-1', name: 'Серверные ОС' }]
    catalogs.items['operating-systems'] = [{ id: 'os-1', name: 'Astra Linux', category_id: 'cat-1' } as never]
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()

    await wrapper
      .findAll('.catalog-item')
      .find((i) => i.text().includes('Операционная система'))!
      .trigger('click')
    expect(wrapper.find('tbody').text()).toContain('Серверные ОС')
    expect(wrapper.find('tbody').text()).not.toContain('cat-1')
  })

  it('"Добавить" открывает модалку в режиме создания (item = null)', async () => {
    seedCatalogs()
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()

    expect(wrapper.findComponent(CatalogRecordFormModal).exists()).toBe(false)
    await wrapper.find('.content-head button').trigger('click')

    const modal = wrapper.findComponent(CatalogRecordFormModal)
    expect(modal.exists()).toBe(true)
    expect(modal.props('item')).toBeNull()
    expect(modal.props('resource')).toBe('device-types')
  })

  it('клик по "Редактировать" в строке открывает модалку с этой записью', async () => {
    seedCatalogs()
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()

    await wrapper.find('tbody tr .icon-btn').trigger('click')
    const modal = wrapper.findComponent(CatalogRecordFormModal)
    expect(modal.props('item')).toEqual({ id: 'dt-1', name: 'Сервер' })
  })

  it('сохранение в модалке закрывает её, перезагружает каталоги и показывает уведомление', async () => {
    seedCatalogs()
    stubCatalogsReload()
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()
    await wrapper.find('.content-head button').trigger('click')

    await wrapper.findComponent(CatalogRecordFormModal).vm.$emit('saved', { id: 'dt-new', name: 'Новый тип' })
    await flushPromises()

    expect(wrapper.findComponent(CatalogRecordFormModal).exists()).toBe(false)
    // Toast рендерится общим ToastContainer вне этого компонента (см. useToast.ts — общее
    // модульное состояние) — проверяем само состояние тоста, а не wrapper.text().
    expect(useToast().toasts.at(-1)?.message).toBe('Запись добавлена')
  })

  it('удаление в модалке закрывает её, перезагружает каталоги и показывает уведомление', async () => {
    seedCatalogs()
    stubCatalogsReload()
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()
    await wrapper.find('tbody tr .icon-btn').trigger('click')

    await wrapper.findComponent(CatalogRecordFormModal).vm.$emit('deleted', 'dt-1')
    await flushPromises()

    expect(wrapper.findComponent(CatalogRecordFormModal).exists()).toBe(false)
    expect(useToast().toasts.at(-1)?.message).toBe('Запись удалена')
  })

  it('закрытие модалки без сохранения не перезагружает каталоги', async () => {
    seedCatalogs()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()
    await wrapper.find('.content-head button').trigger('click')

    await wrapper.findComponent(CatalogRecordFormModal).vm.$emit('close')
    await flushPromises()

    expect(wrapper.findComponent(CatalogRecordFormModal).exists()).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('OtherCatalogsView.vue — пагинация', () => {
  function stubPrefs() {
    const puts: unknown[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith('/preferences/user') && init?.method === 'PUT') {
          puts.push(JSON.parse(init.body as string))
          return jsonResponse({ global: {}, user: {} })
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )
    return puts
  }

  function seedMany(count: number) {
    const catalogs = seedCatalogs()
    catalogs.items['device-types'] = Array.from({ length: count }, (_, i) => ({ id: `dt-${i + 1}`, name: `Тип ${i + 1}` }))
    return catalogs
  }

  const range = (wrapper: ReturnType<typeof mount>) => wrapper.find('.paged-foot .range').text()

  it('длинный справочник режется на страницы по 10 записей, в подвале — диапазон и номера страниц', async () => {
    stubPrefs()
    seedMany(25)
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()

    expect(wrapper.findAll('tbody tr')).toHaveLength(10)
    expect(range(wrapper)).toBe('Показано 1–10 из 25')
    expect(wrapper.findAll('.pager button[aria-label^="Страница"]')).toHaveLength(3)
  })

  it('счётчик у справочника в списке слева остаётся общим числом записей, а не размером страницы', async () => {
    stubPrefs()
    seedMany(25)
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()

    const item = wrapper.findAll('.catalog-item').find((i) => i.text().includes('Тип устройства'))!
    expect(item.find('.count').text()).toBe('25')
  })

  it('последняя страница показывает остаток записей', async () => {
    stubPrefs()
    seedMany(25)
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()

    await wrapper.find('.pager button[aria-label="Страница 3"]').trigger('click')

    expect(wrapper.findAll('tbody tr')).toHaveLength(5)
    expect(wrapper.findAll('tbody tr')[0].text()).toContain('Тип 21')
    expect(range(wrapper)).toBe('Показано 21–25 из 25')
  })

  it('смена размера страницы меняет число строк и запоминается для экрана', async () => {
    const puts = stubPrefs()
    seedMany(25)
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()

    await wrapper.find('.page-size select').setValue('20')
    await flushPromises()

    expect(wrapper.findAll('tbody tr')).toHaveLength(20)
    expect(puts).toEqual([{ page_sizes: { otherCatalogs: 20 } }])
  })

  it('при переходе на другой справочник страница сбрасывается на первую', async () => {
    stubPrefs()
    const catalogs = seedMany(25)
    catalogs.items['manufacturers'] = Array.from({ length: 15 }, (_, i) => ({ id: `mf-${i + 1}`, name: `Производитель ${i + 1}` }))
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()
    await wrapper.find('.pager button[aria-label="Страница 3"]').trigger('click')

    await wrapper
      .findAll('.catalog-item')
      .find((i) => i.text().includes('Производитель'))!
      .trigger('click')

    expect(range(wrapper)).toBe('Показано 1–10 из 15')
    expect(wrapper.findAll('tbody tr')[0].text()).toContain('Производитель 1')
  })

  it('справочник, помещающийся на одну страницу, — одна кнопка страницы; пустой справочник — без подвала', async () => {
    stubPrefs()
    seedCatalogs()
    const wrapper = mount(OtherCatalogsView)
    await flushPromises()

    expect(range(wrapper)).toBe('Показано 1–2 из 2')
    expect(wrapper.findAll('.pager button[aria-label^="Страница"]')).toHaveLength(1)

    await wrapper
      .findAll('.catalog-item')
      .find((i) => i.text().includes('Встроенная ОС'))!
      .trigger('click')
    expect(wrapper.find('.paged-foot').exists()).toBe(false)
  })
})
