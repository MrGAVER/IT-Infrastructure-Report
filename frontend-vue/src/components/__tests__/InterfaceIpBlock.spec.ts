import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import InterfaceIpBlock from '../InterfaceIpBlock.vue'
import type { InterfaceIpDraftRow } from '../../api/types'

const ips: InterfaceIpDraftRow[] = [
  { id: 'ip-1', ip_address: '10.0.0.1', prefix_length: '24', purpose: 'управление' },
  { id: 'ip-2', ip_address: '10.0.1.1', prefix_length: '24', purpose: '' },
]

function mountBlock(props: Partial<InstanceType<typeof InterfaceIpBlock>['$props']> = {}) {
  return mount(InterfaceIpBlock, { props: { ips, managed: false, lockNote: '', ...props } })
}
const lastUpdate = (wrapper: ReturnType<typeof mountBlock>) => wrapper.emitted('update:ips')!.at(-1)![0] as InterfaceIpDraftRow[]

describe('InterfaceIpBlock', () => {
  it('без адресов — пометка «IP-адреса не добавлены»; кнопка добавляет пустую строку в конец списка', async () => {
    const wrapper = mountBlock({ ips: [] })
    expect(wrapper.get('.empty').text()).toBe('IP-адреса не добавлены')
    expect(wrapper.findAll('.ip-row')).toHaveLength(0)

    await wrapper.get('.ip-head button').trigger('click')
    expect(lastUpdate(wrapper)).toEqual([{ ip_address: '', prefix_length: '', purpose: '' }])
  })

  it('показывает адрес, префикс и назначение каждой строки', () => {
    const wrapper = mountBlock()
    const rows = wrapper.findAll('.ip-row')

    expect(rows).toHaveLength(2)
    expect(rows[0].findAll('input').map((i) => (i.element as HTMLInputElement).value)).toEqual(['10.0.0.1', '24', 'управление'])
    expect(wrapper.find('.empty').exists()).toBe(false)
  })

  it('правка поля меняет только эту строку и только это поле, остальное — как было', async () => {
    const wrapper = mountBlock()
    const second = wrapper.findAll('.ip-row')[1].findAll('input')

    await second[0].setValue('10.0.9.9')
    expect(lastUpdate(wrapper)).toEqual([ips[0], { ...ips[1], ip_address: '10.0.9.9' }])
    await second[1].setValue('16')
    expect(lastUpdate(wrapper)[1]).toMatchObject({ prefix_length: '16', ip_address: '10.0.1.1' })
    await second[2].setValue('резерв')
    expect(lastUpdate(wrapper)[1]).toMatchObject({ purpose: 'резерв' })
  })

  it('удаление убирает именно выбранную строку', async () => {
    const wrapper = mountBlock()
    await wrapper.findAll('.ip-row')[0].get('button[aria-label="Удалить IP интерфейса"]').trigger('click')
    expect(lastUpdate(wrapper)).toEqual([ips[1]])
  })

  it('исходный список не мутируется — родитель получает новый', async () => {
    const source = ips.map((ip) => ({ ...ip }))
    const wrapper = mountBlock({ ips: source })
    await wrapper.get('.ip-head button').trigger('click')
    await wrapper.findAll('.ip-row')[0].findAll('input')[0].setValue('1.1.1.1')
    expect(source).toEqual(ips)
  })

  it('IP задаёт группа: поля заблокированы, добавлять и удалять нельзя, вместо кнопки — подсказка', () => {
    const wrapper = mountBlock({ managed: true, lockNote: 'IP-адрес и его назначение задан группой «Магистраль»' })

    expect(wrapper.findAll('.ip-row input').every((i) => i.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.find('.ip-head button').exists()).toBe(false)
    expect(wrapper.find('button[aria-label="Удалить IP интерфейса"]').exists()).toBe(false)
    expect(wrapper.get('.group-lock').text()).toContain('«Магистраль»')
  })
})
