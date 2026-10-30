import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import StaleSubinterfacesPanel from '../StaleSubinterfacesPanel.vue'
import type { StaleGroupSubinterface, StaleSubinterface } from '../../api/staleSubinterfaces'

function item(patch: Partial<StaleSubinterface> = {}): StaleSubinterface {
  return {
    subinterface_id: 's-1',
    subinterface_name: 'Gi0/0.30',
    port_id: 'p-1',
    port_name: 'Gi0/0',
    device_id: 'd-1',
    device_name: 'RTR-1',
    vlan_id: 'v-30',
    vlan_number: 30,
    vlan_name: 'Резерв',
    reason: 'device',
    ...patch,
  }
}

function groupItem(patch: Partial<StaleGroupSubinterface> = {}): StaleGroupSubinterface {
  return {
    subinterface_id: 'gs-1',
    group_id: 'g-1',
    group_name: 'Серверные',
    device_id: 'd-1',
    device_name: 'RTR-1',
    vlan_id: 'v-30',
    vlan_number: 30,
    vlan_name: 'Резерв',
    ...patch,
  }
}

function stubReport(subinterfaces: StaleSubinterface[], group_subinterfaces: StaleGroupSubinterface[] = []) {
  const total = subinterfaces.length + group_subinterfaces.length
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: total === 0, total, subinterfaces, group_subinterfaces })))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function mountPanel() {
  const wrapper = mount(StaleSubinterfacesPanel)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('StaleSubinterfacesPanel.vue', () => {
  it('если проблем нет — панель ничего не показывает', async () => {
    stubReport([])
    const wrapper = await mountPanel()

    expect(wrapper.find('.stale-panel').exists()).toBe(false)
  })

  it('показывает число подинтерфейсов и строки «порт · подинтерфейс · VLAN», сгруппированные по устройствам', async () => {
    stubReport([
      item({
        subinterface_id: 'a',
        device_id: 'd-1',
        device_name: 'A-FW',
        port_name: 'eth0',
        subinterface_name: 'eth0.10',
        vlan_number: 10,
        vlan_name: 'Серверы',
      }),
      item({ subinterface_id: 'b', device_id: 'd-2', device_name: 'B-RTR' }),
      item({ subinterface_id: 'c', device_id: 'd-2', device_name: 'B-RTR', port_name: 'Gi0/1', subinterface_name: 'Gi0/1.20', vlan_number: 20, vlan_name: '' }),
    ])
    const wrapper = await mountPanel()

    expect(wrapper.find('.stale-head b').text()).toBe('Подинтерфейсы на недоступном VLAN: 3')
    const devices = wrapper.findAll('.stale-device')
    expect(devices.map((d) => d.find('.stale-device-head b').text())).toEqual(['A-FW', 'B-RTR'])
    expect(devices[0].find('li').text()).toContain('eth0')
    expect(devices[0].find('li').text()).toContain('eth0.10')
    expect(devices[0].find('li').text()).toContain('VLAN 10 — Серверы')
    expect(devices[1].findAll('li')).toHaveLength(2)
    expect(devices[1].findAll('li')[1].text()).toContain('VLAN 20') // без имени — только номер
  })

  it('у каждой строки названа причина: снят с устройства / не выбран на порту', async () => {
    stubReport([
      item({ subinterface_id: 'a', reason: 'device', subinterface_name: 'Gi0/0.30' }),
      item({ subinterface_id: 'b', reason: 'port', port_name: 'Gi0/1', subinterface_name: 'Gi0/1.40', vlan_number: 40, vlan_name: 'Гости' }),
    ])
    const wrapper = await mountPanel()

    const rows = wrapper.findAll('.stale-list li')
    expect(rows[0].find('.stale-vlan').text()).toBe('VLAN 30 — Резерв · снят с устройства')
    expect(rows[1].find('.stale-vlan').text()).toBe('VLAN 40 — Гости · не выбран на порту')
  })

  it('шаблоны подинтерфейсов групп показываются в своём устройстве и входят в число; если нет обычных строк — панель всё равно видна', async () => {
    stubReport(
      [item({ device_id: 'd-2', device_name: 'B-RTR' })],
      [
        groupItem({ device_id: 'd-1', device_name: 'A-FW', group_name: 'Серверные' }),
        groupItem({ subinterface_id: 'gs-2', device_id: 'd-2', device_name: 'B-RTR', group_name: 'Гости', vlan_number: 50, vlan_name: '' }),
      ],
    )
    const wrapper = await mountPanel()

    expect(wrapper.find('.stale-head b').text()).toBe('Подинтерфейсы на недоступном VLAN: 3')
    const devices = wrapper.findAll('.stale-device')
    expect(devices.map((d) => d.find('.stale-device-head b').text())).toEqual(['A-FW', 'B-RTR'])
    const only = devices[0].findAll('li')
    expect(only).toHaveLength(1)
    expect(only[0].classes()).toContain('stale-group-item')
    expect(only[0].text()).toContain('Группа «Серверные»')
    expect(only[0].text()).toContain('VLAN 30 — Резерв · не входит в VLAN группы')
    expect(devices[1].findAll('li')).toHaveLength(2) // подинтерфейс порта и шаблон группы «Гости»
    expect(devices[1].findAll('li')[1].text()).toContain('VLAN 50 ·')
  })

  it('«Открыть устройство» сообщает id устройства', async () => {
    stubReport([item({ device_id: 'd-7', device_name: 'RTR-7' })])
    const wrapper = await mountPanel()

    await wrapper.find('.stale-device-head button').trigger('click')

    expect(wrapper.emitted('open-device')).toEqual([['d-7']])
  })

  it('«Проверить снова» и reload() перечитывают отчёт: исправленные строки исчезают', async () => {
    const fetchMock = stubReport([item()])
    const wrapper = await mountPanel()
    expect(wrapper.find('.stale-panel').exists()).toBe(true)

    stubReport([]) // подинтерфейс перенесён на другой VLAN
    await wrapper.find('.stale-head button').trigger('click')
    await flushPromises()

    expect(wrapper.find('.stale-panel').exists()).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    stubReport([item()])
    await (wrapper.vm as unknown as { reload: () => Promise<void> }).reload()
    expect(wrapper.find('.stale-panel').exists()).toBe(true)
  })

  it('сбой диагностики не прячется: причина и «Повторить»', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: 'База недоступна' }), { status: 500 })),
    )
    const wrapper = await mountPanel()

    expect(wrapper.find('[role="alert"]').text()).toContain('Не удалось проверить подинтерфейсы')
    expect(wrapper.find('.stale-panel').classes()).toContain('stale-error')

    stubReport([item()])
    await wrapper.find('[role="alert"] button').trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.find('.stale-head b').text()).toContain(': 1')
  })
})
