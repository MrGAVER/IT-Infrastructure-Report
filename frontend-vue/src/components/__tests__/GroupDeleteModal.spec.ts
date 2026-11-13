import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import type { InterfaceGroupDraft } from '../../api/types'
import { emptyGroup } from '../../utils/interfaceGroups'
import GroupDeleteModal from '../GroupDeleteModal.vue'

function group(patch: Partial<InterfaceGroupDraft> = {}): InterfaceGroupDraft {
  return { ...emptyGroup('Серверные'), key: 'g1', ...patch }
}

function mountModal(g: InterfaceGroupDraft = group({ vlan_mode: 'access', vlan_ids: ['v10'] }), membersCount = 3) {
  return mount(GroupDeleteModal, { props: { group: g, membersCount } })
}

const buttons = (wrapper: ReturnType<typeof mountModal>) => wrapper.findAll('.delete-actions .btn')

describe('GroupDeleteModal', () => {
  it('в заголовке — имя группы, в описании — число портов и то, чем управляла группа', () => {
    const wrapper = mountModal(group({ name: 'Серверные', vlan_mode: 'access', vlan_ids: ['v10'] }), 3)

    expect(wrapper.get('h2').text()).toBe('Удалить группу «Серверные»?')
    expect(wrapper.get('.delete-desc').text()).toBe('В группе портов: 3. Группа задавала: режим порта и VLAN. Что сделать со значениями в этих портах?')
  })

  it('перечисляет все управляемые параметры в порядке: режим и VLAN, IP, открытые порты, подинтерфейсы', () => {
    const all = group({
      vlan_mode: 'trunk',
      ips: [{ ip_address: '10.0.0.5', prefix_length: '', purpose: '' }],
      manage_open_ports: true,
      manage_subinterfaces: true,
    })
    expect(mountModal(all).get('.delete-desc').text()).toContain('Группа задавала: режим порта и VLAN, IP-адрес, открытые порты, подинтерфейсы.')

    const some = group({ ips: [{ ip_address: '10.0.0.5', prefix_length: '', purpose: '' }], manage_subinterfaces: true })
    expect(mountModal(some).get('.delete-desc').text()).toContain('Группа задавала: IP-адрес, подинтерфейсы.')
  })

  it('три кнопки: «Оставить значения» и «Стереть значения» сообщают выбор, «Отмена» закрывает окно', async () => {
    const wrapper = mountModal()
    expect(buttons(wrapper).map((b) => b.text())).toEqual(['Оставить значения в портах', 'Стереть значения', 'Отмена'])

    await buttons(wrapper)[0].trigger('click')
    await buttons(wrapper)[1].trigger('click')
    await buttons(wrapper)[2].trigger('click')

    expect(wrapper.emitted('confirm')).toEqual([['keep'], ['erase']])
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('закрывается крестиком и кликом по подложке, но не нажатием внутри карточки', async () => {
    const wrapper = mountModal()
    await wrapper.get('button[aria-label="Закрыть"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)

    const overlay = wrapper.get('.modal-overlay')
    await overlay.trigger('mousedown')
    await overlay.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(2)

    // выделение текста в карточке, закончившееся на подложке, окно не закрывает
    await wrapper.get('.delete-modal').trigger('mousedown')
    await overlay.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(2)
    expect(wrapper.emitted('confirm')).toBeUndefined()
  })

  it('окно — диалог с понятным именем для вспомогательных технологий', () => {
    const dialog = mountModal().get('[role="dialog"]')
    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(dialog.attributes('aria-label')).toBe('Удаление группы портов')
  })
})
