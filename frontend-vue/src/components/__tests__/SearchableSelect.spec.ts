import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SearchableSelect from '../SearchableSelect.vue'
import type { SearchableSelectOption } from '../SearchableSelect.vue'

const OPTIONS: SearchableSelectOption[] = [
  { value: 'msk', label: 'Москва' },
  { value: 'spb', label: 'Санкт-Петербург' },
  { value: 'nsk', label: 'Новосибирск' },
]

const GROUPED_OPTIONS: SearchableSelectOption[] = [
  { value: 't-server', label: 'Сервер (тип, без модели)' },
  { value: 'm-dell-1', label: 'PowerEdge R740', group: 'Dell' },
  { value: 'm-dell-2', label: 'PowerEdge R750', group: 'Dell' },
  { value: 'm-hp-1', label: 'ProLiant DL380', group: 'HP' },
]

describe('SearchableSelect.vue (п.4)', () => {
  it('закрыт по умолчанию, показывает placeholder без выбора', () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS } })
    expect(wrapper.find('.ss-panel').exists()).toBe(false)
    expect((wrapper.find('input').element as HTMLInputElement).placeholder).toBe('— не выбрано —')
  })

  it('при выбранном значении показывает подпись опции, а не сырой id', () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: 'spb', options: OPTIONS } })
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('Санкт-Петербург')
  })

  it('клик по полю открывает список со всеми опциями', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS } })
    await wrapper.find('input').trigger('focus')
    const labels = wrapper.findAll('.ss-option').map((o) => o.text())
    expect(labels).toEqual(['Москва', 'Санкт-Петербург', 'Новосибирск'])
  })

  it('ввод текста фильтрует опции без учёта регистра', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS } })
    await wrapper.find('input').trigger('focus')
    await wrapper.find('input').setValue('санкт')
    expect(wrapper.findAll('.ss-option').map((o) => o.text())).toEqual(['Санкт-Петербург'])
  })

  it('фильтр без совпадений показывает "Ничего не найдено"', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS } })
    await wrapper.find('input').trigger('focus')
    await wrapper.find('input').setValue('лондон')
    expect(wrapper.find('.ss-empty').text()).toBe('Ничего не найдено')
    expect(wrapper.findAll('.ss-option')).toHaveLength(0)
  })

  it('клик по опции выбирает её и закрывает список', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS } })
    await wrapper.find('input').trigger('focus')
    await wrapper.findAll('.ss-option')[1].trigger('mousedown')

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['spb'])
    await wrapper.setProps({ modelValue: 'spb' })
    expect(wrapper.find('.ss-panel').exists()).toBe(false)
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('Санкт-Петербург')
  })

  it('кнопка очистки сбрасывает значение и не закрывает список для нового выбора', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: 'msk', options: OPTIONS } })
    await wrapper.find('.ss-clear').trigger('mousedown')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([''])
  })

  it('кнопка очистки не рендерится, пока ничего не выбрано', () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS } })
    expect(wrapper.find('.ss-clear').exists()).toBe(false)
  })

  it('Escape закрывает список и возвращает подпись текущего выбора вместо введённого запроса', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: 'msk', options: OPTIONS } })
    await wrapper.find('input').trigger('focus')
    await wrapper.find('input').setValue('какой-то поиск')
    await wrapper.find('input').trigger('keydown.esc')

    expect(wrapper.find('.ss-panel').exists()).toBe(false)
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('Москва')
  })

  it('клик вне компонента закрывает список', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS }, attachTo: document.body })
    await wrapper.find('input').trigger('focus')
    expect(wrapper.find('.ss-panel').exists()).toBe(true)

    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.ss-panel').exists()).toBe(false)
    wrapper.unmount()
  })

  it('disabled запрещает открытие списка', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS, disabled: true } })
    await wrapper.find('input').trigger('focus')
    expect(wrapper.find('.ss-panel').exists()).toBe(false)
    expect((wrapper.find('input').element as HTMLInputElement).disabled).toBe(true)
  })

  it('ArrowDown/ArrowUp + Enter выбирают опцию клавиатурой', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS } })
    await wrapper.find('input').trigger('focus')
    await wrapper.find('input').trigger('keydown.down') // msk -> spb (индекс 0 -> 1)
    await wrapper.find('input').trigger('keydown.down') // spb -> nsk (индекс 1 -> 2)
    await wrapper.find('input').trigger('keydown.up') // nsk -> spb (индекс 2 -> 1)
    await wrapper.find('input').trigger('keydown.enter')

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['spb'])
  })

  it('ArrowDown на закрытом списке открывает его, не выбирая ничего', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS } })
    await wrapper.find('input').trigger('keydown.down')
    expect(wrapper.find('.ss-panel').exists()).toBe(true)
    expect(wrapper.emitted('update:modelValue')).toBeFalsy()
  })

  it('группы (optgroup-подобные) рендерятся с заголовком, обычные опции — без', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: GROUPED_OPTIONS } })
    await wrapper.find('input').trigger('focus')

    const groupLabels = wrapper.findAll('.ss-group-label').map((g) => g.text())
    expect(groupLabels).toEqual(['Dell', 'HP']) // "голый" тип без group не создаёт заголовок
    expect(wrapper.findAll('.ss-option').map((o) => o.text())).toEqual([
      'Сервер (тип, без модели)',
      'PowerEdge R740',
      'PowerEdge R750',
      'ProLiant DL380',
    ])
  })

  it('клавиатурная навигация проходит по единому плоскому индексу через границы групп', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: GROUPED_OPTIONS } })
    await wrapper.find('input').trigger('focus')
    for (let i = 0; i < 3; i++) await wrapper.find('input').trigger('keydown.down') // -> 4-я опция (ProLiant DL380)
    await wrapper.find('input').trigger('keydown.enter')

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['m-hp-1'])
  })
})
