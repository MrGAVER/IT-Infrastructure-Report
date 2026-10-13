import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InterfaceGroupsPanel from '../InterfaceGroupsPanel.vue'
import InterfaceSubinterfacesEditor from '../InterfaceSubinterfacesEditor.vue'
import SearchableSelect from '../SearchableSelect.vue'
import { useToast } from '../../composables/useToast'
import type { InterfaceDraftRow, InterfaceGroupDraft, ProtocolPortCatalogEntry, VLANDefinition } from '../../api/types'

const vlanOptions: VLANDefinition[] = [
  { id: 'v10', vlan_id: 10, name: 'Серверы', description: '', domain_id: null, domain_name: '', devices: [] },
  { id: 'v20', vlan_id: 20, name: 'Гости', description: '', domain_id: null, domain_name: '', devices: [] },
]
const catalog: ProtocolPortCatalogEntry[] = [{ id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null }]

function row(name: string, patch: Partial<InterfaceDraftRow> = {}): InterfaceDraftRow {
  return { name, interface_type_id: '', mac_address: '', speed_id: '', is_management: false, is_data_transfer: false, description: '', vlan_ids: [], vlan_mode: 'access', ips: [], open_ports: [], ...patch }
}

function savedGroup(patch: Partial<InterfaceGroupDraft> = {}): InterfaceGroupDraft {
  return { id: 'g1', key: 'g1', name: 'Серверные', vlan_mode: '', vlan_ids: [], ip_address: '10.0.0.5', prefix_length: '24', ip_purpose: '', manage_open_ports: false, open_ports: [], ...patch }
}

type Change = { rows: InterfaceDraftRow[]; groups: InterfaceGroupDraft[] }

function mountPanel(props: { rows: InterfaceDraftRow[]; groups?: InterfaceGroupDraft[]; selectedIndices?: number[] }) {
  return mount(InterfaceGroupsPanel, { props: { groups: [], vlanOptions, protocolPortCatalog: catalog, ...props } })
}

function lastChange(wrapper: ReturnType<typeof mountPanel>): Change {
  const events = wrapper.emitted('change') as Change[][]
  return events[events.length - 1][0]
}

beforeEach(() => {
  setActivePinia(createPinia())
  useToast().toasts.splice(0)
})

describe('InterfaceGroupsPanel.vue', () => {
  it('без групп показывает подсказку отметить порты', () => {
    const wrapper = mountPanel({ rows: [row('Gi0/1')] })
    expect(wrapper.text()).toContain('Групп нет')
  })

  it('создание группы из отмеченных портов: порты входят в группу, её значения записываются в каждый', async () => {
    const wrapper = mountPanel({ rows: [row('Gi0/1'), row('Gi0/2'), row('Gi0/3')], selectedIndices: [0, 1] })

    await wrapper.find('.groups-head button').trigger('click')
    // Отмеченные в таблице порты сразу предложены как состав группы.
    const members = wrapper.findAll('.member-check input').map((c) => (c.element as HTMLInputElement).checked)
    expect(members).toEqual([true, true, false])

    await wrapper.find('.group-modal .field input').setValue('  Серверные  ')
    await wrapper.findAll('input[name="group-mode"]')[1].trigger('change') // Access
    const vlanSelect = wrapper.find('.vlan-param .searchable-select')
    await vlanSelect.find('input').trigger('focus')
    await vlanSelect.findAll('.ss-option')[0].trigger('mousedown')
    await wrapper.find('input[aria-label="Общий IP-адрес группы"]').setValue('10.0.0.5')
    await wrapper.find('input[aria-label="Префикс общего IP-адреса"]').setValue('24')
    await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

    const { rows, groups } = lastChange(wrapper)
    expect(groups).toHaveLength(1)
    expect(groups[0]).toMatchObject({ name: 'Серверные', vlan_mode: 'access', vlan_ids: ['v10'], ip_address: '10.0.0.5', prefix_length: '24' })
    const key = groups[0].key
    expect(rows.map((r) => r.group_key ?? '')).toEqual([key, key, ''])
    expect(rows[0]).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'] })
    expect(rows[0].ips[0]).toMatchObject({ ip_address: '10.0.0.5', prefix_length: '24' })
    expect(rows[1].ips[0].ip_address).toBe('10.0.0.5')
    expect(rows[2].ips).toEqual([])
    expect(wrapper.find('.group-modal').exists()).toBe(false)
  })

  describe('назначение общего IP-адреса', () => {
    const purposeInput = (wrapper: ReturnType<typeof mountPanel>) => wrapper.find('input[aria-label="Назначение общего IP-адреса группы"]')

    it('в окне группы поле «Назначение» стоит рядом с IP-адресом и префиксом и недоступно, пока IP не указан', async () => {
      const wrapper = mountPanel({ rows: [row('Gi0/1')] })

      await wrapper.find('.groups-head button').trigger('click')

      const inputs = wrapper.findAll('.ip-row input')
      expect(inputs.map((i) => i.attributes('placeholder'))).toEqual(['IP-адрес (пусто — не задавать)', 'Префикс', 'Назначение'])
      expect(purposeInput(wrapper).attributes('disabled')).toBeDefined()

      await wrapper.find('input[aria-label="Общий IP-адрес группы"]').setValue('10.0.0.5')
      expect(purposeInput(wrapper).attributes('disabled')).toBeUndefined()
    })

    it('создание группы с назначением записывает его в IP каждого порта группы', async () => {
      const rows = [row('Gi0/1', { ips: [{ ip_address: '192.168.0.1', prefix_length: '24', purpose: 'Своё' }] }), row('Gi0/2'), row('Gi0/3')]
      const wrapper = mountPanel({ rows, selectedIndices: [0, 1] })

      await wrapper.find('.groups-head button').trigger('click')
      await wrapper.find('.group-modal .field input').setValue('Управление')
      await wrapper.find('input[aria-label="Общий IP-адрес группы"]').setValue('10.0.0.5')
      await wrapper.find('input[aria-label="Префикс общего IP-адреса"]').setValue('24')
      await purposeInput(wrapper).setValue('Администрирование')
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      const { rows: result, groups } = lastChange(wrapper)
      expect(groups[0]).toMatchObject({ ip_address: '10.0.0.5', ip_purpose: 'Администрирование' })
      expect(result[0].ips[0]).toMatchObject({ ip_address: '10.0.0.5', purpose: 'Администрирование' })
      expect(result[1].ips[0]).toMatchObject({ ip_address: '10.0.0.5', purpose: 'Администрирование' })
      expect(result[2].ips).toEqual([])
    })

    it('группа с IP, но с пустым назначением, очищает назначение у портов — оно управляется так же, как адрес и префикс', async () => {
      const rows = [row('Gi0/1', { ips: [{ ip_address: '192.168.0.1', prefix_length: '24', purpose: 'Своё' }] })]
      const wrapper = mountPanel({ rows, selectedIndices: [0] })

      await wrapper.find('.groups-head button').trigger('click')
      await wrapper.find('.group-modal .field input').setValue('Без назначения')
      await wrapper.find('input[aria-label="Общий IP-адрес группы"]').setValue('10.0.0.5')
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      expect(lastChange(wrapper).rows[0].ips[0]).toMatchObject({ ip_address: '10.0.0.5', purpose: '' })
    })

    it('копирование IP с порта подставляет и его назначение', async () => {
      const source = row('Gi0/1', { ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'Администрирование' }] })
      const wrapper = mountPanel({ rows: [source, row('Gi0/2')] })

      await wrapper.find('.groups-head button').trigger('click')
      const select = wrapper.find('.copy-row .searchable-select')
      await select.find('input').trigger('focus')
      await select.findAll('.ss-option').find((o) => o.text() === 'Gi0/1')!.trigger('mousedown')
      await wrapper.find('.copy-row .btn').trigger('click')

      expect((purposeInput(wrapper).element as HTMLInputElement).value).toBe('Администрирование')
    })

    it('правка назначения у сохранённой группы обновляет IP во всех её портах', async () => {
      const group = savedGroup({ ip_purpose: 'Старое' })
      const rows = [row('Gi0/1', { group_key: 'g1', ips: [{ id: 'ip-1', ip_address: '10.0.0.5', prefix_length: '24', purpose: 'Старое' }] })]
      const wrapper = mountPanel({ rows, groups: [group] })

      await wrapper.find('button[aria-label="Изменить группу"]').trigger('click')
      expect((purposeInput(wrapper).element as HTMLInputElement).value).toBe('Старое')
      await purposeInput(wrapper).setValue('Новое')
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      const change = lastChange(wrapper)
      expect(change.groups[0].ip_purpose).toBe('Новое')
      expect(change.rows[0].ips[0]).toMatchObject({ id: 'ip-1', purpose: 'Новое' })
    })

    it('в списке групп назначение указано рядом с IP', () => {
      const wrapper = mountPanel({ rows: [row('Gi0/1', { group_key: 'g1' })], groups: [savedGroup({ ip_purpose: 'Администрирование' })] })

      expect(wrapper.find('.group-summary').text()).toBe('IP 10.0.0.5/24 (Администрирование)')
    })
  })

  it('группа без наименования не создаётся: ошибка и окно остаётся открытым', async () => {
    const wrapper = mountPanel({ rows: [row('Gi0/1')] })

    await wrapper.find('.groups-head button').trigger('click')
    await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

    expect(wrapper.emitted('change')).toBeUndefined()
    expect(wrapper.find('.group-modal').exists()).toBe(true)
    expect(useToast().toasts.map((t) => t.message)).toEqual(['У каждой группы портов должно быть наименование.'])
  })

  it('повтор наименования другой группы отклоняется', async () => {
    const wrapper = mountPanel({ rows: [row('Gi0/1')], groups: [savedGroup()] })

    await wrapper.find('.groups-head button').trigger('click')
    await wrapper.find('.group-modal .field input').setValue('серверные')
    await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

    expect(wrapper.emitted('change')).toBeUndefined()
    expect(useToast().toasts[0].message).toContain('уникальны')
  })

  describe('открытые порты группы: номера не повторяются', () => {
    const wideCatalog: ProtocolPortCatalogEntry[] = [
      { id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null },
      { id: 'cat-http', port: 80, protocol_type: 'HTTP', description: null },
      { id: 'cat-http-alt', port: 80, protocol_type: 'HTTP-Proxy', description: null },
      { id: 'cat-https', port: 443, protocol_type: 'HTTPS', description: null },
    ]
    const port = (protocol_catalog_id: string) => ({ protocol_catalog_id, transport_protocol: 'TCP', description: '' })

    function mountWithPorts(ids: string[]) {
      const group = savedGroup({ manage_open_ports: true, open_ports: ids.map(port) })
      return mount(InterfaceGroupsPanel, { props: { rows: [row('Gi0/1', { group_key: 'g1' })], groups: [group], vlanOptions, protocolPortCatalog: wideCatalog } })
    }

    it('сохранение группы с повтором номера порта отклоняется, окно остаётся открытым', async () => {
      const wrapper = mountWithPorts(['cat-http', 'cat-ssh', 'cat-http-alt'])

      await wrapper.find('button[aria-label="Изменить группу"]').trigger('click')
      expect(wrapper.find('.group-modal .dup-error').text()).toContain('Порт 80')
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      expect(wrapper.emitted('change')).toBeUndefined()
      expect(wrapper.find('.group-modal').exists()).toBe(true)
      expect(useToast().toasts.map((t) => t.message)).toEqual(['В группе «Серверные» номера открытых портов повторяются: 80.'])
    })

    it('при сохранении открытые порты группы упорядочиваются по номеру и в таком порядке попадают в порты-участники', async () => {
      const wrapper = mountWithPorts(['cat-https', 'cat-ssh'])

      await wrapper.find('button[aria-label="Изменить группу"]').trigger('click')
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      const change = lastChange(wrapper)
      expect(change.groups[0].open_ports.map((p) => p.protocol_catalog_id)).toEqual(['cat-ssh', 'cat-https'])
      expect(change.rows[0].open_ports.map((p) => p.protocol_catalog_id)).toEqual(['cat-ssh', 'cat-https'])
    })

    it('без повторов группа сохраняется', async () => {
      const wrapper = mountWithPorts(['cat-ssh', 'cat-https'])

      await wrapper.find('button[aria-label="Изменить группу"]').trigger('click')
      expect(wrapper.find('.group-modal .dup-error').exists()).toBe(false)
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      expect(lastChange(wrapper).groups[0].open_ports.map((p) => p.protocol_catalog_id)).toEqual(['cat-ssh', 'cat-https'])
    })
  })

  it('правка группы обновляет значения во всех её портах и переносит порты из другой группы с предупреждением', async () => {
    const other = savedGroup({ id: 'g2', key: 'g2', name: 'Чужая', ip_address: '' })
    const rows = [row('Gi0/1', { group_key: 'g1' }), row('Gi0/2', { group_key: 'g2' })]
    const wrapper = mountPanel({ rows, groups: [savedGroup(), other] })

    await wrapper.findAll('button[aria-label="Изменить группу"]')[0].trigger('click')
    expect(wrapper.find('.member-note').text()).toContain('«Чужая»')
    await wrapper.findAll('.member-check input')[1].setValue(true)
    await wrapper.find('input[aria-label="Общий IP-адрес группы"]').setValue('10.0.0.9')
    await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

    const change = lastChange(wrapper)
    expect(change.rows.map((r) => r.group_key)).toEqual(['g1', 'g1'])
    expect(change.rows.map((r) => r.ips[0].ip_address)).toEqual(['10.0.0.9', '10.0.0.9'])
    expect(change.groups.find((g) => g.key === 'g1')?.ip_address).toBe('10.0.0.9')
  })

  describe('«Все VLAN» и выбор VLAN в Trunk-режиме группы — как на порту', () => {
    type Wrapper = ReturnType<typeof mountPanel>
    const allCheckbox = (w: Wrapper) => w.find('.vlan-param .vlan-check-all input')
    const isAllChecked = (w: Wrapper) => (allCheckbox(w).element as HTMLInputElement).checked
    const summary = (w: Wrapper) => w.find('.vlan-param .vlan-summary').text()
    const pickerButton = (w: Wrapper) => w.find('.vlan-param .vlan-picker-btn')
    const picker = (w: Wrapper) => w.find('.vlan-picker-modal')
    const pickerVlanChecks = (w: Wrapper) => w.findAll('.vlan-picker-modal .check-inline:not(.vlan-check-all) input')
    const pickerStates = (w: Wrapper) => pickerVlanChecks(w).map((c) => (c.element as HTMLInputElement).checked)
    const modeRadio = (w: Wrapper, index: number) => w.findAll('input[name="group-mode"]')[index]

    async function openTrunkCreate(rows = [row('Gi0/1')]) {
      const wrapper = mountPanel({ rows })
      await wrapper.find('.groups-head button').trigger('click')
      await modeRadio(wrapper, 2).trigger('change') // Trunk
      return wrapper
    }

    it('галочка «Все VLAN» и кнопка выбора есть только в Trunk: в «Не задавать» и Access их нет', async () => {
      const wrapper = mountPanel({ rows: [row('Gi0/1')] })
      await wrapper.find('.groups-head button').trigger('click')
      expect(allCheckbox(wrapper).exists()).toBe(false)
      expect(pickerButton(wrapper).exists()).toBe(false)

      await modeRadio(wrapper, 1).trigger('change') // Access
      expect(allCheckbox(wrapper).exists()).toBe(false)
      expect(pickerButton(wrapper).exists()).toBe(false)

      await modeRadio(wrapper, 2).trigger('change') // Trunk
      expect(allCheckbox(wrapper).exists()).toBe(true)
      expect(pickerButton(wrapper).exists()).toBe(true)
      expect(wrapper.find('.vlan-param .vlan-check-all').text()).toBe('Все VLAN')
    })

    it('переключение в Trunk сразу отмечает все VLAN, в том числе вместо выбранного в Access', async () => {
      const wrapper = mountPanel({ rows: [row('Gi0/1')] })
      await wrapper.find('.groups-head button').trigger('click')
      await modeRadio(wrapper, 1).trigger('change') // Access
      const vlanSelect = wrapper.find('.vlan-param .searchable-select')
      await vlanSelect.find('input').trigger('focus')
      await vlanSelect.findAll('.ss-option')[1].trigger('mousedown') // v20

      await modeRadio(wrapper, 2).trigger('change') // Trunk
      expect(isAllChecked(wrapper)).toBe(true)
      expect(summary(wrapper)).toBe('Выбрано VLAN: 2 из 2')
    })

    it('«Все VLAN» снимает и снова отмечает все VLAN одним кликом', async () => {
      const wrapper = await openTrunkCreate()

      await allCheckbox(wrapper).setValue(false)
      expect(isAllChecked(wrapper)).toBe(false)
      expect(summary(wrapper)).toBe('Выбрано VLAN: 0 из 2')

      await allCheckbox(wrapper).setValue(true)
      expect(isAllChecked(wrapper)).toBe(true)
      expect(summary(wrapper)).toBe('Выбрано VLAN: 2 из 2')
    })

    it('список VLAN открывается кнопкой в окне поверх окна группы и закрывается «Готово», окно группы остаётся', async () => {
      const wrapper = await openTrunkCreate()
      expect(picker(wrapper).exists()).toBe(false)
      expect(wrapper.findAll('.vlan-param .check-inline:not(.vlan-check-all)')).toHaveLength(0) // список VLAN не растягивает окно группы

      await pickerButton(wrapper).trigger('click')
      expect(picker(wrapper).exists()).toBe(true)
      expect(picker(wrapper).findAll('.check-inline:not(.vlan-check-all)').map((l) => l.text())).toEqual(['10 — Серверы', '20 — Гости'])

      await picker(wrapper).find('.modal-foot .btn-primary').trigger('click')
      expect(picker(wrapper).exists()).toBe(false)
      expect(wrapper.find('.group-modal').exists()).toBe(true)
    })

    it('клик по подложке закрывает только окно выбора VLAN, а не окно группы', async () => {
      const wrapper = await openTrunkCreate()
      await pickerButton(wrapper).trigger('click')

      // Окно выбора — последняя подложка в DOM (поверх подложки окна группы).
      const overlays = wrapper.findAll('.overlay')
      expect(overlays).toHaveLength(2)
      await overlays[1].trigger('mousedown')
      await overlays[1].trigger('click')

      expect(picker(wrapper).exists()).toBe(false)
      expect(wrapper.find('.group-modal').exists()).toBe(true)
    })

    it('«Все VLAN» — сохраняемый признак: снятие VLAN снимает галочку, а те же VLAN, отмеченные вручную, её не возвращают', async () => {
      const wrapper = await openTrunkCreate()
      await pickerButton(wrapper).trigger('click')
      expect(pickerStates(wrapper)).toEqual([true, true])

      await pickerVlanChecks(wrapper)[0].setValue(false)
      expect(pickerStates(wrapper)).toEqual([false, true])
      expect(isAllChecked(wrapper)).toBe(false)
      expect(summary(wrapper)).toBe('Выбрано VLAN: 1 из 2')
      // та же галочка есть и в самом окне выбора
      expect((wrapper.find('.vlan-picker-modal .vlan-check-all input').element as HTMLInputElement).checked).toBe(false)

      await pickerVlanChecks(wrapper)[0].setValue(true)
      expect(pickerStates(wrapper)).toEqual([true, true])
      expect(summary(wrapper)).toBe('Выбрано VLAN: 2 из 2')
      expect(isAllChecked(wrapper)).toBe(false) // полный набор вручную — это не признак «Все VLAN»

      await wrapper.find('.vlan-picker-modal .vlan-check-all input').setValue(true)
      expect(isAllChecked(wrapper)).toBe(true)
    })

    it('«Все VLAN» в окне выбора действует так же, как в окне группы', async () => {
      const wrapper = await openTrunkCreate()
      await pickerButton(wrapper).trigger('click')

      await wrapper.find('.vlan-picker-modal .vlan-check-all input').setValue(false)
      expect(pickerStates(wrapper)).toEqual([false, false])
      expect(summary(wrapper)).toBe('Выбрано VLAN: 0 из 2')

      await wrapper.find('.vlan-picker-modal .vlan-check-all input').setValue(true)
      expect(pickerStates(wrapper)).toEqual([true, true])
    })

    it('при сохранении выбранные VLAN записываются в группу и в каждый её порт', async () => {
      const wrapper = await openTrunkCreate([row('Gi0/1'), row('Gi0/2')])
      await wrapper.find('.group-modal .field input').setValue('Транки')
      for (const check of wrapper.findAll('.member-check input')) await check.setValue(true)
      await pickerButton(wrapper).trigger('click')
      await pickerVlanChecks(wrapper)[1].setValue(false) // оставляем только v10
      await picker(wrapper).find('.modal-foot .btn-primary').trigger('click')
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      const { rows, groups } = lastChange(wrapper)
      expect(groups[0]).toMatchObject({ vlan_mode: 'trunk', vlan_ids: ['v10'] })
      expect(rows.map((r) => r.vlan_ids)).toEqual([['v10'], ['v10']])
    })

    it('при сохранении с «Все VLAN» в группу и порты уходят все VLAN устройства и признак «Все VLAN»', async () => {
      const wrapper = await openTrunkCreate([row('Gi0/1')])
      await wrapper.find('.group-modal .field input').setValue('Транки')
      await wrapper.find('.member-check input').setValue(true)
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      const { rows, groups } = lastChange(wrapper)
      expect(groups[0]).toMatchObject({ vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], all_vlans: true })
      expect(rows[0]).toMatchObject({ vlan_ids: ['v10', 'v20'], all_vlans: true })
    })

    it('выбор VLAN вручную (даже всех) сохраняет группу и порты без признака «Все VLAN»', async () => {
      const wrapper = await openTrunkCreate([row('Gi0/1')])
      await wrapper.find('.group-modal .field input').setValue('Транки')
      await wrapper.find('.member-check input').setValue(true)
      await pickerButton(wrapper).trigger('click')
      await pickerVlanChecks(wrapper)[0].setValue(false)
      await pickerVlanChecks(wrapper)[0].setValue(true) // снова все, но вручную
      await picker(wrapper).find('.modal-foot .btn-primary').trigger('click')
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      const { rows, groups } = lastChange(wrapper)
      expect([...groups[0].vlan_ids].sort()).toEqual(['v10', 'v20']) // порядок отметки не важен
      expect(groups[0].all_vlans).toBe(false)
      expect([...rows[0].vlan_ids].sort()).toEqual(['v10', 'v20'])
      expect(rows[0].all_vlans).toBe(false)
    })

    it('в Access признака «Все VLAN» нет: переключение режима его снимает', async () => {
      const wrapper = await openTrunkCreate([row('Gi0/1')])
      expect(isAllChecked(wrapper)).toBe(true)

      await modeRadio(wrapper, 1).trigger('change') // Access
      await modeRadio(wrapper, 2).trigger('change') // и обратно в Trunk — «Все VLAN» ставится заново, как при первом выборе Trunk
      expect(isAllChecked(wrapper)).toBe(true)

      await wrapper.find('.group-modal .field input').setValue('Транки')
      await modeRadio(wrapper, 1).trigger('change')
      await wrapper.find('.member-check input').setValue(true)
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')
      const { groups } = lastChange(wrapper)
      expect(groups[0]).toMatchObject({ vlan_mode: 'access', all_vlans: false })
    })

    it('у сохранённой группы галочка при открытии отражает сохранённый признак, а не число VLAN', async () => {
      const rows = [row('Gi0/1', { group_key: 'g1', vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'] })]
      const flagged = mountPanel({ rows, groups: [savedGroup({ vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], all_vlans: true })] })
      await flagged.find('button[aria-label="Изменить группу"]').trigger('click')
      expect(isAllChecked(flagged)).toBe(true)
      expect(summary(flagged)).toBe('Выбрано VLAN: 2 из 2')

      // тот же полный набор, выбранный вручную, — не «Все VLAN»
      const manual = mountPanel({ rows, groups: [savedGroup({ vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], all_vlans: false })] })
      await manual.find('button[aria-label="Изменить группу"]').trigger('click')
      expect(isAllChecked(manual)).toBe(false)
      expect(summary(manual)).toBe('Выбрано VLAN: 2 из 2')

      const partial = mountPanel({ rows, groups: [savedGroup({ vlan_mode: 'trunk', vlan_ids: ['v20'] })] })
      await partial.find('button[aria-label="Изменить группу"]').trigger('click')
      expect(isAllChecked(partial)).toBe(false)
      expect(summary(partial)).toBe('Выбрано VLAN: 1 из 2')
    })

    it('закрытие окна группы закрывает и окно выбора VLAN: при повторном открытии его нет', async () => {
      const wrapper = await openTrunkCreate()
      await pickerButton(wrapper).trigger('click')
      expect(picker(wrapper).exists()).toBe(true)

      await wrapper.find('.group-modal-actions .btn-secondary').trigger('click') // «Отмена»
      expect(wrapper.find('.group-modal').exists()).toBe(false)
      expect(picker(wrapper).exists()).toBe(false)

      await wrapper.find('.groups-head button').trigger('click')
      expect(picker(wrapper).exists()).toBe(false)
    })

    it('без VLAN у типа устройства нет ни галочки, ни кнопки — только подсказка', async () => {
      const wrapper = mount(InterfaceGroupsPanel, { props: { rows: [row('Gi0/1')], groups: [], vlanOptions: [], protocolPortCatalog: catalog } })
      await wrapper.find('.groups-head button').trigger('click')
      await modeRadio(wrapper, 2).trigger('change') // Trunk

      expect(allCheckbox(wrapper).exists()).toBe(false)
      expect(pickerButton(wrapper).exists()).toBe(false)
      expect(wrapper.find('.vlan-param .empty').text()).toContain('VLAN не назначены')
    })
  })

  describe('поиск в окне выбора VLAN группы', () => {
    const manyVlans: VLANDefinition[] = [
      { id: 'v10', vlan_id: 10, name: 'Серверы', description: '', domain_id: null, domain_name: '', devices: [] },
      { id: 'v20', vlan_id: 20, name: 'Гости', description: '', domain_id: null, domain_name: '', devices: [] },
      { id: 'v30', vlan_id: 30, name: 'Печать', description: '', domain_id: null, domain_name: '', devices: [] },
      { id: 'v110', vlan_id: 110, name: 'Серверы управления', description: '', domain_id: null, domain_name: '', devices: [] },
    ]

    async function openPicker() {
      const wrapper = mount(InterfaceGroupsPanel, { props: { rows: [row('Gi0/1')], groups: [], vlanOptions: manyVlans, protocolPortCatalog: catalog } })
      await wrapper.find('.groups-head button').trigger('click')
      await wrapper.findAll('input[name="group-mode"]')[2].trigger('change') // Trunk — все VLAN отмечены
      await wrapper.find('.vlan-param .vlan-picker-btn').trigger('click')
      return wrapper
    }
    type Wrapper = Awaited<ReturnType<typeof openPicker>>
    const searchInput = (w: Wrapper) => w.find('.vlan-picker-modal .picker-search input')
    const visibleLabels = (w: Wrapper) => w.findAll('.vlan-picker-modal .check-inline:not(.vlan-check-all)').map((l) => l.text())
    const pickerSummary = (w: Wrapper) => w.find('.vlan-picker-modal .vlan-summary').text()
    const inlineSummary = (w: Wrapper) => w.find('.vlan-param .vlan-summary').text()

    it('в окне выбора есть поле поиска, при открытии оно пустое и показаны все VLAN', async () => {
      const wrapper = await openPicker()
      expect(searchInput(wrapper).exists()).toBe(true)
      expect((searchInput(wrapper).element as HTMLInputElement).value).toBe('')
      expect(visibleLabels(wrapper)).toEqual(['10 — Серверы', '20 — Гости', '30 — Печать', '110 — Серверы управления'])
    })

    it('ввод фильтрует список по номеру и имени, несколько слов — по всем сразу', async () => {
      const wrapper = await openPicker()

      await searchInput(wrapper).setValue('серверы')
      expect(visibleLabels(wrapper)).toEqual(['10 — Серверы', '110 — Серверы управления'])

      await searchInput(wrapper).setValue('серверы 110')
      expect(visibleLabels(wrapper)).toEqual(['110 — Серверы управления'])

      await searchInput(wrapper).setValue('30')
      expect(visibleLabels(wrapper)).toEqual(['30 — Печать'])
    })

    it('если ничего не найдено — подсказка вместо списка', async () => {
      const wrapper = await openPicker()
      await searchInput(wrapper).setValue('нет такого')

      expect(visibleLabels(wrapper)).toEqual([])
      expect(wrapper.find('.vlan-picker-modal .picker-empty').text()).toBe('Ничего не найдено')

      await searchInput(wrapper).setValue('')
      expect(wrapper.find('.vlan-picker-modal .picker-empty').exists()).toBe(false)
    })

    it('отметка найденного VLAN при активном поиске не трогает скрытые; сводка считает все VLAN, а не только найденные', async () => {
      const wrapper = await openPicker()
      await wrapper.find('.vlan-picker-modal .vlan-check-all input').setValue(false) // снять все
      await searchInput(wrapper).setValue('гост')
      expect(pickerSummary(wrapper)).toBe('Выбрано VLAN: 0 из 4')

      await wrapper.find('.vlan-picker-modal .check-inline:not(.vlan-check-all) input').setValue(true) // «20 — Гости»
      expect(pickerSummary(wrapper)).toBe('Выбрано VLAN: 1 из 4')
      expect(inlineSummary(wrapper)).toBe('Выбрано VLAN: 1 из 4')

      await searchInput(wrapper).setValue('')
      const states = wrapper.findAll('.vlan-picker-modal .check-inline:not(.vlan-check-all) input').map((c) => (c.element as HTMLInputElement).checked)
      expect(states).toEqual([false, true, false, false])
    })

    it('«Все VLAN» при активном поиске действует на ВСЕ VLAN, включая скрытые фильтром', async () => {
      const wrapper = await openPicker()
      await searchInput(wrapper).setValue('гост')

      await wrapper.find('.vlan-picker-modal .vlan-check-all input').setValue(false)
      expect(pickerSummary(wrapper)).toBe('Выбрано VLAN: 0 из 4')

      await wrapper.find('.vlan-picker-modal .vlan-check-all input').setValue(true)
      expect(pickerSummary(wrapper)).toBe('Выбрано VLAN: 4 из 4')
    })

    it('поиск сбрасывается при повторном открытии окна выбора', async () => {
      const wrapper = await openPicker()
      await searchInput(wrapper).setValue('серверы')
      await wrapper.find('.vlan-picker-modal .modal-foot .btn-primary').trigger('click') // «Готово»

      await wrapper.find('.vlan-param .vlan-picker-btn').trigger('click')
      expect((searchInput(wrapper).element as HTMLInputElement).value).toBe('')
      expect(visibleLabels(wrapper)).toHaveLength(4)
    })
  })

  describe('копирование значений с порта', () => {
    const sourceRow = () =>
      row('Gi0/1', {
        vlan_mode: 'trunk',
        vlan_ids: ['v10', 'v20'],
        ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }],
        open_ports: [{ id: 'op-1', protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: 'админ' }],
      })

    async function openCreateAndPickSource(wrapper: ReturnType<typeof mountPanel>, label = 'Gi0/1') {
      await wrapper.find('.groups-head button').trigger('click')
      const select = wrapper.find('.copy-row .searchable-select')
      await select.find('input').trigger('focus')
      await select.findAll('.ss-option').find((o) => o.text() === label)!.trigger('mousedown')
    }

    it('без выбранного порта кнопка «Скопировать» недоступна, список вариантов — порты устройства', async () => {
      const wrapper = mountPanel({ rows: [sourceRow(), row('Gi0/2')] })

      await wrapper.find('.groups-head button').trigger('click')
      expect(wrapper.find('.copy-row .btn').attributes('disabled')).toBeDefined()
      expect(wrapper.find('.copy-what').exists()).toBe(false)

      await wrapper.find('.copy-row .searchable-select input').trigger('focus')
      expect(wrapper.findAll('.copy-row .ss-option').map((o) => o.text())).toEqual(['Gi0/1', 'Gi0/2'])
    })

    it('после выбора порта отмечено всё, что на нём задано; недоступное выключено', async () => {
      const onlyIp = row('Gi0/2', { ips: [{ ip_address: '10.0.0.9', prefix_length: '24', purpose: '' }] })
      const wrapper = mountPanel({ rows: [sourceRow(), onlyIp] })

      await openCreateAndPickSource(wrapper, 'Gi0/2')

      const boxes = wrapper.findAll('.copy-what input').map((c) => ({ checked: (c.element as HTMLInputElement).checked, disabled: c.attributes('disabled') !== undefined }))
      expect(boxes).toEqual([
        { checked: false, disabled: true }, // режим порта и VLAN — на порту нет VLAN
        { checked: true, disabled: false }, // IP-адрес
        { checked: false, disabled: true }, // открытые порты — не заданы
      ])
      expect(wrapper.find('.copy-row .btn').attributes('disabled')).toBeUndefined()
    })

    it('«Скопировать» переносит и признак «Все VLAN» порта', async () => {
      const wrapper = mountPanel({ rows: [{ ...sourceRow(), all_vlans: true }, row('Gi0/2')] })

      await openCreateAndPickSource(wrapper)
      await wrapper.find('.copy-row .btn').trigger('click')

      expect((wrapper.find('.vlan-param .vlan-check-all input').element as HTMLInputElement).checked).toBe(true)
    })

    it('порт без значений: подсказка и недоступное копирование', async () => {
      const wrapper = mountPanel({ rows: [sourceRow(), row('Gi0/2')] })

      await openCreateAndPickSource(wrapper, 'Gi0/2')

      expect(wrapper.find('.copy-what').text()).toContain('нет значений, которые можно скопировать')
      expect(wrapper.find('.copy-row .btn').attributes('disabled')).toBeDefined()
    })

    it('«Скопировать» заполняет параметры группы значениями порта и сообщает об этом', async () => {
      const wrapper = mountPanel({ rows: [sourceRow(), row('Gi0/2')] })

      await openCreateAndPickSource(wrapper)
      await wrapper.find('.copy-row .btn').trigger('click')

      expect((wrapper.findAll('input[name="group-mode"]')[2].element as HTMLInputElement).checked).toBe(true) // Trunk
      // С порта скопирован полный набор VLAN, выбранный вручную (признака «Все VLAN» у порта нет) — галочка не ставится.
      expect((wrapper.find('.vlan-param .vlan-check-all input').element as HTMLInputElement).checked).toBe(false)
      expect(wrapper.find('.vlan-param .vlan-summary').text()).toBe('Выбрано VLAN: 2 из 2')
      expect((wrapper.find('input[aria-label="Общий IP-адрес группы"]').element as HTMLInputElement).value).toBe('10.0.0.5')
      expect((wrapper.find('input[aria-label="Префикс общего IP-адреса"]').element as HTMLInputElement).value).toBe('24')
      expect((wrapper.find('.ports-param .manage-check input').element as HTMLInputElement).checked).toBe(true)
      expect(wrapper.findAll('.ports-param .nested-row').length).toBe(1)
      expect(useToast().toasts.map((t) => t.message)).toEqual(['Значения скопированы с порта «Gi0/1».'])
      // выбор порта сброшен — повторное копирование требует нового выбора
      expect(wrapper.find('.copy-what').exists()).toBe(false)
    })

    it('копируется только отмеченное', async () => {
      const wrapper = mountPanel({ rows: [sourceRow(), row('Gi0/2')] })

      await openCreateAndPickSource(wrapper)
      await wrapper.findAll('.copy-what input')[0].setValue(false) // без режима порта и VLAN
      await wrapper.findAll('.copy-what input')[2].setValue(false) // без открытых портов
      await wrapper.find('.copy-row .btn').trigger('click')

      expect((wrapper.findAll('input[name="group-mode"]')[0].element as HTMLInputElement).checked).toBe(true) // «Не задавать»
      expect((wrapper.find('input[aria-label="Общий IP-адрес группы"]').element as HTMLInputElement).value).toBe('10.0.0.5')
      expect((wrapper.find('.ports-param .manage-check input').element as HTMLInputElement).checked).toBe(false)
    })

    it('у порта несколько IP — в уведомлении сказано, что скопирован первый', async () => {
      const many = row('Gi0/1', { ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }, { ip_address: '10.0.0.6', prefix_length: '24', purpose: '' }] })
      const wrapper = mountPanel({ rows: [many] })

      await openCreateAndPickSource(wrapper)
      await wrapper.find('.copy-row .btn').trigger('click')

      expect(useToast().toasts[0].message).toContain('скопирован первый')
      expect((wrapper.find('input[aria-label="Общий IP-адрес группы"]').element as HTMLInputElement).value).toBe('10.0.0.5')
    })

    it('скопированные значения записываются в порты группы только при сохранении группы', async () => {
      const wrapper = mountPanel({ rows: [sourceRow(), row('Gi0/2'), row('Gi0/3')], selectedIndices: [1, 2] })

      await openCreateAndPickSource(wrapper)
      await wrapper.find('.copy-row .btn').trigger('click')
      expect(wrapper.emitted('change')).toBeUndefined()

      await wrapper.find('.group-modal .field input').setValue('Копия Gi0/1')
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      const { rows, groups } = lastChange(wrapper)
      expect(groups[0]).toMatchObject({ name: 'Копия Gi0/1', vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'], ip_address: '10.0.0.5', manage_open_ports: true })
      for (const i of [1, 2]) {
        expect(rows[i]).toMatchObject({ group_key: groups[0].key, vlan_mode: 'trunk', vlan_ids: ['v10', 'v20'] })
        expect(rows[i].ips[0].ip_address).toBe('10.0.0.5')
        expect(rows[i].open_ports.map((p) => p.protocol_catalog_id)).toEqual(['cat-ssh'])
      }
      // порт-источник не менялся и в группу не вошёл
      expect(rows[0]).toEqual(sourceRow())
    })

    it('при повторном открытии окна прежний выбор порта не сохраняется', async () => {
      const wrapper = mountPanel({ rows: [sourceRow()] })

      await openCreateAndPickSource(wrapper)
      await wrapper.find('.group-modal .modal-head .icon-btn').trigger('click')
      await wrapper.find('.groups-head button').trigger('click')

      expect(wrapper.find('.copy-what').exists()).toBe(false)
    })
  })

  describe('удаление группы', () => {
    const groups = [savedGroup()]
    const rows = () => [row('Gi0/1', { group_key: 'g1', ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] }), row('Gi0/2')]

    it('спрашивает, что сделать со значениями, и по умолчанию предлагает оставить их в портах', async () => {
      const wrapper = mountPanel({ rows: rows(), groups })

      await wrapper.find('button[aria-label="Удалить группу"]').trigger('click')

      const dialog = wrapper.find('.delete-modal')
      expect(dialog.text()).toContain('Оставить значения в портах')
      expect(dialog.text()).toContain('Стереть значения')
      expect(dialog.text()).toContain('IP-адрес')
      expect(wrapper.emitted('change')).toBeUndefined()
      // Главная (primary) кнопка — «оставить», стирание — второстепенная.
      expect(dialog.find('.btn-primary').text()).toBe('Оставить значения в портах')
    })

    it('«Оставить значения»: группа удалена, порты вне группы, значения на месте', async () => {
      const wrapper = mountPanel({ rows: rows(), groups })

      await wrapper.find('button[aria-label="Удалить группу"]').trigger('click')
      await wrapper.find('.delete-modal .btn-primary').trigger('click')

      const change = lastChange(wrapper)
      expect(change.groups).toEqual([])
      expect(change.rows[0].group_key).toBe('')
      expect(change.rows[0].ips).toEqual([{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }])
      expect(wrapper.find('.delete-modal').exists()).toBe(false)
    })

    it('«Стереть значения»: группа удалена, значения управляемых ею параметров стёрты только у её портов', async () => {
      const wrapper = mountPanel({ rows: rows(), groups })

      await wrapper.find('button[aria-label="Удалить группу"]').trigger('click')
      await wrapper.find('.delete-modal .danger-btn').trigger('click')

      const change = lastChange(wrapper)
      expect(change.groups).toEqual([])
      expect(change.rows[0]).toMatchObject({ group_key: '', ips: [] })
      expect(change.rows[1]).toEqual(rows()[1])
    })

    it('«Отмена» ничего не меняет', async () => {
      const wrapper = mountPanel({ rows: rows(), groups })

      await wrapper.find('button[aria-label="Удалить группу"]').trigger('click')
      const cancel = wrapper.findAll('.delete-actions .btn').find((b) => b.text() === 'Отмена')!
      await cancel.trigger('click')

      expect(wrapper.emitted('change')).toBeUndefined()
      expect(wrapper.find('.delete-modal').exists()).toBe(false)
    })

    it('у группы без портов спрашивать нечего — удаляется сразу', async () => {
      const wrapper = mountPanel({ rows: [row('Gi0/1')], groups })

      await wrapper.find('button[aria-label="Удалить группу"]').trigger('click')

      expect(wrapper.find('.delete-modal').exists()).toBe(false)
      expect(lastChange(wrapper).groups).toEqual([])
    })
  })

  describe('подинтерфейсы группы', () => {
    type Wrapper = ReturnType<typeof mountPanel>
    const manageCheck = (w: Wrapper) => w.find('input[aria-label="Задать подинтерфейсы"]')
    const editor = (w: Wrapper) => w.findComponent(InterfaceSubinterfacesEditor)
    const vlanSelect = (w: Wrapper) => editor(w).findComponent(SearchableSelect)
    const optionValues = (w: Wrapper) => (vlanSelect(w).props('options') as { value: string }[]).map((o) => o.value)
    const template = (patch = {}) => ({ key: 't1', name: '', vlan_id: 'v10', is_management: true, is_data_transfer: false, description: '', ips: [{ ip_address: '10.0.10.1', prefix_length: '24', purpose: '' }], open_ports: [], ...patch })
    const trunkGroup = (patch: Partial<InterfaceGroupDraft> = {}) => savedGroup({ vlan_mode: 'trunk', vlan_ids: ['v10'], ip_address: '', prefix_length: '', ...patch })

    it('редактор подинтерфейсов появляется только после галочки «Задать подинтерфейсы»', async () => {
      const wrapper = mountPanel({ rows: [row('Gi0/1', { group_key: 'g1' })], groups: [trunkGroup()] })
      await wrapper.find('button[aria-label="Изменить группу"]').trigger('click')

      expect(editor(wrapper).exists()).toBe(false)
      await manageCheck(wrapper).setValue(true)

      expect(editor(wrapper).exists()).toBe(true)
      expect(editor(wrapper).props('mode')).toBe('group')
    })

    it('VLAN шаблона выбирается только из VLAN группы; без режима порта и VLAN группы список пуст', async () => {
      const wrapper = mountPanel({ rows: [row('Gi0/1', { group_key: 'g1' })], groups: [trunkGroup({ manage_subinterfaces: true, subinterfaces: [template({ vlan_id: '' })] })] })
      await wrapper.find('button[aria-label="Изменить группу"]').trigger('click')
      expect(optionValues(wrapper)).toEqual(['v10']) // v20 в VLAN группы не входит

      const none = mountPanel({ rows: [], groups: [savedGroup({ manage_subinterfaces: true })] }) // режим порта не задан
      await none.find('button[aria-label="Изменить группу"]').trigger('click')
      expect(editor(none).props('vlanOptions')).toEqual([])
      expect(editor(none).text()).toContain('задайте режим порта и VLAN группы')
    })

    it('«Все VLAN» у группы: в списке подинтерфейса все VLAN устройства', async () => {
      const wrapper = mountPanel({ rows: [], groups: [trunkGroup({ all_vlans: true, vlan_ids: ['v10', 'v20'], manage_subinterfaces: true, subinterfaces: [template({ vlan_id: '' })] })] })
      await wrapper.find('button[aria-label="Изменить группу"]').trigger('click')

      expect(optionValues(wrapper)).toEqual(['v10', 'v20'])
    })

    it('сохранение записывает в каждый порт группы подинтерфейс «<порт>.<VLAN>» с общими значениями', async () => {
      const rows = [row('Gi0/1', { group_key: 'g1' }), row('Gi0/2', { group_key: 'g1' }), row('Gi0/3')]
      const wrapper = mountPanel({ rows, groups: [trunkGroup({ manage_subinterfaces: true, subinterfaces: [template()] })] })

      await wrapper.find('button[aria-label="Изменить группу"]').trigger('click')
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      const change = lastChange(wrapper)
      expect(change.rows[0].subinterfaces!.map((s) => [s.name, s.vlan_id, s.is_management])).toEqual([['Gi0/1.10', 'v10', true]])
      expect(change.rows[1].subinterfaces![0]).toMatchObject({ name: 'Gi0/2.10', ips: [{ ip_address: '10.0.10.1', prefix_length: '24' }] })
      expect(change.rows[2].subinterfaces).toBeUndefined() // порт вне группы не тронут
      expect(change.groups[0]).toMatchObject({ manage_subinterfaces: true })
      expect(change.groups[0].subinterfaces).toHaveLength(1)
    })

    it('шаблоны сохраняются по возрастанию номера VLAN', async () => {
      const rows = [row('Gi0/1', { group_key: 'g1' })]
      const wrapper = mountPanel({ rows, groups: [trunkGroup({ vlan_ids: ['v10', 'v20'], manage_subinterfaces: true, subinterfaces: [template({ key: 't20', vlan_id: 'v20' }), template({ key: 't10' })] })] })

      await wrapper.find('button[aria-label="Изменить группу"]').trigger('click')
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      expect(lastChange(wrapper).groups[0].subinterfaces!.map((s) => s.vlan_id)).toEqual(['v10', 'v20'])
    })

    it('подинтерфейс на VLAN, не входящем в VLAN группы, не сохраняется: ошибка, окно открыто', async () => {
      const wrapper = mountPanel({ rows: [], groups: [trunkGroup({ manage_subinterfaces: true, subinterfaces: [template({ vlan_id: 'v20' })] })] })

      await wrapper.find('button[aria-label="Изменить группу"]').trigger('click')
      await wrapper.find('.group-modal-actions .btn-primary').trigger('click')

      expect(wrapper.emitted('change')).toBeUndefined()
      expect(wrapper.find('.group-modal').text()).toContain('не входит в VLAN группы')
    })

    it('удаление группы с подинтерфейсами предупреждает, что значения останутся или будут стёрты', async () => {
      const wrapper = mountPanel({ rows: [row('Gi0/1', { group_key: 'g1' })], groups: [trunkGroup({ manage_subinterfaces: true, subinterfaces: [template()] })] })

      await wrapper.find('button[aria-label="Удалить группу"]').trigger('click')

      expect(wrapper.find('.delete-modal').text()).toContain('подинтерфейсы')
    })
  })
})
