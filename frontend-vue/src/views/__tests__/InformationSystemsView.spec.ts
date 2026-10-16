import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InformationSystemsView from '../InformationSystemsView.vue'
import { useInformationSystemsStore } from '../../stores/informationSystems'
import { useCatalogsStore } from '../../stores/catalogs'
import { useContainersStore } from '../../stores/containers'
import { useDevicesStore } from '../../stores/devices'
import { useVMsStore } from '../../stores/vms'
import type { InformationSystem } from '../../api/types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function system(overrides: Partial<InformationSystem>): InformationSystem {
  return {
    id: 'is-1',
    number: null,
    name: 'ИС',
    type: 'ИС',
    description: null,
    purpose: null,
    localization: null,
    support_organization_id: null,
    support_method_id: null,
    process_description: null,
    siem_enabled: false,
    crypto_protection_enabled: false,
    crypto_protection_description_id: null,
    status: 'active',
    ...overrides,
  }
}

/** Всё, что экран грузит рядом со списком ИС (справочники, устройства, ВМ, контейнеры), помечаем загруженным —
 * тесты проверяют сам экран, а не лишние сетевые запросы. Единственный сетевой запрос — список ИС. */
function stubServer(rows: InformationSystem[]) {
  useCatalogsStore().loaded = true
  useDevicesStore().loaded = true
  useVMsStore().loaded = true
  useContainersStore().loaded = true
  const fetchMock = vi.fn(async (url: string) => {
    if (url.endsWith('/information-systems')) return jsonResponse(rows)
    return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function mountView() {
  const wrapper = mount(InformationSystemsView)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('InformationSystemsView.vue — столбец «IP-адреса»', () => {
  it('столбец стоит после «Назначения», перед организацией техподдержки', async () => {
    stubServer([system({ name: 'Альфа' })])
    const wrapper = await mountView()

    const headers = wrapper.findAll('thead th').map((th) => th.text())
    expect(headers).toEqual(['Наименование', 'Назначение', 'IP-адреса', 'Организация техподдержки', 'SIEM', 'СКЗИ', ''])
  })

  it('адреса системы показаны по одному на строке, в порядке ответа сервера', async () => {
    stubServer([system({ name: 'Альфа', ip_addresses: ['10.1.1.5', '192.168.5.10/24'] })])
    const wrapper = await mountView()

    const ips = wrapper.findAll('tbody tr')[0].findAll('.ip-cell .ip')
    expect(ips.map((el) => el.text())).toEqual(['10.1.1.5', '192.168.5.10/24'])
  })

  it('у системы без адресов (пустой список или поля нет в ответе) — прочерк', async () => {
    stubServer([system({ id: 'a', name: 'Альфа', ip_addresses: [] }), system({ id: 'b', name: 'Бета' })])
    const wrapper = await mountView()

    const cells = wrapper.findAll('tbody tr').map((row) => row.find('.ip-cell'))
    expect(cells.map((c) => c.text())).toEqual(['—', '—'])
    expect(wrapper.findAll('.ip')).toHaveLength(0)
  })

  it('строка «ничего не найдено» занимает все столбцы таблицы', async () => {
    stubServer([system({ name: 'Альфа' })])
    const wrapper = await mountView()
    useInformationSystemsStore().search = 'нет такой'
    await flushPromises()

    const columns = wrapper.findAll('thead th').length
    expect(wrapper.find('td.empty-row').attributes('colspan')).toBe(String(columns))
  })

  it('ввод IP-адреса в строку поиска оставляет в таблице только системы с этим адресом', async () => {
    stubServer([
      system({ id: 'a', name: 'Альфа', ip_addresses: ['10.1.1.5', '192.168.5.10/24'] }),
      system({ id: 'b', name: 'Бета', ip_addresses: ['172.16.0.7'] }),
      system({ id: 'c', name: 'Гамма' }),
    ])
    const wrapper = await mountView()
    expect(wrapper.findAll('tbody tr')).toHaveLength(3)

    await wrapper.find('.search-box input').setValue('192.168.5')

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(1)
    expect(rows[0].text()).toContain('Альфа')
    expect(rows[0].find('.ip-cell').text()).toContain('192.168.5.10/24')
  })

  it('подсказка поля поиска упоминает IP-адрес', async () => {
    stubServer([])
    const wrapper = await mountView()

    expect(wrapper.find('.search-box input').attributes('placeholder')).toContain('IP-адрес')
  })

  it('загруженный список при открытии экрана не перезапрашивается', async () => {
    const store = useInformationSystemsStore()
    store.all = [system({ name: 'Альфа', ip_addresses: ['10.0.0.1'] })]
    store.loaded = true
    const fetchMock = stubServer([system({ name: 'Альфа', ip_addresses: ['10.0.0.2'] })])
    const wrapper = await mountView()

    expect(fetchMock).not.toHaveBeenCalled()
    expect(wrapper.find('.ip-cell').text()).toBe('10.0.0.1')
  })

  it('после invalidate() (правка ВМ на другом экране) список загружается заново и показывает новые адреса', async () => {
    const store = useInformationSystemsStore()
    store.all = [system({ name: 'Альфа', ip_addresses: ['10.0.0.1'] })]
    store.loaded = true
    const fetchMock = stubServer([system({ name: 'Альфа', ip_addresses: ['10.0.0.2'] })])

    store.invalidate()
    const wrapper = await mountView()

    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/information-systems'), expect.anything())
    expect(wrapper.find('.ip-cell').text()).toBe('10.0.0.2')
  })
})
