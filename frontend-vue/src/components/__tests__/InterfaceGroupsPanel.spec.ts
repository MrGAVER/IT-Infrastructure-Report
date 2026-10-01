import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InterfaceGroupsPanel from '../InterfaceGroupsPanel.vue'
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
      expect(wrapper.findAll('.vlan-param .check-inline input').map((c) => (c.element as HTMLInputElement).checked)).toEqual([true, true])
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
})
