import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import type { InterfaceIpDraftRow } from '../../api/types'
import GroupIpListEditor from '../GroupIpListEditor.vue'

const ip = (ip_address: string, prefix_length = '', purpose = '', id?: string): InterfaceIpDraftRow => ({ id, ip_address, prefix_length, purpose })

function mountEditor(modelValue: InterfaceIpDraftRow[]) {
  return mount(GroupIpListEditor, { props: { modelValue } })
}
const lastEmit = (wrapper: ReturnType<typeof mountEditor>) => wrapper.emitted('update:modelValue')!.at(-1)![0] as InterfaceIpDraftRow[]
const addresses = (wrapper: ReturnType<typeof mountEditor>) => wrapper.findAll('input[aria-label="Общий IP-адрес группы"]')

describe('GroupIpListEditor', () => {
  it('у группы без адресов показана одна пустая строка («не задавать»), удалить её нельзя', () => {
    const wrapper = mountEditor([])

    expect(addresses(wrapper)).toHaveLength(1)
    expect((addresses(wrapper)[0].element as HTMLInputElement).value).toBe('')
    expect(wrapper.find('button[aria-label="Удалить общий IP-адрес группы"]').exists()).toBe(false)
  })

  it('ввод в пустую строку отдаёт список из одного адреса', async () => {
    const wrapper = mountEditor([])

    await addresses(wrapper)[0].setValue('10.0.0.5')

    expect(lastEmit(wrapper)).toEqual([ip('10.0.0.5')])
  })

  it('«IP-адрес» добавляет ещё одну строку к имеющимся', async () => {
    const wrapper = mountEditor([ip('10.0.0.5', '24', 'Управление', 'g-1')])

    await wrapper.find('.btn-secondary').trigger('click')

    expect(lastEmit(wrapper)).toEqual([ip('10.0.0.5', '24', 'Управление', 'g-1'), ip('')])
  })

  it('у группы без адресов «IP-адрес» даёт две строки: видимую пустую и новую', async () => {
    const wrapper = mountEditor([])

    await wrapper.find('.btn-secondary').trigger('click')

    expect(lastEmit(wrapper)).toEqual([ip(''), ip('')])
  })

  it('правка одной строки не задевает остальные и сохраняет id строки; префикс остаётся строкой', async () => {
    const wrapper = mountEditor([ip('10.0.0.5', '24', 'Управление', 'g-1'), ip('10.0.1.5', '24', 'Данные', 'g-2')])

    await wrapper.findAll('input[aria-label="Префикс общего IP-адреса"]')[1].setValue('16')

    expect(lastEmit(wrapper)).toEqual([ip('10.0.0.5', '24', 'Управление', 'g-1'), ip('10.0.1.5', '16', 'Данные', 'g-2')])
    expect(typeof lastEmit(wrapper)[1].prefix_length).toBe('string')
  })

  it('удаление строки убирает именно её; из последней строки с данными список становится пустым', async () => {
    const wrapper = mountEditor([ip('10.0.0.5', '24', '', 'g-1'), ip('10.0.1.5', '24', '', 'g-2')])

    await wrapper.findAll('button[aria-label="Удалить общий IP-адрес группы"]')[0].trigger('click')
    expect(lastEmit(wrapper)).toEqual([ip('10.0.1.5', '24', '', 'g-2')])

    const single = mountEditor([ip('10.0.0.5', '24', '', 'g-1')])
    await single.get('button[aria-label="Удалить общий IP-адрес группы"]').trigger('click')
    expect(lastEmit(single)).toEqual([])
  })

  it('назначение недоступно, пока в строке нет адреса (оно часть IP), и доступно после ввода адреса', () => {
    const wrapper = mountEditor([ip('10.0.0.5', '24', '', 'g-1'), ip('')])
    const purposes = wrapper.findAll('input[aria-label="Назначение общего IP-адреса группы"]')

    expect(purposes[0].attributes('disabled')).toBeUndefined()
    expect(purposes[1].attributes('disabled')).toBeDefined()
  })
})
