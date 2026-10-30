import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { InterfaceDraftRow, InterfaceGroupDraft } from '../../api/types'
import { emptyGroup } from '../../utils/interfaceGroups'
import { makeRow, makeVlan } from '../../utils/__tests__/interfaceRowFixture'
import { useToast } from '../../composables/useToast'
import GroupEditModal from '../GroupEditModal.vue'
import GroupVlanPickerModal from '../GroupVlanPickerModal.vue'
import InterfaceSubinterfacesEditor from '../InterfaceSubinterfacesEditor.vue'
import OpenPortListEditor from '../OpenPortListEditor.vue'

const vlans = [makeVlan('v10', 10, 'Серверы'), makeVlan('v20', 20, 'Гости')]

function newGroup(patch: Partial<InterfaceGroupDraft> = {}): InterfaceGroupDraft {
  return { ...emptyGroup(), key: 'g1', ...patch }
}

type Props = InstanceType<typeof GroupEditModal>['$props']
function mountModal(props: Partial<Props> = {}) {
  const rows: InterfaceDraftRow[] = [makeRow({ name: 'Gi0/1' }), makeRow({ name: 'Gi0/2' }), makeRow({ name: '' })]
  return mount(GroupEditModal, { props: { group: newGroup(), isNew: true, members: new Set<number>(), rows, groups: [], vlanOptions: vlans, protocolPortCatalog: [], ...props } })
}
type Wrapper = ReturnType<typeof mountModal>

const saved = (wrapper: Wrapper) => wrapper.emitted('save')![0][0] as { group: InterfaceGroupDraft; members: Set<number> }
const save = (wrapper: Wrapper) => wrapper.get('.group-modal-actions .btn-primary').trigger('click')
const mode = (wrapper: Wrapper, i: number) => wrapper.findAll('input[name="group-mode"]')[i]

beforeEach(() => {
  setActivePinia(createPinia())
  useToast().toasts.splice(0)
})

describe('GroupEditModal', () => {
  it('новая группа: заголовок и кнопка «Создать группу»; правка: «Группа портов» и «Применить»', () => {
    const created = mountModal({ isNew: true })
    expect(created.get('h2').text()).toBe('Новая группа портов')
    expect(created.get('[role="dialog"]').attributes('aria-label')).toBe('Новая группа портов')
    expect(created.get('.group-modal-actions .btn-primary').text()).toBe('Создать группу')

    const edited = mountModal({ isNew: false })
    expect(edited.get('h2').text()).toBe('Группа портов')
    expect(edited.get('.group-modal-actions .btn-primary').text()).toBe('Применить')
  })

  it('поля заполнены из группы, а состав — из переданных индексов портов', () => {
    const wrapper = mountModal({ group: newGroup({ name: 'Серверные', ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'mgmt' }] }), members: new Set([0, 2]) })

    expect((wrapper.get('.group-modal .field input').element as HTMLInputElement).value).toBe('Серверные')
    expect((wrapper.get('input[aria-label="Общий IP-адрес группы"]').element as HTMLInputElement).value).toBe('10.0.0.5')
    expect((wrapper.get('input[aria-label="Префикс общего IP-адреса"]').element as HTMLInputElement).value).toBe('24')
    expect((wrapper.get('input[aria-label="Назначение общего IP-адреса группы"]').element as HTMLInputElement).value).toBe('mgmt')
    expect(wrapper.findAll('.member-check input').map((c) => (c.element as HTMLInputElement).checked)).toEqual([true, false, true])
    expect(wrapper.findAll('.member-name').map((n) => n.text())).toEqual(['Gi0/1', 'Gi0/2', '#3'])
  })

  it('«Создать группу» отдаёт черновик и состав событием save; окно закрывается только родителем', async () => {
    const wrapper = mountModal()
    await wrapper.get('.group-modal .field input').setValue('Серверные')
    await wrapper.findAll('.member-check input')[1].setValue(true)
    await save(wrapper)

    const { group, members } = saved(wrapper)
    expect(group).toMatchObject({ key: 'g1', name: 'Серверные' })
    expect([...members]).toEqual([1])
    expect(wrapper.emitted('close')).toBeUndefined()
  })

  it('окно правит копию: переданная группа и состав остаются прежними, пока родитель не примет save', async () => {
    const original = newGroup({ name: 'Старое', vlan_mode: 'trunk', vlan_ids: ['v10'] })
    const members = new Set([0])
    const wrapper = mountModal({ group: original, members, isNew: false })

    await wrapper.get('.group-modal .field input').setValue('Новое')
    await wrapper.findAll('.member-check input')[2].setValue(true)
    await mode(wrapper, 0).trigger('change')

    expect(original).toMatchObject({ name: 'Старое', vlan_mode: 'trunk', vlan_ids: ['v10'] })
    expect([...members]).toEqual([0])
  })

  it('снятая галочка убирает порт из состава', async () => {
    const wrapper = mountModal({ members: new Set([0, 1]) })
    await wrapper.findAll('.member-check input')[0].setValue(false)
    await save(wrapper)

    expect([...saved(wrapper).members]).toEqual([1])
  })

  it('порт другой группы можно забрать, но окно предупреждает: «перейдёт из группы»', () => {
    const rows = [makeRow({ name: 'Gi0/1', group_key: 'g2' }), makeRow({ name: 'Gi0/2', group_key: 'g1' }), makeRow({ name: 'Gi0/3', group_key: 'gone' }), makeRow({ name: 'Gi0/4' })]
    const groups = [{ ...emptyGroup('Эта же'), key: 'g1' }, { ...emptyGroup('Соседняя'), key: 'g2' }]
    const wrapper = mountModal({ rows, group: newGroup({ name: 'Эта же' }), groups, isNew: false })

    // g2 — другая группа, g1 — эта же (она есть в списке групп, но порт и так в ней), gone — группы нет в списке, у четвёртого порта группы нет
    expect(wrapper.findAll('.member-note').map((n) => n.text())).toEqual(['перейдёт из группы «Соседняя»'])
  })

  it('без портов в списке вместо состава — подсказка', () => {
    const wrapper = mountModal({ rows: [] })
    expect(wrapper.find('.member-grid').exists()).toBe(false)
    expect(wrapper.get('.nested-editor .empty').text()).toBe('В списке нет портов.')
  })

  describe('режим порта и VLAN', () => {
    it('Trunk сразу отмечает «Все VLAN»: сводка «2 из 2», признак уходит в черновик', async () => {
      const wrapper = mountModal()
      await mode(wrapper, 2).trigger('change')

      expect(wrapper.get('.vlan-summary').text()).toBe('Выбрано VLAN: 2 из 2')
      expect((wrapper.get('.vlan-check-all input').element as HTMLInputElement).checked).toBe(true)
      await save(wrapper)
      expect(saved(wrapper).group).toMatchObject({ vlan_mode: 'trunk', all_vlans: true, vlan_ids: ['v10', 'v20'] })
    })

    it('снятие «Все VLAN» очищает набор; Access оставляет один VLAN', async () => {
      const wrapper = mountModal()
      await mode(wrapper, 2).trigger('change')
      await wrapper.get('.vlan-check-all input').setValue(false)
      expect(wrapper.get('.vlan-summary').text()).toBe('Выбрано VLAN: 0 из 2')

      await wrapper.get('.vlan-check-all input').setValue(true)
      await mode(wrapper, 1).trigger('change')
      expect(wrapper.find('.trunk-row').exists()).toBe(false)
      await save(wrapper)
      expect(saved(wrapper).group).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'], all_vlans: false })
    })

    it('Access: VLAN выбирается из списка устройства и сохраняется единственным', async () => {
      const wrapper = mountModal()
      await mode(wrapper, 1).trigger('change')
      const select = wrapper.get('.vlan-param .searchable-select')
      await select.get('input').trigger('focus')
      await select.findAll('.ss-option')[1].trigger('mousedown')
      await save(wrapper)

      expect(saved(wrapper).group).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v20'] })
    })

    it('у устройства без VLAN Trunk показывает пояснение вместо «Все VLAN»', async () => {
      const wrapper = mountModal({ vlanOptions: [] })
      await mode(wrapper, 2).trigger('change')

      expect(wrapper.get('.trunk-row .empty').text()).toBe('Для типа устройства VLAN не назначены')
      expect(wrapper.find('.vlan-check-all').exists()).toBe(false)
    })

    it('окно выбора VLAN открывается кнопкой, выбор в нём снимает «Все VLAN», «Готово» закрывает окно', async () => {
      const wrapper = mountModal()
      await mode(wrapper, 2).trigger('change')
      expect(wrapper.findComponent(GroupVlanPickerModal).exists()).toBe(false)

      await wrapper.get('.vlan-picker-btn').trigger('click')
      const picker = wrapper.getComponent(GroupVlanPickerModal)
      expect(picker.props()).toMatchObject({ allVlans: true, vlanIds: ['v10', 'v20'] })

      await picker.findAll('.vlan-picker-list .check-inline:not(.vlan-check-all) input')[1].setValue(false)
      expect(wrapper.get('.vlan-summary').text()).toBe('Выбрано VLAN: 1 из 2')
      expect((wrapper.get('.vlan-check-all input').element as HTMLInputElement).checked).toBe(false)

      await picker.get('.modal-foot .btn-primary').trigger('click')
      expect(wrapper.findComponent(GroupVlanPickerModal).exists()).toBe(false)
      await save(wrapper)
      expect(saved(wrapper).group).toMatchObject({ vlan_ids: ['v10'], all_vlans: false })
    })

    it('«Все VLAN» из окна выбора действует так же, как из окна группы', async () => {
      const wrapper = mountModal()
      await mode(wrapper, 2).trigger('change')
      await wrapper.get('.vlan-check-all input').setValue(false)
      await wrapper.get('.vlan-picker-btn').trigger('click')
      await wrapper.getComponent(GroupVlanPickerModal).get('.vlan-check-all input').setValue(true)

      expect(wrapper.get('.vlan-summary').text()).toBe('Выбрано VLAN: 2 из 2')
    })
  })

  describe('общий IP-адрес', () => {
    it('префикс остаётся строкой, а «Назначение» недоступно, пока IP не указан', async () => {
      const wrapper = mountModal()
      const purpose = () => wrapper.get('input[aria-label="Назначение общего IP-адреса группы"]')
      expect(purpose().attributes('disabled')).toBeDefined()

      await wrapper.get('input[aria-label="Общий IP-адрес группы"]').setValue('10.0.0.5')
      await wrapper.get('input[aria-label="Префикс общего IP-адреса"]').setValue('24')
      await purpose().setValue('Администрирование')
      expect(purpose().attributes('disabled')).toBeUndefined()
      await save(wrapper)

      const { group } = saved(wrapper)
      expect(group.ips).toEqual([{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'Администрирование' }])
      expect(typeof group.ips[0].prefix_length).toBe('string')
    })

    it('можно задать несколько общих IP: второй адрес добавляется кнопкой и уходит в черновик вместе с первым', async () => {
      const wrapper = mountModal({ group: newGroup({ name: 'Серверные', ips: [{ id: 'gip-1', ip_address: '10.0.0.5', prefix_length: '24', purpose: 'Управление' }] }) })

      await wrapper.get('.group-ips .btn-secondary').trigger('click')
      const addresses = wrapper.findAll('input[aria-label="Общий IP-адрес группы"]')
      expect(addresses).toHaveLength(2)
      await addresses[1].setValue('10.0.1.5')
      await wrapper.findAll('input[aria-label="Назначение общего IP-адреса группы"]')[1].setValue('Данные')
      await save(wrapper)

      expect(saved(wrapper).group.ips).toEqual([
        { id: 'gip-1', ip_address: '10.0.0.5', prefix_length: '24', purpose: 'Управление' },
        { ip_address: '10.0.1.5', prefix_length: '', purpose: 'Данные' },
      ])
    })

    it('правка в окне не задевает исходную группу, пока не нажато «Применить» (копия списка IP глубокая)', async () => {
      const source = newGroup({ ips: [{ id: 'gip-1', ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] })
      const wrapper = mountModal({ group: source })

      await wrapper.get('input[aria-label="Общий IP-адрес группы"]').setValue('10.9.9.9')

      expect(source.ips[0].ip_address).toBe('10.0.0.5')
    })
  })

  describe('открытые порты и подинтерфейсы', () => {
    it('редакторы появляются только при включённых галочках', async () => {
      const wrapper = mountModal()
      expect(wrapper.findComponent(OpenPortListEditor).exists()).toBe(false)
      expect(wrapper.findComponent(InterfaceSubinterfacesEditor).exists()).toBe(false)

      await wrapper.get('.ports-param .manage-check input').setValue(true)
      await wrapper.get('input[aria-label="Задать подинтерфейсы"]').setValue(true)
      expect(wrapper.findComponent(OpenPortListEditor).exists()).toBe(true)
      expect(wrapper.findComponent(InterfaceSubinterfacesEditor).exists()).toBe(true)
      await save(wrapper)
      expect(saved(wrapper).group).toMatchObject({ manage_open_ports: true, manage_subinterfaces: true })
    })

    it('VLAN подинтерфейсов — VLAN группы: без режима и у access без VLAN пусто, у access выбранный, у trunk с «Все VLAN» — все VLAN устройства', async () => {
      const wrapper = mountModal()
      await wrapper.get('input[aria-label="Задать подинтерфейсы"]').setValue(true)
      const options = () => wrapper.getComponent(InterfaceSubinterfacesEditor).props('vlanOptions').map((v: { id: string }) => v.id)
      expect(options()).toEqual([])

      await mode(wrapper, 1).trigger('change')
      expect(options()).toEqual([])
      const select = wrapper.get('.vlan-param .searchable-select')
      await select.get('input').trigger('focus')
      await select.findAll('.ss-option')[1].trigger('mousedown')
      expect(options()).toEqual(['v20'])
      await mode(wrapper, 2).trigger('change')
      expect(options()).toEqual(['v10', 'v20'])
      expect(wrapper.getComponent(InterfaceSubinterfacesEditor).props('vlanCatalog')).toHaveLength(2)
    })

    it('шаблоны подинтерфейсов, изменённые в редакторе, попадают в черновик', async () => {
      const wrapper = mountModal({ group: newGroup({ vlan_mode: 'access', vlan_ids: ['v10'], manage_subinterfaces: true }) })
      const template = { key: 's1', name: '', vlan_id: 'v10', is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [] }
      wrapper.getComponent(InterfaceSubinterfacesEditor).vm.$emit('update:modelValue', [template])
      await wrapper.vm.$nextTick()
      await save(wrapper)

      expect(saved(wrapper).group.subinterfaces).toEqual([template])
    })
  })

  it('блок копирования с порта подставляет значения порта в поля окна', async () => {
    const rows = [makeRow({ name: 'Gi0/1', vlan_mode: 'access', vlan_ids: ['v20'], ips: [{ ip_address: '10.0.0.7', prefix_length: '24', purpose: 'mgmt' }] })]
    const wrapper = mountModal({ rows })
    const select = wrapper.get('.copy-row .searchable-select')
    await select.get('input').trigger('focus')
    await select.findAll('.ss-option')[0].trigger('mousedown')
    await wrapper.get('.copy-row .btn').trigger('click')

    expect((wrapper.get('input[aria-label="Общий IP-адрес группы"]').element as HTMLInputElement).value).toBe('10.0.0.7')
    expect((mode(wrapper, 1).element as HTMLInputElement).checked).toBe(true)
    await save(wrapper)
    expect(saved(wrapper).group).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v20'], ips: [{ ip_address: '10.0.0.7', prefix_length: '24', purpose: 'mgmt' }] })
  })

  it('закрывается крестиком, «Отмена» и кликом по подложке, но не нажатием внутри карточки', async () => {
    const wrapper = mountModal()
    await wrapper.get('button[aria-label="Закрыть"]').trigger('click')
    await wrapper.get('.group-modal-actions .btn-secondary').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(2)

    const overlay = wrapper.get('.overlay')
    await overlay.trigger('mousedown')
    await overlay.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(3)

    await wrapper.get('.group-modal').trigger('mousedown')
    await overlay.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(3)
    expect(wrapper.emitted('save')).toBeUndefined()
  })
})
