import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { InterfaceDraftRow, InterfaceGroupDraft } from '../../api/types'
import { emptyGroup } from '../../utils/interfaceGroups'
import { makeRow, makeVlan } from '../../utils/__tests__/interfaceRowFixture'
import { useToast } from '../../composables/useToast'
import GroupCopyBlock from '../GroupCopyBlock.vue'

const vlans = [makeVlan('v10', 10), makeVlan('v20', 20)]

function mountBlock(rows: InterfaceDraftRow[], draft: InterfaceGroupDraft = { ...emptyGroup('Группа'), key: 'g1' }) {
  return mount(GroupCopyBlock, { props: { rows, draft, vlanOptions: vlans, protocolPortCatalog: [] } })
}

async function choosePort(wrapper: ReturnType<typeof mountBlock>, label: string) {
  const select = wrapper.get('.copy-row .searchable-select')
  await select.get('input').trigger('focus')
  await select
    .findAll('.ss-option')
    .find((o) => o.text() === label)!
    .trigger('mousedown')
}

const checks = (wrapper: ReturnType<typeof mountBlock>) => wrapper.findAll('.copy-what .check-inline')

beforeEach(() => {
  setActivePinia(createPinia())
  useToast().toasts.splice(0)
})

describe('GroupCopyBlock', () => {
  it('пока порт не выбран, параметры не показываются, а «Скопировать» недоступна', () => {
    const wrapper = mountBlock([makeRow({ name: 'Gi0/1', vlan_ids: ['v10'] })])

    expect(wrapper.find('.copy-what').exists()).toBe(false)
    expect(wrapper.get('.copy-row .btn').attributes('disabled')).toBeDefined()
  })

  it('выбор порта показывает четыре параметра: доступны (и отмечены) только те, что есть на порту', async () => {
    const wrapper = mountBlock([makeRow({ name: 'Gi0/1', vlan_ids: ['v10'], ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] })])
    await choosePort(wrapper, 'Gi0/1')

    expect(checks(wrapper).map((c) => c.text())).toEqual(['Режим порта и VLAN', 'IP-адрес', 'Открытые порты', 'Подинтерфейсы'])
    expect(checks(wrapper).map((c) => (c.get('input').element as HTMLInputElement).checked)).toEqual([true, true, false, false])
    expect(checks(wrapper).map((c) => c.classes('disabled'))).toEqual([false, false, true, true])
    expect(checks(wrapper).map((c) => c.get('input').attributes('disabled') !== undefined)).toEqual([false, false, true, true])
    expect(wrapper.get('.copy-row .btn').attributes('disabled')).toBeUndefined()
  })

  it('доступность параметров считается по каждому порту отдельно: IP без VLAN и VLAN без IP', async () => {
    const wrapper = mountBlock([
      makeRow({ name: 'Gi0/1', vlan_ids: [], ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] }),
      makeRow({ name: 'Gi0/2', vlan_ids: ['v10'], ips: [] }),
    ])
    const state = () => checks(wrapper).map((c) => [c.classes('disabled'), c.get('input').attributes('disabled') !== undefined])

    await choosePort(wrapper, 'Gi0/1')
    expect(state()).toEqual([
      [true, true],
      [false, false],
      [true, true],
      [true, true],
    ])

    await choosePort(wrapper, 'Gi0/2')
    expect(state()).toEqual([
      [false, false],
      [true, true],
      [true, true],
      [true, true],
    ])
  })

  it('у порта без значений — подсказка, копирование недоступно', async () => {
    const wrapper = mountBlock([makeRow({ name: 'Gi0/1', vlan_ids: [] })])
    await choosePort(wrapper, 'Gi0/1')

    expect(wrapper.get('.copy-what .hint').text()).toBe('У порта нет значений, которые можно скопировать.')
    expect(wrapper.get('.copy-row .btn').attributes('disabled')).toBeDefined()
  })

  it('«Скопировать» отдаёт новый черновик событием apply и не мутирует исходный', async () => {
    const draft: InterfaceGroupDraft = { ...emptyGroup('Группа'), key: 'g1' }
    const wrapper = mountBlock(
      [makeRow({ name: 'Gi0/1', vlan_mode: 'access', vlan_ids: ['v10'], ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'mgmt' }] })],
      draft,
    )
    await choosePort(wrapper, 'Gi0/1')
    await wrapper.get('.copy-row .btn').trigger('click')

    const applied = wrapper.emitted('apply')![0][0] as InterfaceGroupDraft
    expect(applied).toMatchObject({
      key: 'g1',
      name: 'Группа',
      vlan_mode: 'access',
      vlan_ids: ['v10'],
      ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'mgmt' }],
    })
    expect(draft).toMatchObject({ vlan_mode: '', vlan_ids: [], ips: [] })
    expect(useToast().toasts.at(-1)).toMatchObject({ type: 'success' })
  })

  it('подинтерфейсы копируются вместе с VLAN порта: предупреждения о «лишних» VLAN нет, шаблон приходит в черновике', async () => {
    // Исходная группа без режима и VLAN: пока родитель не принял apply, проп draft остаётся старым.
    const sub = { key: 's1', name: 'Gi0/1.10', vlan_id: 'v10', is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [] }
    const wrapper = mountBlock([makeRow({ name: 'Gi0/1', vlan_mode: 'access', vlan_ids: ['v10'], subinterfaces: [sub] })])
    await choosePort(wrapper, 'Gi0/1')
    await wrapper.get('.copy-row .btn').trigger('click')

    const applied = wrapper.emitted('apply')![0][0] as InterfaceGroupDraft
    expect(applied).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'], manage_subinterfaces: true })
    expect(applied.subinterfaces?.map((s) => s.vlan_id)).toEqual(['v10'])
    expect(useToast().toasts.map((t) => t.type)).toEqual(['success'])
  })

  it('снятая галочка исключает параметр из копирования', async () => {
    const wrapper = mountBlock([makeRow({ name: 'Gi0/1', vlan_ids: ['v10'], ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] })])
    await choosePort(wrapper, 'Gi0/1')
    await checks(wrapper)[0].get('input').setValue(false) // без режима порта и VLAN
    await wrapper.get('.copy-row .btn').trigger('click')

    expect(wrapper.emitted('apply')![0][0]).toMatchObject({ ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }], vlan_mode: '', vlan_ids: [] })
  })

  it('после копирования блок возвращается в исходное состояние: порт не выбран, параметры скрыты', async () => {
    const wrapper = mountBlock([makeRow({ name: 'Gi0/1', vlan_ids: ['v10'] })])
    await choosePort(wrapper, 'Gi0/1')
    await wrapper.get('.copy-row .btn').trigger('click')

    expect(wrapper.find('.copy-what').exists()).toBe(false)
    expect(wrapper.get('.copy-row .btn').attributes('disabled')).toBeDefined()
  })
})
