import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InterfaceSubinterfacesEditor from '../InterfaceSubinterfacesEditor.vue'
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

  it('если у устройства нет VLAN — добавить подинтерфейс нельзя, подсказка объясняет почему', () => {
    const wrapper = mountEditor([], { vlanOptions: [] })
    expect(wrapper.find('.sub-head button').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('назначьте устройству VLAN')
  })

  it('выбор VLAN подставляет имя «<порт>.<VLAN>», если имя пустое', async () => {
    const wrapper = mountEditor([emptySubinterface('Gi0/0')])
    await wrapper.find('select[aria-label="VLAN подинтерфейса"]').setValue('v-10')

    expect(lastEmitted(wrapper)[0]).toMatchObject({ vlan_id: 'v-10', name: 'Gi0/0.10' })
  })

  it('смена VLAN обновляет автоимя, но не затирает имя, введённое вручную', async () => {
    const auto = mountEditor([emptySubinterface('Gi0/0', vlans[1])]) // Gi0/0.10 — автоимя
    await auto.find('select[aria-label="VLAN подинтерфейса"]').setValue('v-20')
    expect(lastEmitted(auto)[0]).toMatchObject({ vlan_id: 'v-20', name: 'Gi0/0.20' })

    const manual = mountEditor([{ ...emptySubinterface('Gi0/0', vlans[1]), name: 'wan-uplink' }])
    await manual.find('select[aria-label="VLAN подинтерфейса"]').setValue('v-20')
    expect(lastEmitted(manual)[0]).toMatchObject({ vlan_id: 'v-20', name: 'wan-uplink' })
  })

  it('VLAN, занятый соседним подинтерфейсом порта, в списке выключен; свой собственный — доступен', () => {
    const first = emptySubinterface('Gi0/0', vlans[1]) // v-10
    const second = emptySubinterface('Gi0/0', vlans[0]) // v-20
    const wrapper = mountEditor([first, second])

    const selects = wrapper.findAll('select[aria-label="VLAN подинтерфейса"]')
    const optionOf = (selectIndex: number, vlanId: string) => selects[selectIndex].find(`option[value="${vlanId}"]`)
    expect(optionOf(0, 'v-20').attributes('disabled')).toBeDefined() // занят вторым
    expect(optionOf(0, 'v-10').attributes('disabled')).toBeUndefined() // свой
    expect(optionOf(1, 'v-10').attributes('disabled')).toBeDefined()
  })

  it('VLAN, недоступный устройству, не пропадает молча: пометка и предупреждение', () => {
    const wrapper = mountEditor([{ ...emptySubinterface('Gi0/0'), name: 'Gi0/0.99', vlan_id: 'v-gone' }])
    expect(wrapper.find('select[aria-label="VLAN подинтерфейса"]').classes()).toContain('is-stale')
    expect(wrapper.find('[role="alert"]').text()).toContain('больше не назначен устройству')
  })

  describe('перенос подинтерфейса с недоступного VLAN прямо из предупреждения', () => {
    const reserve: VLANDefinition = { id: 'v-30', vlan_id: 30, name: 'Резерв', description: '', domain_id: null, domain_name: '', devices: [] }
    const staleSub = (patch: Partial<SubinterfaceDraftRow> = {}): SubinterfaceDraftRow => ({ ...emptySubinterface('Gi0/0'), name: 'Gi0/0.30', vlan_id: 'v-30', ...patch })
    const moveSelect = (wrapper: ReturnType<typeof mountEditor>) => wrapper.find('select[aria-label="Перенести подинтерфейс на VLAN"]')

    it('предупреждение называет прежний VLAN по справочнику, а список переноса содержит только свободные VLAN устройства', () => {
      const taken = emptySubinterface('Gi0/0', vlans[1]) // v-10 занят соседним подинтерфейсом порта
      const wrapper = mountEditor([staleSub(), taken], { vlanCatalog: [reserve] })

      expect(wrapper.find('.sub-warn').text()).toContain('(30 — Резерв)')
      const options = moveSelect(wrapper).findAll('option').map((o) => o.attributes('value'))
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

    const [management, dataTransfer] = wrapper.findAll('.flag input')
    await management.setValue(true)
    expect(lastEmitted(wrapper)[0].is_management).toBe(true)
    await dataTransfer.setValue(true)
    expect(lastEmitted(wrapper)[0].is_data_transfer).toBe(true)

    await wrapper.find('input[aria-label="Описание подинтерфейса"]').setValue('Сеть серверов')
    expect(lastEmitted(wrapper)[0].description).toBe('Сеть серверов')
  })

  it('IP-адреса: добавление, правка и удаление', async () => {
    const wrapper = mountEditor([emptySubinterface('Gi0/0', vlans[1])])

    await wrapper.find('.sub-ips-head button').trigger('click')
    expect(lastEmitted(wrapper)[0].ips).toEqual([{ ip_address: '', prefix_length: '', purpose: '' }])

    const withIp = mountEditor([{ ...emptySubinterface('Gi0/0', vlans[1]), ips: [{ id: 'ip-1', ip_address: '10.0.10.1', prefix_length: '24', purpose: '' }] }])
    await withIp.find('input[aria-label="IP-адрес подинтерфейса"]').setValue('10.0.10.2')
    expect(lastEmitted(withIp)[0].ips).toEqual([{ id: 'ip-1', ip_address: '10.0.10.2', prefix_length: '24', purpose: '' }])

    await withIp.find('button[aria-label="Удалить IP подинтерфейса"]').trigger('click')
    expect(lastEmitted(withIp)[0].ips).toEqual([])
  })

  it('открытые порты подинтерфейса редактируются вложенным редактором', async () => {
    const wrapper = mountEditor([emptySubinterface('Gi0/0', vlans[1])])
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
