import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import NeighborReviewModal from '../NeighborReviewModal.vue'
import type { ReviewItem } from '../../utils/neighborReview'
import { makeRow } from '../../utils/__tests__/interfaceRowFixture'

const config = { is_management: false, is_data_transfer: true, vlan_mode: 'trunk' as const, all_vlans: false }
function item(patch: Partial<ReviewItem> & { name?: string; isSelf?: boolean } = {}): ReviewItem {
  const { name = 'Gi0/1', isSelf = false, ...rest } = patch
  return {
    key: `${name}>peer`,
    index: 0,
    row: makeRow({ name }),
    peer: { ref: 'p1', label: '«Gi0/9» (sw-02)', config, interfaceId: 'p1', isSelf },
    kinds: ['flags'],
    texts: ['«Управление»: да / у соседа нет'],
    ...rest,
  }
}

function mountModal(props: Partial<InstanceType<typeof NeighborReviewModal>['$props']> = {}) {
  return mount(NeighborReviewModal, { props: { items: [item()], busy: false, ...props } })
}

describe('NeighborReviewModal', () => {
  it('перечисляет расхождения: порт, сосед и что именно отличается; безымянный порт — «без имени»', () => {
    const wrapper = mountModal({ items: [item(), item({ name: '  ', key: 'k2', texts: ['режим порта', '«Все VLAN»'] })] })

    const entries = wrapper.findAll('.review-item')
    expect(entries).toHaveLength(2)
    expect(entries[0].get('.review-item-title').text()).toBe('Порт «Gi0/1» ↔ «Gi0/9» (sw-02)')
    expect(entries[0].get('.review-item-diffs').text()).toBe('«Управление»: да / у соседа нет')
    expect(entries[1].get('.review-item-title').text()).toContain('Порт «без имени»')
    expect(entries[1].get('.review-item-diffs').text()).toBe('режим порта; «Все VLAN»')
  })

  it('пометка «настройки изменятся сразу» — только у соседа с другого устройства', () => {
    const wrapper = mountModal({ items: [item(), item({ key: 'self', isSelf: true })] })

    const notes = wrapper.findAll('.review-item')
    expect(notes[0].find('.review-item-note').exists()).toBe(true)
    expect(notes[1].find('.review-item-note').exists()).toBe(false)
  })

  it('кнопки пункта отдают именно его пункт; на время применения они недоступны', async () => {
    const wrapper = mountModal({ items: [item(), item({ name: 'Gi0/2', key: 'second' })] })
    const [neighbor, current] = wrapper.findAll('.review-item')[1].findAll('.review-item-actions button')
    await neighbor.trigger('click')
    await current.trigger('click')
    expect(wrapper.emitted('apply-neighbor')![0][0]).toMatchObject({ key: 'second' })
    expect(wrapper.emitted('apply-current')![0][0]).toMatchObject({ key: 'second' })

    await wrapper.setProps({ busy: true })
    expect(wrapper.findAll('.review-item-actions button').every((b) => b.attributes('disabled') !== undefined)).toBe(true)
  })

  it('с расхождениями кнопка сохранения называется «Сохранить как есть»; без них — «Расхождений не осталось» и «Сохранить»', async () => {
    const wrapper = mountModal()
    expect(wrapper.get('.review-footer .btn-primary').text()).toBe('Сохранить как есть')

    await wrapper.setProps({ items: [] })
    expect(wrapper.get('.review-done').text()).toBe('Расхождений не осталось.')
    expect(wrapper.find('.review-list').exists()).toBe(false)
    expect(wrapper.get('.review-footer .btn-primary').text()).toBe('Сохранить')
  })

  it('finish: «Сохранить» — true; «Вернуться к форме», крестик и подложка — false', async () => {
    const wrapper = mountModal()
    await wrapper.get('.review-footer .btn-primary').trigger('click')
    await wrapper.get('.review-footer .btn-secondary').trigger('click')
    await wrapper.get('button[aria-label="Вернуться к форме"]').trigger('click')
    const overlay = wrapper.get('.overlay')
    await overlay.trigger('mousedown')
    await overlay.trigger('click')

    expect(wrapper.emitted('finish')!.map((e) => e[0])).toEqual([true, false, false, false])
  })

  it('это диалог-предупреждение: у окна роль alertdialog, подписанная заголовком', () => {
    const wrapper = mountModal()
    const dialog = wrapper.get('[role="alertdialog"]')
    expect(dialog.attributes('aria-labelledby')).toBe('neighbor-review-title')
    expect(wrapper.get('#neighbor-review-title').text()).toContain('расходятся с соседним портом')
  })
})
