import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import DashboardView from '../DashboardView.vue'
import { routes } from '../../router'

// Все числа разные: по ним тест находит нужную карточку, не завися от порядка.
const COUNTS = {
  information_systems: 12,
  physical_devices: 34,
  virtual_machines: 56,
  containers: 78,
  connections: 91,
  vlan: 23,
  software: 45,
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

// Роутер из настоящей таблицы маршрутов приложения (без гарда и без загрузки экранов): так проверяется, что ссылка
// дашборда ведёт на маршрут, который на самом деле есть, а не только что строка совпала с ожиданием в тесте.
let router: Router

beforeEach(() => {
  router = createRouter({ history: createMemoryHistory(), routes })
})

async function mountDashboard(fetchImpl: () => Promise<Response> = async () => jsonResponse(COUNTS)) {
  vi.stubGlobal('fetch', vi.fn(fetchImpl))
  const wrapper = mount(DashboardView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

describe('DashboardView.vue — ссылки от количеств', () => {
  it('каждое число — ссылка на экран своих записей', async () => {
    const wrapper = await mountDashboard()

    const hrefByNumber = Object.fromEntries(wrapper.findAll('a.num-link').map((a) => [a.text(), a.attributes('href')]))
    expect(hrefByNumber).toEqual({
      '12': '/information-systems',
      '34': '/devices',
      '56': '/vms',
      '78': '/containers',
      '91': '/connections',
      '23': '/vlans',
      '45': '/other-catalogs?catalog=software-assets',
    })
  })

  it('все ссылки ведут на существующие маршруты приложения', async () => {
    const wrapper = await mountDashboard()

    const links = wrapper.findAll('a.num-link')
    expect(links).toHaveLength(7)
    for (const link of links) {
      const resolved = router.resolve(link.attributes('href')!)
      expect(resolved.matched, `нет маршрута для ${link.attributes('href')}`).not.toHaveLength(0)
    }
  })

  it('рядом с числом остаётся подпись карточки, у ссылки — доступное имя с ней', async () => {
    const wrapper = await mountDashboard()

    const devices = wrapper.findAll('.stat-card').find((card) => card.text().includes('Физические устройства'))!
    expect(devices.find('a.num-link').text()).toBe('34')
    expect(devices.find('a.num-link').attributes('aria-label')).toBe('Физические устройства: 34. Открыть раздел')
  })

  it('нулевое количество тоже остаётся ссылкой', async () => {
    const wrapper = await mountDashboard(async () => jsonResponse({ ...COUNTS, containers: 0 }))

    const containers = wrapper.findAll('.stat-card').find((card) => card.text().includes('Контейнеры'))!
    expect(containers.find('a.num-link').text()).toBe('0')
    expect(containers.find('a.num-link').attributes('href')).toBe('/containers')
  })

  it('если сводка не загрузилась — сообщение об ошибке и ни одной ссылки', async () => {
    const wrapper = await mountDashboard(async () => jsonResponse({ detail: 'сбой' }, 500))

    expect(wrapper.find('.error-banner').exists()).toBe(true)
    expect(wrapper.find('a.num-link').exists()).toBe(false)
  })
})
