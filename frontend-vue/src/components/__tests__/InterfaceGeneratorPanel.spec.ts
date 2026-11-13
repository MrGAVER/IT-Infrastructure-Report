import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import HelpTip from '../HelpTip.vue'
import InterfaceGeneratorPanel from '../InterfaceGeneratorPanel.vue'
import QuickAddButton from '../QuickAddButton.vue'
import { TEMPLATE_HELP_TEXT } from '../../utils/interfaceRowDraft'

const typeOptions = [
  { id: 't-eth', name: 'Ethernet' },
  { id: 't-sfp', name: 'SFP+' },
]
const speedOptions = [{ id: 's-1g', name: '1 Гбит/с' }]

function mountPanel(props: Record<string, unknown> = {}) {
  return mount(InterfaceGeneratorPanel, {
    props: { count: '4', startAt: '', nameTemplate: 'eth{n}', typeId: '', speedId: '', replaceAll: false, typeOptions, speedOptions, ...props },
    // QuickAddButton открывает окно через Teleport и ходит в справочники — здесь нужны только его события
    global: { stubs: { QuickAddButton: true } },
  })
}
const field = (wrapper: ReturnType<typeof mountPanel>, label: string) => wrapper.findAll('label').find((l) => l.text().startsWith(label))!

describe('InterfaceGeneratorPanel', () => {
  it('поля показывают значения из v-model', () => {
    const wrapper = mountPanel({ count: '12', startAt: '5', nameTemplate: 'Gi0/{n0}', typeId: 't-sfp', speedId: 's-1g', replaceAll: true })

    expect((field(wrapper, 'Количество').get('input').element as HTMLInputElement).value).toBe('12')
    expect((field(wrapper, 'Начать нумерацию с').get('input').element as HTMLInputElement).value).toBe('5')
    expect((field(wrapper, 'Шаблон имени').get('input').element as HTMLInputElement).value).toBe('Gi0/{n0}')
    expect((field(wrapper, 'Тип по умолчанию').get('select').element as HTMLSelectElement).value).toBe('t-sfp')
    expect((field(wrapper, 'Скорость по умолчанию').get('select').element as HTMLSelectElement).value).toBe('s-1g')
    expect((wrapper.get('.replace-all-check input').element as HTMLInputElement).checked).toBe(true)
  })

  it('ввод в каждое поле уходит в свой v-model', async () => {
    const wrapper = mountPanel()

    await field(wrapper, 'Количество').get('input').setValue('8')
    await field(wrapper, 'Начать нумерацию с').get('input').setValue('3')
    await field(wrapper, 'Шаблон имени').get('input').setValue('port{n}')
    await field(wrapper, 'Тип по умолчанию').get('select').setValue('t-eth')
    await field(wrapper, 'Скорость по умолчанию').get('select').setValue('s-1g')
    await wrapper.get('.replace-all-check input').setValue(true)

    // B-07: модель — строка (defineModel<string>), поэтому поля type="number" отдают именно строку, а не число; разбор — в usePortGenerator
    expect(wrapper.emitted('update:count')![0]).toEqual(['8'])
    expect(wrapper.emitted('update:startAt')![0]).toEqual(['3'])
    expect(wrapper.emitted('update:nameTemplate')![0]).toEqual(['port{n}'])
    expect(wrapper.emitted('update:typeId')![0]).toEqual(['t-eth'])
    expect(wrapper.emitted('update:speedId')![0]).toEqual(['s-1g'])
    expect(wrapper.emitted('update:replaceAll')![0]).toEqual([true])
  })

  it('B-07: очищенное поле отдаёт пустую строку (а не 0 и не NaN) — «не задано» для usePortGenerator', async () => {
    const wrapper = mountPanel({ count: '4', startAt: '7' })

    await field(wrapper, 'Количество').get('input').setValue('')
    await field(wrapper, 'Начать нумерацию с').get('input').setValue('')

    expect(wrapper.emitted('update:count')![0]).toEqual([''])
    expect(wrapper.emitted('update:startAt')![0]).toEqual([''])
  })

  it('тип и скорость выбираются из справочников; «не выбрано» — пустое значение', () => {
    const wrapper = mountPanel()

    expect(
      field(wrapper, 'Тип по умолчанию')
        .findAll('option')
        .map((o) => [o.attributes('value'), o.text()]),
    ).toEqual([
      ['', '— не выбрано —'],
      ['t-eth', 'Ethernet'],
      ['t-sfp', 'SFP+'],
    ])
    expect(field(wrapper, 'Скорость по умолчанию').findAll('option')).toHaveLength(2)
  })

  it('«Сгенерировать» просит родителя сгенерировать порты; сама панель список не меняет', async () => {
    const wrapper = mountPanel()
    await wrapper.get('.generator-actions button').trigger('click')
    expect(wrapper.emitted('generate')).toHaveLength(1)
  })

  it('тип и скорость, созданные тут же (кнопка «+»), сразу подставляются в поле', () => {
    const wrapper = mountPanel()
    const [typeAdd, speedAdd] = wrapper.findAllComponents(QuickAddButton)

    typeAdd.vm.$emit('created', { id: 't-new' })
    speedAdd.vm.$emit('created', { id: 's-new' })

    expect(wrapper.emitted('update:typeId')![0]).toEqual(['t-new'])
    expect(wrapper.emitted('update:speedId')![0]).toEqual(['s-new'])
  })

  it('у шаблона имени есть подсказка по {n} и {n0}, а под панелью — пояснение про режимы «добавить» и «заменить»', () => {
    const wrapper = mountPanel()
    expect(wrapper.getComponent(HelpTip).props('text')).toBe(TEMPLATE_HELP_TEXT)
    expect(wrapper.get('.generator-hint').text()).toContain('Заменить все порты')
  })
})
