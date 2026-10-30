import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import InterfaceConnectionEditor from '../InterfaceConnectionEditor.vue'
import InterfaceRow from '../InterfaceRow.vue'
import InterfaceSubinterfacesEditor from '../InterfaceSubinterfacesEditor.vue'
import type { InterfaceDraftRow, OpenPortDraftRow } from '../../api/types'
import { emptyGroup } from '../../utils/interfaceGroups'
import { makeConflict, makeRow, makeVlan } from '../../utils/__tests__/interfaceRowFixture'

const vlans = [makeVlan('v10', 10, 'Гостевой'), makeVlan('v20', 20, 'Серверы')]
const types = [{ id: 't-eth', name: 'Ethernet' }]
const speeds = [{ id: 's-1g', name: '1 Гбит/с' }]
const catalog = [{ id: 'c80', port: 80, protocol_type: 'HTTP', description: null }]
const http: OpenPortDraftRow = { protocol_catalog_id: 'c80', transport_protocol: 'tcp', description: '' }
const sub = { key: 's1', name: 'Gi0/1.99', vlan_id: 'v99', is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [] }

type RowProps = InstanceType<typeof InterfaceRow>['$props']

// <tr> нельзя монтировать в <div>: браузерный разбор отбросил бы его, поэтому строка монтируется внутрь <tbody>
function mountRow(props: Partial<RowProps> = {}, options: { editConnections?: boolean } = {}) {
  const row = props.row ?? makeRow({ id: 'if-1', name: 'Gi0/1' })
  const tbody = document.body.appendChild(document.createElement('table')).appendChild(document.createElement('tbody'))
  return mount(InterfaceRow, {
    props: {
      row,
      index: 0,
      rows: [row],
      groups: [],
      selected: false,
      expanded: false,
      copyTarget: '',
      typeOptions: types,
      speedOptions: speeds,
      vlanOptions: vlans,
      vlanCatalog: vlans,
      allowedVlanIds: new Set(['v10', 'v20']),
      protocolPortCatalog: catalog,
      collapseAfter: 20,
      conflict: undefined,
      editConnections: options.editConnections ?? false,
      deviceId: null,
      freedPeerIds: new Set<string>(),
      applyingPeerConfig: false,
      peersVersion: 0,
      ...props,
    },
    attachTo: tbody,
    global: { plugins: [createPinia()], stubs: { InterfaceConnectionEditor: true } },
  })
}
const lastPatch = (wrapper: ReturnType<typeof mountRow>) => wrapper.emitted('update')!.at(-1)![0] as Partial<InterfaceDraftRow>

describe('InterfaceRow — свёрнутая строка', () => {
  it('показывает номер, поля порта и сводку «VLAN / IP»; раскрытой части нет', () => {
    const row = makeRow({ id: 'if-1', name: 'Gi0/3', interface_type_id: 't-eth', mac_address: 'AA:BB', speed_id: 's-1g', is_management: true })
    const wrapper = mountRow({ row, rows: [row], index: 2 })

    expect(wrapper.get('.col-index').text()).toBe('3')
    const inputs = wrapper.findAll('.cell-input')
    expect((inputs[0].element as HTMLInputElement).value).toBe('Gi0/3')
    expect((inputs[1].element as HTMLSelectElement).value).toBe('t-eth')
    expect((inputs[2].element as HTMLInputElement).value).toBe('AA:BB')
    expect((inputs[3].element as HTMLSelectElement).value).toBe('s-1g')
    expect((wrapper.findAll('.col-check input')[0].element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.get('.expand-toggle').text()).toBe('Access · 0 IP')
    expect(wrapper.find('.iface-detail-row').exists()).toBe(false)
    wrapper.unmount()
  })

  it('правка полей уходит событием update с патчем, а имя — отдельным событием rename', async () => {
    const wrapper = mountRow()
    const [name, type, mac, speed] = wrapper.findAll('.cell-input')

    await name.setValue('Gi0/9')
    await type.setValue('t-eth')
    await mac.setValue('11:22')
    await speed.setValue('s-1g')
    const [management, dataTransfer] = wrapper.findAll('.col-check input')
    await management.setValue(true)
    await dataTransfer.setValue(true)

    expect(wrapper.emitted('rename')![0]).toEqual(['Gi0/9'])
    expect(wrapper.emitted('update')!.map((e) => e[0])).toEqual([
      { interface_type_id: 't-eth' },
      { mac_address: '11:22' },
      { speed_id: 's-1g' },
      { is_management: true },
      { is_data_transfer: true },
    ])
    wrapper.unmount()
  })

  it('выбор, раскрытие, удаление и перемещение — отдельными событиями', async () => {
    const rows = [makeRow({ id: 'a' }), makeRow({ id: 'b' }), makeRow({ id: 'c' })]
    const wrapper = mountRow({ row: rows[1], rows, index: 1 })

    await wrapper.get('.col-select input').setValue(true)
    await wrapper.get('.expand-toggle').trigger('click')
    await wrapper.get('button[aria-label="Переместить интерфейс выше"]').trigger('click')
    await wrapper.get('button[aria-label="Переместить интерфейс ниже"]').trigger('click')
    await wrapper.get('button[aria-label="Удалить интерфейс"]').trigger('click')

    expect(wrapper.emitted('select')![0]).toEqual([true])
    expect(wrapper.emitted('toggle-expand')).toHaveLength(1)
    expect(wrapper.emitted('move')!.map((e) => e[0])).toEqual([-1, 1])
    expect(wrapper.emitted('remove')).toHaveLength(1)
    wrapper.unmount()
  })

  it('отметка и стрелка раскрытия отражают состояние, переданное родителем', () => {
    const wrapper = mountRow({ selected: true, expanded: true })
    expect((wrapper.get('.col-select input').element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.get('.chev').classes()).toContain('open')
    wrapper.unmount()
  })

  it('первую строку нельзя поднять выше, последнюю — опустить ниже', () => {
    const rows = [makeRow({ id: 'a' }), makeRow({ id: 'b' })]
    const first = mountRow({ row: rows[0], rows, index: 0 })
    const last = mountRow({ row: rows[1], rows, index: 1 })

    expect(first.get('button[aria-label="Переместить интерфейс выше"]').attributes('disabled')).toBeDefined()
    expect(first.get('button[aria-label="Переместить интерфейс ниже"]').attributes('disabled')).toBeUndefined()
    expect(last.get('button[aria-label="Переместить интерфейс выше"]').attributes('disabled')).toBeUndefined()
    expect(last.get('button[aria-label="Переместить интерфейс ниже"]').attributes('disabled')).toBeDefined()
    first.unmount()
    last.unmount()
  })

  it('сводка перечисляет IP, подинтерфейсы, подключение и группу', () => {
    const group = emptyGroup('Магистраль')
    const connection = { peer_device_id: 'dev-2', peer_interface_id: 'p9', connection_type_id: '', description: '', peer_device_name: 'sw-02', peer_interface_name: 'Gi0/9' }
    const row = makeRow({
      id: 'if-1',
      vlan_mode: 'trunk',
      vlan_ids: ['v10', 'v20'],
      group_key: group.key,
      ips: [{ ip_address: '10.0.0.1', prefix_length: '24', purpose: '' }],
      subinterfaces: [{ ...sub, vlan_id: 'v10' }],
      connection,
    })
    const wrapper = mountRow({ row, rows: [row], groups: [group], deviceId: 'dev-1' })

    expect(wrapper.get('.expand-toggle').text()).toBe('Trunk · 2 VLAN · 1 IP · 1 подинт. · ↔ sw-02 · Gi0/9 · Группа «Магистраль»')
    wrapper.unmount()
  })

  it('сводка подключения к другому порту этого же устройства берёт его имя из списка портов', () => {
    const link = { peer_device_id: 'dev-1', peer_interface_id: 'b', connection_type_id: '', description: '' }
    const rows = [makeRow({ id: 'a', name: 'Gi0/1', connection: link }), makeRow({ id: 'b', name: 'Gi0/2' })]
    const wrapper = mountRow({ row: rows[0], rows, deviceId: 'dev-1' })

    expect(wrapper.get('.expand-toggle').text()).toBe('Access · 0 IP · ↔ это устройство · Gi0/2')
    wrapper.unmount()
  })

  it('индикаторы проблем на свёрнутой строке: повтор номера открытого порта, подинтерфейс на недоступном VLAN, расхождения с соседом', () => {
    const row = makeRow({ id: 'if-1', vlan_mode: 'trunk', vlan_ids: ['v10'], open_ports: [http, { ...http }], subinterfaces: [{ ...sub, vlan_id: 'v99' }] })
    const conflict = makeConflict({ flagsDiffer: true, vlanModeDiffer: true, allVlansDiffer: true })
    const wrapper = mountRow({ row, rows: [row], conflict })

    expect(wrapper.get('.ports-dup-icon').attributes('title')).toBe('Повторяются номера открытых портов: 80')
    expect(wrapper.get('.stale-sub-icon').attributes('title')).toContain('«Gi0/1.99»')
    expect(wrapper.findAll('.expand-toggle .conflict-icon')).toHaveLength(4)
    expect(wrapper.findAll('.col-check.has-conflict')).toHaveLength(2) // «Упр.» и «Данные» подсвечиваются вместе
    wrapper.unmount()
  })

  it('подинтерфейс на VLAN, выбранном на порту и назначенном устройству, индикатора не вызывает; снятый с устройства — вызывает', () => {
    const row = makeRow({ id: 'if-1', vlan_mode: 'trunk', vlan_ids: ['v10'], subinterfaces: [{ ...sub, vlan_id: 'v10' }] })

    const fine = mountRow({ row, rows: [row], allowedVlanIds: new Set(['v10', 'v20']) })
    expect(fine.find('.stale-sub-icon').exists()).toBe(false)
    fine.unmount()

    const removed = mountRow({ row, rows: [row], allowedVlanIds: new Set(['v20']) })
    expect(removed.find('.stale-sub-icon').exists()).toBe(true)
    removed.unmount()
  })

  it('без проблем индикаторов нет', () => {
    const wrapper = mountRow({ conflict: makeConflict() })
    expect(wrapper.find('.expand-toggle .conflict-icon').exists()).toBe(false)
    expect(wrapper.find('.has-conflict').exists()).toBe(false)
    wrapper.unmount()
  })

  it('значок расхождения назначения у «Упр.» открывает окно решения по «flags»', async () => {
    const wrapper = mountRow({ conflict: makeConflict({ flagsDiffer: true }) })
    await wrapper.get('.col-check .conflict-icon-btn').trigger('click')
    expect(wrapper.emitted('open-conflict')![0]).toEqual(['flags'])
    wrapper.unmount()
  })
})

describe('InterfaceRow — раскрытая часть', () => {
  it('содержит описание и блоки VLAN, IP-адресов, подинтерфейсов и открытых портов; блока «Подключение» нет, пока не включён', () => {
    const wrapper = mountRow({ expanded: true })

    expect(wrapper.find('.iface-detail-row td').attributes('colspan')).toBe('11')
    for (const selector of ['textarea', '.vlan-block', '.ip-block', '.ports-block']) expect(wrapper.find(`.iface-detail ${selector}`).exists()).toBe(true)
    expect(wrapper.findComponent(InterfaceSubinterfacesEditor).exists()).toBe(true)
    expect(wrapper.findComponent(InterfaceConnectionEditor).exists()).toBe(false)
    wrapper.unmount()
  })

  it('описание уходит событием update', async () => {
    const wrapper = mountRow({ expanded: true })
    await wrapper.get('textarea').setValue('uplink')
    expect(lastPatch(wrapper)).toEqual({ description: 'uplink' })
    wrapper.unmount()
  })

  it('блоки передают действия наверх: режим порта, «Все VLAN», окно выбора VLAN, IP, копирование открытых портов', async () => {
    const rows = [makeRow({ id: 'a', vlan_mode: 'trunk', vlan_ids: ['v10'], open_ports: [http] }), makeRow({ id: 'b', name: 'Gi0/2' })]
    const wrapper = mountRow({ row: rows[0], rows, expanded: true, copyTarget: '1' })

    await wrapper.findAll('input[type="radio"]')[1].trigger('change')
    await wrapper.get('.vlan-check-all input').setValue(true)
    await wrapper.get('.vlan-picker-btn').trigger('click')
    await wrapper.get('.ip-head button').trigger('click')
    await wrapper.get('.copy-target-select').setValue('1')
    await wrapper.get('.copy-ports-row button').trigger('click')

    expect(wrapper.emitted('set-vlan-mode')![0]).toEqual(['access'])
    expect(wrapper.emitted('toggle-all-vlans')![0]).toEqual([true])
    expect(wrapper.emitted('open-vlan-picker')).toHaveLength(1)
    expect(lastPatch(wrapper)).toEqual({ ips: [{ ip_address: '', prefix_length: '', purpose: '' }] })
    expect(wrapper.emitted('set-copy-target')![0]).toEqual(['1'])
    expect(wrapper.emitted('apply-copy')).toHaveLength(1)
    wrapper.unmount()
  })

  it('access-порт: выбор VLAN в блоке уходит событием set-access-vlan', async () => {
    const wrapper = mountRow({ expanded: true })
    wrapper.findComponent({ name: 'SearchableSelect' }).vm.$emit('update:modelValue', 'v20')
    expect(wrapper.emitted('set-access-vlan')![0]).toEqual(['v20'])
    wrapper.unmount()
  })

  it('расхождение режима порта и «Все VLAN» из раскрытой части открывает окно решения по своему виду', async () => {
    const row = makeRow({ id: 'if-1', vlan_mode: 'trunk', vlan_ids: ['v10'] })
    const wrapper = mountRow({ row, rows: [row], expanded: true, conflict: makeConflict({ vlanModeDiffer: true, allVlansDiffer: true }) })

    await wrapper.get('.vlan-mode-row .conflict-icon-btn').trigger('click')
    await wrapper.get('[data-testid="all-vlans-conflict"]').trigger('click')
    expect(wrapper.emitted('open-conflict')!.map((e) => e[0])).toEqual(['vlan_mode', 'all_vlans'])
    wrapper.unmount()
  })

  it('порт из группы: то, что задаёт группа, заблокировано и подписано, остальное доступно', () => {
    const group = { ...emptyGroup('Магистраль'), vlan_mode: 'trunk' as const, ips: [{ ip_address: '10.9.9.1', prefix_length: '', purpose: '' }], manage_open_ports: true }
    const row = makeRow({ id: 'if-1', vlan_mode: 'trunk', group_key: group.key })
    const wrapper = mountRow({ row, rows: [row], groups: [group], expanded: true })

    expect(wrapper.findAll('.vlan-block input[type="radio"]').every((r) => r.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.find('.ip-head button').exists()).toBe(false)
    expect(wrapper.findAll('.group-lock').map((n) => n.text()).every((t) => t.includes('«Магистраль»'))).toBe(true)
    expect(wrapper.findAll('.group-lock')).toHaveLength(3) // режим и VLAN, IP-адрес, открытые порты
    expect(wrapper.find('textarea').attributes('disabled')).toBeUndefined() // описание группа не задаёт
    wrapper.unmount()
  })

  it('подинтерфейсам предлагаются только VLAN, выбранные на самом порту; при «Все VLAN» — все VLAN устройства', () => {
    const manual = makeRow({ id: 'a', vlan_mode: 'trunk', vlan_ids: ['v10'] })
    const all = makeRow({ id: 'b', vlan_mode: 'trunk', all_vlans: true, vlan_ids: ['v10', 'v20'] })
    const ids = (row: InterfaceDraftRow) => {
      const wrapper = mountRow({ row, rows: [row], expanded: true })
      const result = (wrapper.getComponent(InterfaceSubinterfacesEditor).props('vlanOptions') as { id: string }[]).map((v) => v.id)
      wrapper.unmount()
      return result
    }

    expect(ids(manual)).toEqual(['v10'])
    expect(ids(all)).toEqual(['v10', 'v20'])
  })

  it('«Подключение»: блок есть только при editConnections, ему передаются занятые соседи и порты этого устройства, доступные в роли соседа', () => {
    const link = (peer: string) => ({ peer_device_id: '__self__', peer_interface_id: peer, connection_type_id: '', description: '' })
    const rows = [
      makeRow({ id: 'a', name: 'Gi0/1' }),
      makeRow({ id: 'b', name: 'Gi0/2', connection: link('c') }),
      makeRow({ id: 'c', name: 'Gi0/3' }),
      makeRow({ id: 'd', name: 'Gi0/4' }),
      makeRow({ id: 'e', name: 'Gi0/5', connection: link('a') }),
    ]
    const wrapper = mountRow(
      { row: rows[1], rows, index: 1, expanded: true, deviceId: 'dev-1', deviceLabel: 'sw-01', freedPeerIds: new Set(['p1']), peersVersion: 4, applyingPeerConfig: true },
      { editConnections: true },
    )
    const editor = wrapper.getComponent(InterfaceConnectionEditor)

    // занят порт a (его выбрала строка e); свой сосед c в списке остаётся, строка e со своим подключением и сама строка b — нет
    expect([...(editor.props('takenPeerIds') as Set<string>)]).toEqual(['a'])
    expect((editor.props('selfPorts') ?? []).map((p) => p.value)).toEqual(['c', 'd'])
    expect(editor.props()).toMatchObject({ deviceId: 'dev-1', deviceLabel: 'sw-01', applying: true, peersVersion: 4 })
    expect([...(editor.props('freedPeerIds') as Set<string>)]).toEqual(['p1'])
    wrapper.unmount()
  })

  it('«Подключение»: изменение подключения уходит в update, применение конфигурации — отдельными событиями', async () => {
    const wrapper = mountRow({ expanded: true }, { editConnections: true })
    const editor = wrapper.getComponent(InterfaceConnectionEditor)
    const peer = { ref: 'p1', label: 'b1', config: { is_management: false, is_data_transfer: false, vlan_mode: 'trunk' as const, all_vlans: false }, isSelf: false }

    editor.vm.$emit('update:modelValue', null)
    editor.vm.$emit('apply-peer-config', peer, ['flags'])
    editor.vm.$emit('apply-config-to-peer', peer, ['vlan_mode'])

    expect(lastPatch(wrapper)).toEqual({ connection: null })
    expect(wrapper.emitted('apply-peer-config')![0]).toEqual([peer, ['flags']])
    expect(wrapper.emitted('apply-config-to-peer')![0]).toEqual([peer, ['vlan_mode']])
    wrapper.unmount()
  })
})
