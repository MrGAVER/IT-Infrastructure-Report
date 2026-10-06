import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InterfaceConnectionEditor from '../InterfaceConnectionEditor.vue'
import type { InterfaceConnectionDraft } from '../../api/types'
import { useCatalogsStore } from '../../stores/catalogs'
import { SELF_DEVICE, type SelfPortCandidate } from '../../utils/interfaceConnections'

const config = { is_management: false, is_data_transfer: true, vlan_mode: 'trunk' as const }

// Подпись устройства-соседа в черновике (peer_device_name) приходит вместе с подключением с сервера и запоминается при
// выборе устройства; для известных id тестовый черновик получает её сам, как настоящий.
const DEVICE_NAMES: Record<string, string> = { 'dev-b': 'sw-b', 'dev-a': 'A-serial' }

function draft(overrides: Partial<InterfaceConnectionDraft> = {}): InterfaceConnectionDraft {
  const name = DEVICE_NAMES[overrides.peer_device_id ?? '']
  return { peer_device_id: '', peer_interface_id: '', connection_type_id: '', description: '', ...(name ? { peer_device_name: name } : {}), ...overrides }
}

interface ServerPort {
  id: string
  name: string
  occupied?: boolean
  is_management?: boolean
  is_data_transfer?: boolean
  vlan_mode?: 'access' | 'trunk'
}
function port(id: string, name: string, extra: Partial<ServerPort> = {}): ServerPort {
  return { id, name, ...extra }
}

interface ServerDevice {
  id: string
  system_name: string
  serial_number: string
}

// Фейковый сервер: GET /devices/{id}/free-interfaces отдаёт свободные порты и явно запрошенные через include (занятые
// помечены occupied), постранично; GET /devices/options — устройства с поиском, include/exclude и страницами.
// Как backend services/device_connectivity.py. `requests` — запросы портов, `deviceRequests` — запросы устройств.
let serverPorts: Record<string, ServerPort[]>
let serverDevices: ServerDevice[]
let requests: string[]
let deviceRequests: string[]
let deviceHandler: ((params: URLSearchParams) => Response | Promise<Response>) | undefined
const deviceLabel = (d: ServerDevice) => d.system_name || d.serial_number
function stubFreeInterfaces(failWith?: number) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const options = /\/devices\/options\?(.*)$/.exec(url)
      if (options) {
        deviceRequests.push(url)
        const params = new URLSearchParams(options[1])
        if (deviceHandler) return deviceHandler(params)
        const q = (params.get('q') ?? '').toLowerCase()
        const include = new Set(params.getAll('include'))
        const exclude = new Set(params.getAll('exclude'))
        const offset = Number(params.get('offset') ?? 0)
        const limit = Number(params.get('limit') ?? 50)
        const found = serverDevices
          .filter((d) => !exclude.has(d.id) && (include.has(d.id) || !q || deviceLabel(d).toLowerCase().includes(q) || d.serial_number.toLowerCase().includes(q)))
          .sort((a, b) => deviceLabel(a).toLowerCase().localeCompare(deviceLabel(b).toLowerCase()))
        const items = found.slice(offset, offset + limit).map((d) => ({ id: d.id, label: deviceLabel(d), system_name: d.system_name || null, serial_number: d.serial_number }))
        return new Response(JSON.stringify({ items, total: found.length, offset, limit }))
      }
      if (failWith) {
        requests.push(url)
        return new Response(JSON.stringify({ detail: 'Сервер недоступен' }), { status: failWith })
      }
      const match = /\/devices\/([^/]+)\/free-interfaces\?(.*)$/.exec(url)
      if (match) requests.push(url)
      if (!match) return new Response(JSON.stringify({ items: [], total: 0, offset: 0, limit: 1000 }))
      const params = new URLSearchParams(match[2])
      const include = new Set(params.getAll('include'))
      const offset = Number(params.get('offset') ?? 0)
      const limit = Number(params.get('limit') ?? 100)
      const selected = (serverPorts[match[1]] ?? []).filter((p) => !p.occupied || include.has(p.id))
      const items = selected.slice(offset, offset + limit).map((p) => ({ is_management: false, is_data_transfer: true, vlan_mode: 'trunk', occupied: false, ...p }))
      return new Response(JSON.stringify({ items, total: selected.length, offset, limit }))
    }),
  )
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
  requests = []
  deviceRequests = []
  deviceHandler = undefined
  serverPorts = {
    'dev-b': [port('b-1', 'Gi0/1'), port('b-2', 'Gi0/2'), port('b-3', 'Gi0/3')],
    'dev-a': [port('a-1', 'eth0')],
  }
  serverDevices = [
    { id: 'dev-self', system_name: 'srv-self', serial_number: 'S0' },
    { id: 'dev-b', system_name: 'sw-b', serial_number: 'S2' },
    { id: 'dev-a', system_name: '', serial_number: 'A-serial' },
  ]
  stubFreeInterfaces()
  useCatalogsStore().items['connection-types'] = [{ id: 'ct-1', name: 'Витая пара' }] as never
})

async function mountEditor(modelValue: InterfaceConnectionDraft | null, extra: Record<string, unknown> = {}) {
  const wrapper = mount(InterfaceConnectionEditor, { props: { modelValue, deviceId: 'dev-self', config, ...extra } })
  await flushPromises() // порты выбранного соседа приходят с сервера
  return wrapper
}

// SearchableSelect — поле с поиском: опции появляются по фокусу (см. pickVlan в DeviceFormModal.spec.ts).
async function optionLabels(wrapper: VueWrapper, rootSelector: string): Promise<string[]> {
  const select = wrapper.find(`${rootSelector} .searchable-select`)
  await select.find('input').trigger('focus')
  await flushPromises() // список устройств запрашивается у сервера при открытии
  return select.findAll('.ss-option').map((o) => o.text())
}

describe('InterfaceConnectionEditor.vue', () => {
  it('порт не подключён: показывает «Порт не подключён», а «Подключить» отдаёт пустой черновик', async () => {
    const wrapper = await mountEditor(null)
    expect(wrapper.text()).toContain('Порт не подключён')
    expect(wrapper.find('.connection-grid').exists()).toBe(false)

    await wrapper.find('.connection-connect-btn').trigger('click')

    expect(wrapper.emitted('update:modelValue')![0][0]).toEqual({ peer_device_id: '', peer_interface_id: '', connection_type_id: '', description: '' })
    expect(requests).toEqual([]) // без выбранного соседа сервер не опрашивается
  })

  it('«Отключить» отдаёт null', async () => {
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-1', connection_type_id: 'ct-1' }))
    await wrapper.find('.connection-disconnect-btn').trigger('click')
    expect(wrapper.emitted('update:modelValue')![0][0]).toBeNull()
  })

  it('в списке устройств нет самого редактируемого устройства; подпись — системное имя или серийный номер', async () => {
    const wrapper = await mountEditor(draft())
    expect(await optionLabels(wrapper, '.connection-peer-device')).toEqual(['A-serial', 'sw-b'])
  })

  it('порт соседа недоступен, пока не выбрано устройство; затем показываются только его свободные порты с сервера', async () => {
    const empty = await mountEditor(draft())
    expect(empty.find('.connection-peer-port input').attributes('disabled')).toBeDefined()

    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b' }))
    expect(await optionLabels(wrapper, '.connection-peer-port')).toEqual(['Gi0/1', 'Gi0/2', 'Gi0/3'])
    expect(requests).toHaveLength(1)
    expect(requests[0]).toContain('/devices/dev-b/free-interfaces?')
  })

  it('порты, занятые на сервере, не предлагаются (сервер их не отдаёт); порты, выбранные в соседних строках, исключены; свой выбранный остаётся', async () => {
    serverPorts['dev-b'] = [port('b-1', 'Gi0/1', { occupied: true }), port('b-2', 'Gi0/2'), port('b-3', 'Gi0/3')]
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-2' }), { takenPeerIds: new Set(['b-3']) })

    expect(await optionLabels(wrapper, '.connection-peer-port')).toEqual(['Gi0/2'])
  })

  it('порт соседа, выбранный в этой строке и занятый этим же подключением, запрашивается через include и остаётся доступным', async () => {
    serverPorts['dev-b'] = [port('b-1', 'Gi0/1', { occupied: true }), port('b-2', 'Gi0/2')]
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-1' }))

    expect(new URLSearchParams(requests[0].split('?')[1]).getAll('include')).toEqual(['b-1'])
    expect(await optionLabels(wrapper, '.connection-peer-port')).toEqual(['Gi0/1', 'Gi0/2'])
  })

  it('смена устройства-соседа сбрасывает выбранный порт и его подпись', async () => {
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-1', peer_interface_name: 'Gi0/1', connection_type_id: 'ct-1' }))
    const select = wrapper.find('.connection-peer-device .searchable-select')
    await select.find('input').trigger('focus')
    await flushPromises()
    await select.findAll('.ss-option').find((o) => o.text() === 'A-serial')!.trigger('mousedown')

    const next = wrapper.emitted('update:modelValue')![0][0] as InterfaceConnectionDraft
    // Подпись нового устройства запоминается в черновике — полного списка устройств у формы нет.
    expect(next).toEqual({ peer_device_id: 'dev-a', peer_device_name: 'A-serial', peer_interface_id: '', connection_type_id: 'ct-1', description: '' })
    expect(next).not.toHaveProperty('peer_interface_name')
  })

  it('выбор порта запоминает его имя для подписи; тип линии и описание обновляют только своё поле черновика', async () => {
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b' }))
    const portSelect = wrapper.find('.connection-peer-port .searchable-select')
    await portSelect.find('input').trigger('focus')
    await portSelect.findAll('.ss-option').find((o) => o.text() === 'Gi0/2')!.trigger('mousedown')
    await wrapper.find('.connection-description input').setValue('патч-корд №5')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toMatchObject({ peer_device_id: 'dev-b', peer_interface_id: 'b-2', peer_interface_name: 'Gi0/2' })
    expect(emitted[1][0]).toMatchObject({ description: 'патч-корд №5' })
  })

  it('у выбранного устройства нет свободных портов — показывается подсказка', async () => {
    serverPorts['dev-b'] = [port('b-1', 'Gi0/1', { occupied: true })]
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b' }))
    expect(wrapper.find('.connection-hint').text()).toContain('нет свободных')
  })

  it('пока порты загружаются — «Загрузка портов устройства…», подсказки «нет свободных» ещё нет', async () => {
    const wrapper = mount(InterfaceConnectionEditor, { props: { modelValue: draft({ peer_device_id: 'dev-b' }), deviceId: 'dev-self', config } })
    expect(wrapper.find('.connection-loading').text()).toContain('Загрузка')
    expect(wrapper.find('.connection-hint').text()).not.toContain('нет свободных')
    await flushPromises()
    expect(wrapper.find('.connection-loading').exists()).toBe(false)
  })

  it('сервер не ответил — понятная ошибка вместо пустого списка', async () => {
    stubFreeInterfaces(500)
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b' }))
    expect(wrapper.find('.connection-error').text()).toContain('Не удалось загрузить порты устройства: Сервер недоступен')
    expect(wrapper.find('.connection-hint').text()).not.toContain('нет свободных')
  })

  it('расхождение конфигурации с портом соседа показывается сразу, совпадающая — нет', async () => {
    serverPorts['dev-b'] = [port('b-1', 'Gi0/1', { is_management: true, vlan_mode: 'access' })]
    const differ = await mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-1' }))
    expect(differ.find('.connection-diffs').text()).toContain('«Управление»: нет / у соседа да')
    expect(differ.find('.connection-diffs').text()).toContain('режим порта: trunk / у соседа access')

    serverPorts['dev-b'] = [port('b-1', 'Gi0/1')]
    const same = await mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-1' }))
    expect(same.find('.connection-diffs').exists()).toBe(false)
  })

  it('порты соседа больше одной страницы подгружаются целиком, а не обрезаются первой страницей', async () => {
    serverPorts['dev-b'] = Array.from({ length: 450 }, (_, i) => port(`b-${i}`, `Gi0/${i + 1}`))
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b' }))

    expect(requests).toHaveLength(3) // 200 + 200 + 50
    const select = wrapper.find('.connection-peer-port .searchable-select')
    await select.find('input').trigger('focus')
    expect(select.findAll('.ss-option').length).toBe(450)
  })

  it('быстрая смена устройства: ответ устаревшего запроса не затирает порты нового выбора', async () => {
    let releaseFirst: () => void = () => {}
    const gate = new Promise<void>((resolve) => (releaseFirst = resolve))
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/devices/dev-b/')) {
          await gate // ответ по dev-b приходит после ответа по dev-a
          return new Response(JSON.stringify({ items: [{ ...port('b-1', 'Gi0/1'), is_management: false, is_data_transfer: true, vlan_mode: 'trunk', occupied: false }], total: 1, offset: 0, limit: 200 }))
        }
        return new Response(JSON.stringify({ items: [{ ...port('a-1', 'eth0'), is_management: false, is_data_transfer: true, vlan_mode: 'trunk', occupied: false }], total: 1, offset: 0, limit: 200 }))
      }),
    )
    const wrapper = mount(InterfaceConnectionEditor, { props: { modelValue: draft({ peer_device_id: 'dev-b' }), deviceId: 'dev-self', config } })
    await wrapper.setProps({ modelValue: draft({ peer_device_id: 'dev-a' }) })
    await flushPromises()
    releaseFirst()
    await flushPromises()

    expect(await optionLabels(wrapper, '.connection-peer-port')).toEqual(['eth0'])
  })
})

describe('InterfaceConnectionEditor.vue — порты этого же устройства и освобождаемые порты', () => {
  const cfg = { is_management: false, is_data_transfer: true, vlan_mode: 'trunk' as const }
  const savedSibling: SelfPortCandidate = { value: 'self-2', label: 'eth1 (строка 2)', interfaceId: 'self-2', config: cfg }
  const newSibling: SelfPortCandidate = { value: 'row:k3', label: 'eth2 (строка 3)', rowKey: 'k3', config: cfg }

  it('без selfPorts самого устройства в списке нет (прежнее поведение)', async () => {
    const wrapper = await mountEditor(draft())
    expect(await optionLabels(wrapper, '.connection-peer-device')).toEqual(['A-serial', 'sw-b'])
  })

  it('с selfPorts «это устройство» первым в списке: у сохранённого — с его именем, у нового — «Это устройство (новое)»', async () => {
    const saved = await mountEditor(draft(), { selfPorts: [], deviceLabel: 'srv-self' })
    expect(await optionLabels(saved, '.connection-peer-device')).toEqual(['srv-self (это устройство)', 'A-serial', 'sw-b'])

    const unnamed = await mountEditor(draft(), { selfPorts: [] }) // подпись формы не передана
    expect((await optionLabels(unnamed, '.connection-peer-device'))[0]).toBe('Это устройство')

    const created = await mountEditor(draft(), { selfPorts: [], deviceId: null })
    expect((await optionLabels(created, '.connection-peer-device'))[0]).toBe('Это устройство (новое)')
  })

  it('выбрав «это устройство», порты предлагаются из selfPorts (в том числе несохранённые), а сервер не опрашивается', async () => {
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-self' }), { selfPorts: [savedSibling, newSibling] })
    expect(await optionLabels(wrapper, '.connection-peer-port')).toEqual(['eth1 (строка 2)', 'eth2 (строка 3)'])
    expect(requests).toEqual([])
  })

  it('выбор несохранённой строки пишет peer_row_key и пустой peer_interface_id; выбор сохранённого порта — его id без peer_row_key и без подписи', async () => {
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-self' }), { selfPorts: [savedSibling, newSibling] })
    const select = wrapper.find('.connection-peer-port .searchable-select')

    await select.find('input').trigger('focus')
    await select.findAll('.ss-option').find((o) => o.text().startsWith('eth2'))!.trigger('mousedown')
    expect(wrapper.emitted('update:modelValue')![0][0]).toMatchObject({ peer_device_id: 'dev-self', peer_interface_id: '', peer_row_key: 'k3' })

    await select.find('input').trigger('focus')
    await select.findAll('.ss-option').find((o) => o.text().startsWith('eth1'))!.trigger('mousedown')
    const second = wrapper.emitted('update:modelValue')![1][0] as InterfaceConnectionDraft
    expect(second).toMatchObject({ peer_interface_id: 'self-2' })
    expect(second).not.toHaveProperty('peer_row_key')
    expect(second).not.toHaveProperty('peer_interface_name')
  })

  it('у ещё не сохранённого устройства «это устройство» — служебное значение SELF_DEVICE, а смена на другое устройство сбрасывает ссылку на строку', async () => {
    const wrapper = await mountEditor(draft({ peer_device_id: SELF_DEVICE, peer_interface_id: '', peer_row_key: 'k3' }), { selfPorts: [newSibling], deviceId: null })
    const select = wrapper.find('.connection-peer-device .searchable-select')
    expect((select.find('input').element as HTMLInputElement).value).toBe('Это устройство (новое)')

    await select.find('input').trigger('focus')
    await flushPromises()
    await select.findAll('.ss-option').find((o) => o.text() === 'sw-b')!.trigger('mousedown')
    const next = wrapper.emitted('update:modelValue')![0][0] as InterfaceConnectionDraft
    expect(next).toMatchObject({ peer_device_id: 'dev-b', peer_device_name: 'sw-b', peer_interface_id: '' })
    expect(next).not.toHaveProperty('peer_row_key')
  })

  it('расхождение с портом этого же устройства сверяется по текущим значениям строки формы', async () => {
    const differ: SelfPortCandidate = { ...newSibling, config: { is_management: true, is_data_transfer: true, vlan_mode: 'trunk' } }
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-self', peer_interface_id: '', peer_row_key: 'k3' }), { selfPorts: [differ] })
    expect(wrapper.find('.connection-diffs').text()).toContain('«Управление»: нет / у соседа да')
  })

  it('нет других портов у этого устройства — подсказка про редактируемое устройство', async () => {
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-self' }), { selfPorts: [] })
    expect(wrapper.find('.connection-hint').text()).toContain('нет свободных портов, кроме редактируемого')
  })

  it('порт соседа, занятый на сервере, но освобождаемый этой же формой (freedPeerIds), запрашивается через include и снова доступен', async () => {
    serverPorts['dev-b'] = [port('b-1', 'Gi0/1', { occupied: true }), port('b-2', 'Gi0/2'), port('b-3', 'Gi0/3')]
    const busy = await mountEditor(draft({ peer_device_id: 'dev-b' }))
    expect(await optionLabels(busy, '.connection-peer-port')).toEqual(['Gi0/2', 'Gi0/3'])

    requests.length = 0
    const freed = await mountEditor(draft({ peer_device_id: 'dev-b' }), { freedPeerIds: new Set(['b-1']) })
    expect(await optionLabels(freed, '.connection-peer-port')).toEqual(['Gi0/1', 'Gi0/2', 'Gi0/3'])
    expect(new URLSearchParams(requests[0].split('?')[1]).getAll('include')).toEqual(['b-1'])
  })

  it('форма освободила порт уже после открытия списка — список перезапрашивается и порт появляется', async () => {
    serverPorts['dev-b'] = [port('b-1', 'Gi0/1', { occupied: true }), port('b-2', 'Gi0/2')]
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b' }))
    expect(await optionLabels(wrapper, '.connection-peer-port')).toEqual(['Gi0/2'])

    await wrapper.setProps({ freedPeerIds: new Set(['b-1']) })
    await flushPromises()

    expect(await optionLabels(wrapper, '.connection-peer-port')).toEqual(['Gi0/1', 'Gi0/2'])
    expect(requests).toHaveLength(2)
  })

  it('освобождённый порт всё равно не предлагается, если его уже выбрала соседняя строка', async () => {
    serverPorts['dev-b'] = [port('b-1', 'Gi0/1', { occupied: true }), port('b-2', 'Gi0/2'), port('b-3', 'Gi0/3')]
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b' }), { freedPeerIds: new Set(['b-1']), takenPeerIds: new Set(['b-1']) })
    expect(await optionLabels(wrapper, '.connection-peer-port')).toEqual(['Gi0/2', 'Gi0/3'])
  })
})

describe('InterfaceConnectionEditor.vue — устройства-соседи ищутся на сервере', () => {
  const deviceSelect = (wrapper: VueWrapper) => wrapper.find('.connection-peer-device .searchable-select')
  const queryOf = (url: string) => new URLSearchParams(url.split('?')[1])

  async function openDevices(wrapper: VueWrapper) {
    await deviceSelect(wrapper).find('input').trigger('focus')
    await flushPromises()
  }
  async function typeDevices(wrapper: VueWrapper, text: string) {
    await deviceSelect(wrapper).find('input').setValue(text)
  }
  const labels = (wrapper: VueWrapper) => deviceSelect(wrapper).findAll('.ss-option').map((o) => o.text())

  it('список устройств не запрашивается, пока выпадающий список не открыт: показ блока «Подключение» сети не нагружает', async () => {
    const wrapper = await mountEditor(draft())
    expect(deviceRequests).toEqual([])

    await openDevices(wrapper)
    expect(deviceRequests).toHaveLength(1)
    expect(queryOf(deviceRequests[0]).get('limit')).toBe('50')
    expect(queryOf(deviceRequests[0]).has('q')).toBe(false)
  })

  it('в запросе редактируемое устройство уходит в exclude, а выбранный сосед — в include', async () => {
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-1' }))
    await openDevices(wrapper)

    const params = queryOf(deviceRequests[0])
    expect(params.getAll('exclude')).toEqual(['dev-self'])
    expect(params.getAll('include')).toEqual(['dev-b'])
  })

  it('поиск уходит на сервер одним запросом после паузы, а результат не фильтруется на клиенте повторно', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = await mountEditor(draft())
      await openDevices(wrapper) // пустой запрос при открытии — сразу
      deviceRequests.length = 0

      await typeDevices(wrapper, 's')
      await typeDevices(wrapper, 'sw')
      expect(deviceRequests).toEqual([]) // пауза ещё не прошла
      await vi.advanceTimersByTimeAsync(300)
      await flushPromises()

      expect(deviceRequests).toHaveLength(1)
      expect(queryOf(deviceRequests[0]).get('q')).toBe('sw')
      expect(labels(wrapper)).toEqual(['sw-b'])
    } finally {
      vi.useRealTimers()
    }
  })

  it('локально опции не отфильтровываются: что вернул сервер (например, найденное по серийному номеру), то и показано', async () => {
    deviceHandler = () => new Response(JSON.stringify({ items: [{ id: 'dev-x', label: 'Коммутатор-7', system_name: 'Коммутатор-7', serial_number: 'ZZZ-1' }], total: 1, offset: 0, limit: 50 }))
    vi.useFakeTimers()
    try {
      const wrapper = await mountEditor(draft())
      await openDevices(wrapper)
      await typeDevices(wrapper, 'zzz-1') // подпись «Коммутатор-7» этот текст не содержит
      await vi.advanceTimersByTimeAsync(300)
      await flushPromises()
      expect(labels(wrapper)).toEqual(['Коммутатор-7'])
    } finally {
      vi.useRealTimers()
    }
  })

  it('выбранный сосед остаётся в списке и подписан, даже когда поиск его не нашёл', async () => {
    deviceHandler = () => new Response(JSON.stringify({ items: [{ id: 'dev-a', label: 'A-serial', system_name: null, serial_number: 'A-serial' }], total: 1, offset: 0, limit: 50 }))
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-1' }))
    expect((deviceSelect(wrapper).find('input').element as HTMLInputElement).value).toBe('sw-b') // подпись из черновика

    await openDevices(wrapper)
    expect(labels(wrapper)).toEqual(['sw-b', 'A-serial'])
  })

  it('черновик без подписи устройства: подпись запрашивается у сервера через include и показывается в поле', async () => {
    const wrapper = await mountEditor({ peer_device_id: 'dev-b', peer_interface_id: 'b-1', connection_type_id: 'ct-1', description: '' })

    expect(deviceRequests).toHaveLength(1)
    expect(queryOf(deviceRequests[0]).getAll('include')).toEqual(['dev-b'])
    expect((deviceSelect(wrapper).find('input').element as HTMLInputElement).value).toBe('sw-b')
  })

  it('найдено больше, чем помещается на странице, — подсказка «показаны первые N из M»', async () => {
    serverDevices = Array.from({ length: 120 }, (_, i) => ({ id: `d-${i}`, system_name: `sw-${String(i).padStart(3, '0')}`, serial_number: `S-${i}` }))
    const wrapper = await mountEditor(draft())
    await openDevices(wrapper)

    expect(deviceSelect(wrapper).findAll('.ss-option')).toHaveLength(50)
    expect(deviceSelect(wrapper).find('.ss-hint').text()).toBe('Показаны первые 50 из 120 — уточните поиск')
  })

  it('сервер не ответил — сообщение об ошибке под полем, а не пустой список без объяснений', async () => {
    deviceHandler = () => new Response(JSON.stringify({ detail: 'База недоступна' }), { status: 500 })
    const wrapper = await mountEditor(draft())
    await openDevices(wrapper)

    expect(wrapper.find('.connection-error').text()).toContain('Не удалось загрузить устройства: База недоступна')
    expect(labels(wrapper)).toEqual([])
  })

  it('ответ устаревшего поиска не затирает результат более нового', async () => {
    vi.useFakeTimers()
    try {
      let releaseFirst: () => void = () => {}
      const gate = new Promise<void>((resolve) => (releaseFirst = resolve))
      const item = (id: string, label: string) => ({ id, label, system_name: label, serial_number: id })
      deviceHandler = async (params) => {
        if (params.get('q') === 'a') {
          await gate // ответ на «a» приходит позже ответа на «ab»
          return new Response(JSON.stringify({ items: [item('old', 'старый')], total: 1, offset: 0, limit: 50 }))
        }
        return new Response(JSON.stringify({ items: [item('new', 'новый')], total: 1, offset: 0, limit: 50 }))
      }
      const wrapper = await mountEditor(draft())
      await openDevices(wrapper)
      await typeDevices(wrapper, 'a')
      await vi.advanceTimersByTimeAsync(300)
      await typeDevices(wrapper, 'ab')
      await vi.advanceTimersByTimeAsync(300)
      await flushPromises()
      releaseFirst()
      await flushPromises()

      expect(labels(wrapper)).toEqual(['новый'])
    } finally {
      vi.useRealTimers()
    }
  })

  it('пункт «это устройство» при поиске показывается, только если подходит под введённый текст', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = await mountEditor(draft(), { selfPorts: [], deviceLabel: 'srv-self' })
      await openDevices(wrapper)
      expect(labels(wrapper)[0]).toBe('srv-self (это устройство)')

      await typeDevices(wrapper, 'sw')
      await vi.advanceTimersByTimeAsync(300)
      await flushPromises()
      expect(labels(wrapper)).toEqual(['sw-b'])

      await typeDevices(wrapper, 'это устр')
      await vi.advanceTimersByTimeAsync(300)
      await flushPromises()
      expect(labels(wrapper)[0]).toBe('srv-self (это устройство)')
    } finally {
      vi.useRealTimers()
    }
  })

  it('«это устройство» и очистка выбора не запоминают подпись устройства', async () => {
    const wrapper = await mountEditor(draft({ peer_device_id: 'dev-b', peer_interface_id: 'b-1' }), { selfPorts: [], deviceLabel: 'srv-self' })
    await openDevices(wrapper)
    await deviceSelect(wrapper).findAll('.ss-option').find((o) => o.text().startsWith('srv-self'))!.trigger('mousedown')

    const next = wrapper.emitted('update:modelValue')![0][0] as InterfaceConnectionDraft
    expect(next).toMatchObject({ peer_device_id: 'dev-self', peer_interface_id: '' })
    expect(next).not.toHaveProperty('peer_device_name')
  })
})
