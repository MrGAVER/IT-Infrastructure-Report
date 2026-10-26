import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import InterfaceBulkBar from '../InterfaceBulkBar.vue'

const types = [{ id: 't-eth', name: 'Ethernet' }, { id: 't-sfp', name: 'SFP+' }]
const speeds = [{ id: 's-1g', name: '1 Гбит/с' }]

function mountBar(props: Record<string, unknown> = {}) {
  // строка таблицы монтируется внутрь <table>: иначе браузерный разбор DOM отбросит <tr>
  return mount(InterfaceBulkBar, {
    props: { typeId: '', speedId: '', management: '', dataTransfer: '', vlanMode: '', typeOptions: types, speedOptions: speeds, hasVlans: true, vlanSummary: '— выбрать VLAN —', ...props },
    attachTo: (() => {
      const table = document.createElement('table')
      const tbody = document.createElement('tbody')
      table.append(tbody)
      document.body.append(table)
      return tbody
    })(),
  })
}
const select = (wrapper: ReturnType<typeof mountBar>, label: string) => wrapper.get(`select[aria-label="${label} — массовое редактирование"]`)

describe('InterfaceBulkBar', () => {
  it('поля панели — «не менять» по умолчанию; тип и скорость берут варианты из справочников', () => {
    const wrapper = mountBar()

    expect(select(wrapper, 'Тип интерфейса').findAll('option').map((o) => o.text())).toEqual(['— не менять —', 'Ethernet', 'SFP+'])
    expect(select(wrapper, 'Скорость').findAll('option').map((o) => o.text())).toEqual(['— не менять —', '1 Гбит/с'])
    expect(select(wrapper, 'Управление').findAll('option').map((o) => o.attributes('value'))).toEqual(['', 'true', 'false'])
    wrapper.unmount()
  })

  it('выбор в каждом поле уходит в свой v-model', async () => {
    const wrapper = mountBar()

    await select(wrapper, 'Тип интерфейса').setValue('t-sfp')
    await select(wrapper, 'Скорость').setValue('s-1g')
    await select(wrapper, 'Управление').setValue('true')
    await select(wrapper, 'Передача данных').setValue('false')
    await select(wrapper, 'Режим порта').setValue('trunk')

    expect(wrapper.emitted('update:typeId')![0]).toEqual(['t-sfp'])
    expect(wrapper.emitted('update:speedId')![0]).toEqual(['s-1g'])
    expect(wrapper.emitted('update:management')![0]).toEqual(['true'])
    expect(wrapper.emitted('update:dataTransfer')![0]).toEqual(['false'])
    expect(wrapper.emitted('update:vlanMode')![0]).toEqual(['trunk'])
    wrapper.unmount()
  })

  it('значения показываются из v-model, а не копятся внутри строки', () => {
    const wrapper = mountBar({ typeId: 't-eth', dataTransfer: 'true', vlanMode: 'access' })

    expect((select(wrapper, 'Тип интерфейса').element as HTMLSelectElement).value).toBe('t-eth')
    expect((select(wrapper, 'Передача данных').element as HTMLSelectElement).value).toBe('true')
    expect((select(wrapper, 'Режим порта').element as HTMLSelectElement).value).toBe('access')
    wrapper.unmount()
  })

  it('VLAN: кнопка с сводкой открывает окно выбора; без VLAN у устройства вместо неё пометка', async () => {
    const wrapper = mountBar({ vlanSummary: 'Выбрано VLAN: 2' })
    await wrapper.get('.vlan-picker-btn').trigger('click')
    expect(wrapper.get('.vlan-picker-btn').text()).toBe('Выбрано VLAN: 2')
    expect(wrapper.emitted('open-vlan-picker')).toHaveLength(1)

    await wrapper.setProps({ hasVlans: false })
    expect(wrapper.find('.vlan-picker-btn').exists()).toBe(false)
    expect(wrapper.get('.empty').text()).toBe('VLAN не назначены')
    wrapper.unmount()
  })

  it('галочка в последней колонке просит применить заполненные поля', async () => {
    const wrapper = mountBar()
    await wrapper.get('button[aria-label="Применить к выбранным"]').trigger('click')
    expect(wrapper.emitted('apply')).toHaveLength(1)
    wrapper.unmount()
  })
})
