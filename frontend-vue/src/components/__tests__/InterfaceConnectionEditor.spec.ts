import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InterfaceConnectionEditor from '../InterfaceConnectionEditor.vue'
import type { InterfaceConnectionDraft } from '../../api/types'
import { useCatalogsStore } from '../../stores/catalogs'
import { useDevicesStore } from '../../stores/devices'
import { SELF_DEVICE, type SelfPortCandidate } from '../../utils/interfaceConnections'

const config = { is_management: false, is_data_transfer: true, vlan_mode: 'trunk' as const }

function draft(overrides: Partial<InterfaceConnectionDraft> = {}): InterfaceConnectionDraft {
  return { peer_device_id: '', peer_interface_id: '', connection_type_id: '', description: '', ...overrides }
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

// Фейковый сервер GET /devices/{id}/free-interfaces: отдаёт свободные порты и явно запрошенные через include
// (занятые помечены occupied), постранично — как backend services/device_connectivity.py.
let serverPorts: Record<string, ServerPort[]>
let requests: string[]
function stubFreeInterfaces(failWith?: number) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      requests.push(url)
      if (failWith) return new Response(JSON.stringify({ detail: 'Сервер недоступен' }), { status: failWith })
      const match = /\/devices\/([^/]+)\/free-interfaces\?(.*)$/.exec(url)
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
  serverPorts = {
    'dev-b': [port('b-1', 'Gi0/1'), port('b-2', 'Gi0/2'), port('b-3', 'Gi0/3')],
    'dev-a': [port('a-1', 'eth0')],
  }
  stubFreeInterfaces()
  useDevicesStore().all = [
    { id: 'dev-self', system_name: 'srv-self', serial_number: 'S0' },
    { id: 'dev-b', system_name: 'sw-b', serial_number: 'S2' },
    { id: 'dev-a', system_name: '', serial_number: 'A-serial' },
  ] as never
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
    await select.findAll('.ss-option').find((o) => o.text() === 'A-serial')!.trigger('mousedown')

    const next = wrapper.emitted('update:modelValue')![0][0] as InterfaceConnectionDraft
    expect(next).toEqual({ peer_device_id: 'dev-a', peer_interface_id: '', connection_type_id: 'ct-1', description: '' })
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
    const saved = await mountEditor(draft(), { selfPorts: [] })
    expect(await optionLabels(saved, '.connection-peer-device')).toEqual(['srv-self (это устройство)', 'A-serial', 'sw-b'])

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
    await select.findAll('.ss-option').find((o) => o.text() === 'sw-b')!.trigger('mousedown')
    const next = wrapper.emitted('update:modelValue')![0][0] as InterfaceConnectionDraft
    expect(next).toMatchObject({ peer_device_id: 'dev-b', peer_interface_id: '' })
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
