import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InterfaceSubinterfacesEditor from '../InterfaceSubinterfacesEditor.vue'
import ScrollableTableWrap from '../ScrollableTableWrap.vue'
import SearchableSelect from '../SearchableSelect.vue'
import { emptySubinterface } from '../../utils/subinterfaces'
import type { ProtocolPortCatalogEntry, SubinterfaceDraftRow, VLANDefinition } from '../../api/types'

const vlans: VLANDefinition[] = [
  { id: 'v-20', vlan_id: 20, name: 'Гости', description: '', domain_id: null, domain_name: '', devices: [] },
  { id: 'v-10', vlan_id: 10, name: 'Серверы', description: '', domain_id: null, domain_name: '', devices: [] },
]
const catalog: ProtocolPortCatalogEntry[] = [{ id: 'cat-ssh', port: 22, protocol_type: 'SSH', description: null }]

function mountEditor(modelValue: SubinterfaceDraftRow[] = [], extra: Record<string, unknown> = {}) {
  return mount(InterfaceSubinterfacesEditor, { props: { modelValue, parentName: 'Gi0/0', vlanOptions: vlans, protocolPortCatalog: catalog, ...extra } })
}

// Список VLAN строки — SearchableSelect: выбор моделируем событием компонента, варианты читаем из его options.
function vlanSelects(wrapper: ReturnType<typeof mountEditor>) {
  return wrapper.findAllComponents(SearchableSelect)
}
function optionValues(select: ReturnType<typeof vlanSelects>[number]): string[] {
  return (select.props('options') as { value: string }[]).map((o) => o.value)
}
async function expandRow(wrapper: ReturnType<typeof mountEditor>, index = 0) {
  await wrapper.findAll('.expand-toggle')[index].trigger('click')
}

function lastEmitted(wrapper: ReturnType<typeof mountEditor>): SubinterfaceDraftRow[] {
  const events = wrapper.emitted('update:modelValue')!
  return events[events.length - 1][0] as SubinterfaceDraftRow[]
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('InterfaceSubinterfacesEditor.vue', () => {
  it('без подинтерфейсов показывает подсказку; кнопка «+ Подинтерфейс» добавляет пустую строку', async () => {
    const wrapper = mountEditor()
    expect(wrapper.text()).toContain('Подинтерфейсы не добавлены')

    await wrapper.find('.sub-head button').trigger('click')

    const [added] = lastEmitted(wrapper)
    expect(added).toMatchObject({ name: '', vlan_id: '', ips: [], open_ports: [], is_management: false, is_data_transfer: false })
    expect(added.id).toBeUndefined()
  })

  it('F-05: таблица подинтерфейсов стоит в ScrollableTableWrap — на телефоне видна подсказка о прокрутке', () => {
    const wrapper = mountEditor([emptySubinterface('Gi0/0', vlans[1])])
    const wrap = wrapper.getComponent(ScrollableTableWrap)
    expect(wrap.attributes('aria-label')).toBe('Подинтерфейсы')
    expect(wrap.find('table.sub-table').exists()).toBe(true)
  })

  it('если на порту не выбраны VLAN — добавить подинтерфейс нельзя, подсказка объясняет почему', () => {
    const wrapper = mountEditor([], { vlanOptions: [] })
    expect(wrapper.find('.sub-head button').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('выберите VLAN порта')
  })

  it('если все VLAN порта уже заняты подинтерфейсами — новый добавить нельзя', () => {
    const wrapper = mountEditor([emptySubinterface('Gi0/0', vlans[1]), emptySubinterface('Gi0/0', vlans[0])])
    expect(wrapper.find('.sub-head button').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.sub-head button').attributes('title')).toContain('Все VLAN порта уже использованы')
  })

  it('таблица: столбцы «Имя», «VLAN», «Управление», «Данные» и разворачиваемый «IP-адреса / маски»', () => {
    const wrapper = mountEditor([emptySubinterface('Gi0/0', vlans[1])])
    expect(wrapper.findAll('thead th').map((th) => th.text())).toEqual(['Имя', 'VLAN', 'Управление', 'Данные', 'IP-адреса / маски', ''])
  })

  it('поле VLAN — SearchableSelect, в нём только VLAN, выбранные на порту, по возрастанию номера', () => {
    const portOnly = [vlans[1]] // на порту выбран один VLAN (10); VLAN 20 порту не принадлежит
    const wrapper = mountEditor([emptySubinterface('Gi0/0')], { vlanOptions: portOnly })

    expect(vlanSelects(wrapper)).toHaveLength(1)
    expect(wrapper.find('select[aria-label="VLAN подинтерфейса"]').exists()).toBe(false) // нативного select больше нет
    expect(optionValues(vlanSelects(wrapper)[0])).toEqual(['v-10'])

    const two = mountEditor([emptySubinterface('Gi0/0')])
    expect(optionValues(vlanSelects(two)[0])).toEqual(['v-10', 'v-20']) // порядок по номеру, а не по порядку в списке
  })

  it('список VLAN подинтерфейса — плавающий: не обрезается прокручиваемой таблицей (overflow-x: auto)', () => {
    const wrapper = mountEditor([emptySubinterface('Gi0/0')])
    expect(vlanSelects(wrapper)[0].props('floating')).toBe(true)
  })

  it('выбор VLAN подставляет имя «<порт>.<VLAN>», если имя пустое', async () => {
    const wrapper = mountEditor([emptySubinterface('Gi0/0')])
    vlanSelects(wrapper)[0].vm.$emit('update:modelValue', 'v-10')

    expect(lastEmitted(wrapper)[0]).toMatchObject({ vlan_id: 'v-10', name: 'Gi0/0.10' })
  })

  it('смена VLAN обновляет автоимя, но не затирает имя, введённое вручную', async () => {
    const auto = mountEditor([emptySubinterface('Gi0/0', vlans[1])]) // Gi0/0.10 — автоимя
    vlanSelects(auto)[0].vm.$emit('update:modelValue', 'v-20')
    expect(lastEmitted(auto)[0]).toMatchObject({ vlan_id: 'v-20', name: 'Gi0/0.20' })

    const manual = mountEditor([{ ...emptySubinterface('Gi0/0', vlans[1]), name: 'wan-uplink' }])
    vlanSelects(manual)[0].vm.$emit('update:modelValue', 'v-20')
    expect(lastEmitted(manual)[0]).toMatchObject({ vlan_id: 'v-20', name: 'wan-uplink' })
  })

  it('VLAN, уже выбранные другими подинтерфейсами порта, скрыты из списка; свой собственный остаётся', () => {
    const third: VLANDefinition = { id: 'v-30', vlan_id: 30, name: 'Резерв', description: '', domain_id: null, domain_name: '', devices: [] }
    const first = emptySubinterface('Gi0/0', vlans[1]) // v-10
    const second = emptySubinterface('Gi0/0', vlans[0]) // v-20
    const wrapper = mountEditor([first, second], { vlanOptions: [...vlans, third] })

    const [firstSelect, secondSelect] = vlanSelects(wrapper)
    expect(optionValues(firstSelect)).toEqual(['v-10', 'v-30']) // v-20 занят вторым — скрыт, свой v-10 доступен
    expect(optionValues(secondSelect)).toEqual(['v-20', 'v-30'])
  })

  it('VLAN, не выбранный на порту, не пропадает молча: пометка и предупреждение', () => {
    // VLAN 99 есть у устройства, но с порта убран: в списке порта его нет
    const wrapper = mountEditor([{ ...emptySubinterface('Gi0/0'), name: 'Gi0/0.99', vlan_id: 'v-gone' }], {
      deviceVlanIds: new Set(['v-gone', 'v-10', 'v-20']),
    })

    expect(vlanSelects(wrapper)[0].classes()).toContain('is-stale')
    expect(wrapper.find('[role="alert"]').text()).toContain('не выбран на этом порту')
  })

  it('VLAN, снятый с устройства, объясняется отдельным текстом', () => {
    const wrapper = mountEditor([{ ...emptySubinterface('Gi0/0'), name: 'Gi0/0.99', vlan_id: 'v-gone' }], { deviceVlanIds: new Set(['v-10', 'v-20']) })

    expect(wrapper.find('[role="alert"]').text()).toContain('больше не назначен устройству')
  })

  describe('разворачиваемый столбец IP-адресов и масок', () => {
    const withIps = () => ({
      ...emptySubinterface('Gi0/0', vlans[1]),
      ips: [
        { id: 'ip-1', ip_address: '10.0.10.1', prefix_length: '24', purpose: '' },
        { id: 'ip-2', ip_address: '10.0.10.2', prefix_length: '', purpose: '' },
      ],
    })

    it('по умолчанию свёрнут: в строке адреса с масками, форм IP и открытых портов нет', () => {
      const wrapper = mountEditor([withIps()])

      expect(wrapper.find('.expand-toggle').text()).toContain('10.0.10.1/24, 10.0.10.2')
      expect(wrapper.find('.sub-detail-row').exists()).toBe(false)
      expect(wrapper.find('input[aria-label="IP-адрес подинтерфейса"]').exists()).toBe(false)
    })

    it('без адресов в свёрнутом столбце написано «нет IP»; число открытых портов видно и в свёрнутом виде', () => {
      const wrapper = mountEditor([
        { ...emptySubinterface('Gi0/0', vlans[1]), open_ports: [{ protocol_catalog_id: 'cat-ssh', transport_protocol: 'TCP', description: '' }] },
      ])

      expect(wrapper.find('.expand-toggle').text()).toContain('нет IP')
      expect(wrapper.find('.expand-toggle').text()).toContain('портов: 1')
    })

    it('по клику разворачивается: формы IP-адресов и открытых портов, повторный клик сворачивает', async () => {
      const wrapper = mountEditor([withIps()])

      await expandRow(wrapper)
      expect(wrapper.find('.expand-toggle').attributes('aria-expanded')).toBe('true')
      expect(wrapper.findAll('input[aria-label="IP-адрес подинтерфейса"]')).toHaveLength(2)
      expect(wrapper.find('.add-btn').exists()).toBe(true) // «+ Открытый порт» вложенного редактора

      await expandRow(wrapper)
      expect(wrapper.find('.sub-detail-row').exists()).toBe(false)
    })

    it('раскрывается только нажатая строка', async () => {
      const wrapper = mountEditor([withIps(), emptySubinterface('Gi0/0', vlans[0])])

      await expandRow(wrapper, 1)

      expect(wrapper.findAll('.sub-detail-row')).toHaveLength(1)
      expect(wrapper.findAll('.expand-toggle')[0].attributes('aria-expanded')).toBe('false')
    })
  })

  describe('подинтерфейсы заданы группой (readonly) и шаблон группы (mode="group")', () => {
    it('readonly: поля выключены, добавления и удаления нет, пояснение показано', () => {
      const wrapper = mountEditor([emptySubinterface('Gi0/0', vlans[1])], { readonly: true, readonlyNote: 'Список подинтерфейсов задан группой «Серверные»' })

      expect(wrapper.text()).toContain('задан группой «Серверные»')
      expect(wrapper.find('.sub-head button').exists()).toBe(false)
      expect(wrapper.find('button[aria-label="Удалить подинтерфейс"]').exists()).toBe(false)
      expect(wrapper.find('input[aria-label="Имя подинтерфейса"]').attributes('disabled')).toBeDefined()
      expect(vlanSelects(wrapper)[0].props('disabled')).toBe(true)
    })

    it('mode="group": вместо имени — образец «‹порт›.<VLAN>», поля имени нет; выбор VLAN имя не пишет', async () => {
      const wrapper = mountEditor([emptySubinterface('', vlans[1])], { mode: 'group', parentName: '' })

      expect(wrapper.find('input[aria-label="Имя подинтерфейса"]').exists()).toBe(false)
      expect(wrapper.find('.name-pattern').text()).toBe('‹порт›.10')

      vlanSelects(wrapper)[0].vm.$emit('update:modelValue', 'v-20')
      expect(lastEmitted(wrapper)[0]).toMatchObject({ vlan_id: 'v-20', name: '' })
    })

    it('mode="group" без VLAN группы: подсказка просит задать режим порта и VLAN группы', () => {
      const wrapper = mountEditor([], { mode: 'group', parentName: '', vlanOptions: [] })

      expect(wrapper.text()).toContain('задайте режим порта и VLAN группы')
      expect(wrapper.find('.sub-head button').attributes('disabled')).toBeDefined()
    })
  })

  describe('перенос подинтерфейса с недоступного VLAN прямо из предупреждения', () => {
    const reserve: VLANDefinition = { id: 'v-30', vlan_id: 30, name: 'Резерв', description: '', domain_id: null, domain_name: '', devices: [] }
    const staleSub = (patch: Partial<SubinterfaceDraftRow> = {}): SubinterfaceDraftRow => ({
      ...emptySubinterface('Gi0/0'),
      name: 'Gi0/0.30',
      vlan_id: 'v-30',
      ...patch,
    })
    const moveSelect = (wrapper: ReturnType<typeof mountEditor>) => wrapper.find('select[aria-label="Перенести подинтерфейс на VLAN"]')

    it('предупреждение называет прежний VLAN по справочнику, а список переноса содержит только свободные VLAN устройства', () => {
      const taken = emptySubinterface('Gi0/0', vlans[1]) // v-10 занят соседним подинтерфейсом порта
      const wrapper = mountEditor([staleSub(), taken], { vlanCatalog: [reserve] })

      expect(wrapper.find('.sub-warn').text()).toContain('(30 — Резерв)')
      const options = moveSelect(wrapper)
        .findAll('option')
        .map((o) => o.attributes('value'))
      expect(options).toEqual(['', 'v-20']) // v-10 занят соседом, v-30 устройству недоступен
    })

    it('выбор VLAN переносит подинтерфейс и пересчитывает автоимя по номеру прежнего VLAN из справочника', async () => {
      const wrapper = mountEditor([staleSub()], { vlanCatalog: [reserve] })
      await moveSelect(wrapper).setValue('v-10')

      expect(lastEmitted(wrapper)[0]).toMatchObject({ vlan_id: 'v-10', name: 'Gi0/0.10' })
    })

    it('имя, введённое вручную, при переносе сохраняется; без справочника автоимя (по номеру неизвестного VLAN) не угадывается', async () => {
      const manual = mountEditor([staleSub({ name: 'wan-uplink' })], { vlanCatalog: [reserve] })
      await moveSelect(manual).setValue('v-10')
      expect(lastEmitted(manual)[0]).toMatchObject({ vlan_id: 'v-10', name: 'wan-uplink' })

      const noCatalog = mountEditor([staleSub()])
      await moveSelect(noCatalog).setValue('v-10')
      expect(lastEmitted(noCatalog)[0]).toMatchObject({ vlan_id: 'v-10', name: 'Gi0/0.30' })
    })

    it('если свободных VLAN нет — список переноса выключен и объясняет почему', () => {
      const wrapper = mountEditor([staleSub()], { vlanOptions: [] })
      expect(moveSelect(wrapper).attributes('disabled')).toBeDefined()
      expect(moveSelect(wrapper).attributes('title')).toContain('Нет свободных VLAN')
    })

    it('у подинтерфейса на доступном VLAN списка переноса нет', () => {
      expect(moveSelect(mountEditor([emptySubinterface('Gi0/0', vlans[1])])).exists()).toBe(false)
    })
  })

  it('правка имени, флагов и описания уходит в update:modelValue без потери остальных полей', async () => {
    const wrapper = mountEditor([emptySubinterface('Gi0/0', vlans[1])])

    await wrapper.find('input[aria-label="Имя подинтерфейса"]').setValue('mgmt.10')
    expect(lastEmitted(wrapper)[0]).toMatchObject({ name: 'mgmt.10', vlan_id: 'v-10' })

    await wrapper.find('input[aria-label="Подинтерфейс: управление"]').setValue(true)
    expect(lastEmitted(wrapper)[0].is_management).toBe(true)
    await wrapper.find('input[aria-label="Подинтерфейс: передача данных"]').setValue(true)
    expect(lastEmitted(wrapper)[0].is_data_transfer).toBe(true)

    await expandRow(wrapper) // описание — в раскрытой части строки
    await wrapper.find('input[aria-label="Описание подинтерфейса"]').setValue('Сеть серверов')
    expect(lastEmitted(wrapper)[0].description).toBe('Сеть серверов')
  })

  it('IP-адреса: добавление, правка и удаление', async () => {
    const wrapper = mountEditor([emptySubinterface('Gi0/0', vlans[1])])
    await expandRow(wrapper)

    await wrapper.find('.sub-ips-head button').trigger('click')
    expect(lastEmitted(wrapper)[0].ips).toEqual([{ ip_address: '', prefix_length: '', purpose: '' }])

    const withIp = mountEditor([{ ...emptySubinterface('Gi0/0', vlans[1]), ips: [{ id: 'ip-1', ip_address: '10.0.10.1', prefix_length: '24', purpose: '' }] }])
    await expandRow(withIp)
    await withIp.find('input[aria-label="IP-адрес подинтерфейса"]').setValue('10.0.10.2')
    expect(lastEmitted(withIp)[0].ips).toEqual([{ id: 'ip-1', ip_address: '10.0.10.2', prefix_length: '24', purpose: '' }])

    await withIp.find('button[aria-label="Удалить IP подинтерфейса"]').trigger('click')
    expect(lastEmitted(withIp)[0].ips).toEqual([])
  })

  it('открытые порты подинтерфейса редактируются вложенным редактором', async () => {
    const wrapper = mountEditor([emptySubinterface('Gi0/0', vlans[1])])
    await expandRow(wrapper)
    await wrapper.find('.add-btn').trigger('click') // «+ Открытый порт» вложенного OpenPortListEditor

    expect(lastEmitted(wrapper)[0].open_ports).toEqual([{ protocol_catalog_id: '', transport_protocol: 'TCP', description: '' }])
  })

  it('удаление подинтерфейса убирает только его строку', async () => {
    const wrapper = mountEditor([emptySubinterface('Gi0/0', vlans[1]), emptySubinterface('Gi0/0', vlans[0])])
    await wrapper.findAll('button[aria-label="Удалить подинтерфейс"]')[0].trigger('click')

    const rest = lastEmitted(wrapper)
    expect(rest).toHaveLength(1)
    expect(rest[0].vlan_id).toBe('v-20')
  })
})
