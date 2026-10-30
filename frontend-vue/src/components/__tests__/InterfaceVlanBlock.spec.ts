import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import InterfaceVlanBlock from '../InterfaceVlanBlock.vue'
import SearchableSelect from '../SearchableSelect.vue'
import { makeConflict, makeRow, makeVlan } from '../../utils/__tests__/interfaceRowFixture'

const vlans = [makeVlan('v10', 10, 'Гостевой'), makeVlan('v20', 20, 'Серверы')]

function mountBlock(props: Partial<InstanceType<typeof InterfaceVlanBlock>['$props']> = {}) {
  return mount(InterfaceVlanBlock, {
    props: {
      row: makeRow({ vlan_mode: 'trunk', vlan_ids: ['v10'] }),
      index: 0,
      vlanOptions: vlans,
      allVlans: false,
      managed: false,
      lockNote: '',
      conflict: undefined,
      ...props,
    },
  })
}
const radios = (wrapper: ReturnType<typeof mountBlock>) => wrapper.findAll('input[type="radio"]')

describe('InterfaceVlanBlock', () => {
  it('режим порта: Trunk и Access с общим name на строку; отмечен текущий режим, смена уходит событием', async () => {
    const wrapper = mountBlock({ index: 3 })
    const [trunk, access] = radios(wrapper)

    expect(trunk.attributes('name')).toBe('vlan-mode-3')
    expect(access.attributes('name')).toBe('vlan-mode-3')
    expect((trunk.element as HTMLInputElement).checked).toBe(true)
    expect((access.element as HTMLInputElement).checked).toBe(false)

    await access.trigger('change')
    await trunk.trigger('change')
    expect(wrapper.emitted('set-mode')!.map((e) => e[0])).toEqual(['access', 'trunk'])
  })

  it('Access отмечен только у access-порта, у остальных отмечен Trunk', () => {
    const wrapper = mountBlock({ row: makeRow({ vlan_mode: 'access' }) })
    const [trunk, access] = radios(wrapper)
    expect((trunk.element as HTMLInputElement).checked).toBe(false)
    expect((access.element as HTMLInputElement).checked).toBe(true)
  })

  it('trunk: сводка выбранных VLAN, «Все VLAN» из признака порта и кнопка окна выбора', async () => {
    const wrapper = mountBlock({ allVlans: true })

    expect(wrapper.get('.vlan-summary').text()).toBe('Выбрано VLAN: 1 из 2')
    expect((wrapper.get('.vlan-check-all input').element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.get('.vlan-picker-btn').text()).toBe('Выбрать VLAN…')

    await wrapper.get('.vlan-check-all input').setValue(false)
    await wrapper.get('.vlan-picker-btn').trigger('click')
    expect(wrapper.emitted('toggle-all')![0]).toEqual([false])
    expect(wrapper.emitted('open-picker')).toHaveLength(1)
  })

  it('access: один VLAN выбирается в списке с поиском, выбор уходит событием', async () => {
    const wrapper = mountBlock({ row: makeRow({ vlan_mode: 'access', vlan_ids: ['v20'] }) })
    const select = wrapper.getComponent(SearchableSelect)

    expect(select.props('modelValue')).toBe('v20')
    expect((select.props('options') as { value: string; label: string }[]).map((o) => o.value)).toEqual(['v10', 'v20'])
    await select.vm.$emit('update:modelValue', 'v10')
    expect(wrapper.emitted('set-access-vlan')![0]).toEqual(['v10'])
    expect(wrapper.find('.vlan-check-all').exists()).toBe(false)
  })

  it('без VLAN у устройства вместо выбора — пометка, и в access, и в trunk', () => {
    for (const mode of ['access', 'trunk'] as const) {
      const wrapper = mountBlock({ row: makeRow({ vlan_mode: mode }), vlanOptions: [] })
      expect(wrapper.get('.empty').text()).toBe('Для типа устройства VLAN не назначены')
      expect(wrapper.find('.vlan-picker-btn').exists()).toBe(false)
      expect(wrapper.find('.searchable-select').exists()).toBe(false)
    }
  })

  it('режим и VLAN задаёт группа: радиокнопки и «Все VLAN» заблокированы, подсказка показана, кнопка окна — «Показать VLAN…»', () => {
    const wrapper = mountBlock({ managed: true, lockNote: 'Режим порта и VLAN задан группой «Магистраль»' })

    expect(radios(wrapper).every((r) => r.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.get('.vlan-check-all input').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.group-lock').text()).toContain('«Магистраль»')
    expect(wrapper.get('.vlan-picker-btn').text()).toBe('Показать VLAN…')
  })

  it('расхождение с соседом: значок у режима порта и у «Все VLAN» открывает своё окно решения', async () => {
    const wrapper = mountBlock({ conflict: makeConflict({ vlanModeDiffer: true, allVlansDiffer: true }) })

    const buttons = wrapper.findAll('.conflict-icon-btn')
    expect(buttons).toHaveLength(2)
    await wrapper.get('.vlan-mode-row .conflict-icon-btn').trigger('click')
    await wrapper.get('[data-testid="all-vlans-conflict"]').trigger('click')
    expect(wrapper.emitted('open-conflict')!.map((e) => e[0])).toEqual(['vlan_mode', 'all_vlans'])
  })

  it('без расхождения значков нет', () => {
    expect(mountBlock({ conflict: makeConflict() }).find('.conflict-icon-btn').exists()).toBe(false)
    expect(mountBlock().find('.conflict-icon-btn').exists()).toBe(false)
  })

  it('значок расхождения «Все VLAN» есть только в trunk: в access ему негде показаться', () => {
    const wrapper = mountBlock({ row: makeRow({ vlan_mode: 'access' }), conflict: makeConflict({ allVlansDiffer: true }) })
    expect(wrapper.find('[data-testid="all-vlans-conflict"]').exists()).toBe(false)
  })
})
