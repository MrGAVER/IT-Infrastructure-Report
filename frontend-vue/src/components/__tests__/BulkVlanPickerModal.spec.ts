import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import BulkVlanPickerModal from '../BulkVlanPickerModal.vue'
import { makeVlan } from '../../utils/__tests__/interfaceRowFixture'

const vlans = [makeVlan('v10', 10, 'Гостевой'), makeVlan('v20', 20, 'Серверы')]

function mountModal(props: Partial<InstanceType<typeof BulkVlanPickerModal>['$props']> = {}) {
  return mount(BulkVlanPickerModal, { props: { vlanOptions: vlans, vlanMode: 'trunk', allVlans: false, selectedIds: new Set<string>(), ...props } })
}
const boxes = (wrapper: ReturnType<typeof mountModal>) => wrapper.findAll('.vlan-check:not(.vlan-check-all) input[type="checkbox"]')

describe('BulkVlanPickerModal', () => {
  it('галочки отражают набор из панели: отмечены только выбранные VLAN', () => {
    const wrapper = mountModal({ selectedIds: new Set(['v20']) })

    expect(boxes(wrapper).map((b) => (b.element as HTMLInputElement).checked)).toEqual([false, true])
    expect(wrapper.text()).toContain('10 — Гостевой')
  })

  it('«Все VLAN» есть только при режиме Trunk: для access (не более одного VLAN) он не имеет смысла', () => {
    expect(mountModal({ vlanMode: 'trunk' }).find('.vlan-check-all').exists()).toBe(true)
    expect(mountModal({ vlanMode: 'access' }).find('.vlan-check-all').exists()).toBe(false)
    expect(mountModal({ vlanMode: '' }).find('.vlan-check-all').exists()).toBe(false)
  })

  it('клики по галочкам уходят событиями: VLAN — с идентификатором и состоянием, «Все VLAN» — с состоянием', async () => {
    const wrapper = mountModal({ allVlans: true })
    expect((wrapper.get('.vlan-check-all input').element as HTMLInputElement).checked).toBe(true)

    await boxes(wrapper)[0].setValue(true)
    await wrapper.get('.vlan-check-all input').setValue(false)

    expect(wrapper.emitted('toggle-vlan')![0]).toEqual(['v10', true])
    expect(wrapper.emitted('toggle-all')![0]).toEqual([false])
  })

  it('закрывается крестиком, «Готово» и кликом по подложке, но не нажатием внутри карточки', async () => {
    const wrapper = mountModal()
    await wrapper.get('button[aria-label="Закрыть"]').trigger('click')
    await wrapper.get('.conflict-modal-actions button').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(2)

    const overlay = wrapper.get('.overlay')
    await overlay.trigger('mousedown')
    await overlay.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(3)

    // выделение текста в карточке, закончившееся на подложке, окно не закрывает
    await wrapper.get('.vlan-picker-modal').trigger('mousedown')
    await overlay.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(3)
  })
})
