import { afterEach, describe, it, expect, vi } from 'vitest'
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

  it('подпись подтягивается, если опция с выбранным значением появилась в options позже самого значения', async () => {
    // Значение выставлено раньше, чем родитель догрузил опцию (например, запись только что
    // создана через "+", а стор ещё перечитывается) — поле не должно оставаться пустым навсегда.
    const wrapper = mount(SearchableSelect, { props: { modelValue: 'kzn', options: OPTIONS } })
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('')

    await wrapper.setProps({ options: [...OPTIONS, { value: 'kzn', label: 'Казань' }] })

    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('Казань')
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

  it('запрос из нескольких слов требует каждое из них, в любом порядке и не подряд', async () => {
    const options: SearchableSelectOption[] = [
      { value: 'm1', label: 'Cisco WS-C2960-48TD-L' },
      { value: 'm2', label: 'Cisco WS-C3750G-24T' },
      { value: 'm3', label: 'HP ProLiant DL380' },
    ]
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options } })
    await wrapper.find('input').trigger('focus')

    await wrapper.find('input').setValue('cisco 2960')
    expect(wrapper.findAll('.ss-option').map((o) => o.text())).toEqual(['Cisco WS-C2960-48TD-L'])

    await wrapper.find('input').setValue('2960 CISCO')
    expect(wrapper.findAll('.ss-option').map((o) => o.text())).toEqual(['Cisco WS-C2960-48TD-L'])

    await wrapper.find('input').setValue('cisco hp')
    expect(wrapper.findAll('.ss-option')).toHaveLength(0)
  })

  it('searchText опции участвует в поиске, но в списке не показывается', async () => {
    const options: SearchableSelectOption[] = [
      { value: 'm1', label: 'Cisco C2960', searchText: 'Коммутатор' },
      { value: 'm2', label: 'HP DL380', searchText: 'Сервер' },
    ]
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options } })
    await wrapper.find('input').trigger('focus')

    await wrapper.find('input').setValue('коммутатор cisco')
    expect(wrapper.findAll('.ss-option').map((o) => o.text())).toEqual(['Cisco C2960'])
    expect(wrapper.find('.ss-panel').text()).not.toContain('Коммутатор')
  })

  it('пробелы в запросе по краям и между словами не мешают поиску', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS } })
    await wrapper.find('input').trigger('focus')
    await wrapper.find('input').setValue('   санкт   петер  ')
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
    expect(wrapper.findAll('.ss-option').map((o) => o.text())).toEqual(['Сервер (тип, без модели)', 'PowerEdge R740', 'PowerEdge R750', 'ProLiant DL380'])
  })

  it('клавиатурная навигация проходит по единому плоскому индексу через границы групп', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: GROUPED_OPTIONS } })
    await wrapper.find('input').trigger('focus')
    for (let i = 0; i < 3; i++) await wrapper.find('input').trigger('keydown.down') // -> 4-я опция (ProLiant DL380)
    await wrapper.find('input').trigger('keydown.enter')

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['m-hp-1'])
  })
})

describe('SearchableSelect.vue — режим remote (поиск на сервере)', () => {
  const mountRemote = (props: Record<string, unknown> = {}) => mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS, remote: true, ...props } })

  it('при открытии сообщает пустой поиск, при вводе — введённый текст; без remote события search нет', async () => {
    const remote = mountRemote()
    await remote.find('input').trigger('focus')
    await remote.find('input').setValue('мос')
    expect(remote.emitted('search')).toEqual([[''], ['мос']])

    const local = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS } })
    await local.find('input').trigger('focus')
    await local.find('input').setValue('мос')
    expect(local.emitted('search')).toBeFalsy()
  })

  it('опции не фильтруются локально: показано всё, что передал родитель, даже если не содержит введённого текста', async () => {
    const wrapper = mountRemote()
    await wrapper.find('input').trigger('focus')
    await wrapper.find('input').setValue('zzz')

    expect(wrapper.findAll('.ss-option').map((o) => o.text())).toEqual(['Москва', 'Санкт-Петербург', 'Новосибирск'])
    expect(wrapper.find('.ss-empty').exists()).toBe(false)
  })

  it('выбор опции работает как обычно и закрывает список; подпись выбранного остаётся в поле', async () => {
    const wrapper = mountRemote()
    await wrapper.find('input').trigger('focus')
    await wrapper.findAll('.ss-option')[1].trigger('mousedown')

    expect(wrapper.emitted('update:modelValue')![0]).toEqual(['spb'])
    expect(wrapper.find('.ss-panel').exists()).toBe(false)
  })

  it('пустой ответ: «Ничего не найдено», а пока ответа нет — «Загрузка…» вместо него', async () => {
    const wrapper = mountRemote({ options: [], loading: true })
    await wrapper.find('input').trigger('focus')
    expect(wrapper.find('.ss-empty').text()).toBe('Загрузка…')

    await wrapper.setProps({ loading: false })
    expect(wrapper.find('.ss-empty').text()).toBe('Ничего не найдено')
  })

  it('подсказка под списком (hint) и индикатор загрузки над найденным показываются только при наличии опций', async () => {
    const wrapper = mountRemote({ hint: 'Показаны первые 3 из 40 — уточните поиск' })
    await wrapper.find('input').trigger('focus')
    expect(wrapper.find('.ss-hint').text()).toBe('Показаны первые 3 из 40 — уточните поиск')

    await wrapper.setProps({ loading: true })
    expect(wrapper.find('.ss-hint').text()).toBe('Загрузка…')

    await wrapper.setProps({ options: [], hint: 'не должна показываться без опций', loading: false })
    expect(wrapper.find('.ss-hint').exists()).toBe(false)
  })
  it('emptyText: при пустом списке опций показывается вместо «Ничего не найдено»', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: [], emptyText: 'Все города уже выбраны' } })

    await wrapper.find('input').trigger('focus')

    expect(wrapper.find('.ss-empty').text()).toBe('Все города уже выбраны')
  })

  it('без emptyText пустой список по-прежнему показывает «Ничего не найдено»', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: [] } })

    await wrapper.find('input').trigger('focus')

    expect(wrapper.find('.ss-empty').text()).toBe('Ничего не найдено')
  })

  it('emptyText не подменяет «Ничего не найдено», когда опции есть, а не подошёл введённый запрос', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS, emptyText: 'Все города уже выбраны' } })
    const input = wrapper.find('input')

    await input.trigger('focus')
    await input.setValue('несуществующий город')

    expect(wrapper.find('.ss-empty').text()).toBe('Ничего не найдено')
  })
})

// Режим floating: панель в <body> с position: fixed — её не обрезает прокручиваемый предок (таблица подинтерфейсов).
describe('SearchableSelect.vue — режим floating (панель вне прокручиваемых предков)', () => {
  const panel = () => document.body.querySelector<HTMLElement>('.ss-panel')
  // jsdom не считает раскладку: положение поля задаём сами (возвращается getBoundingClientRect строки с полем).
  let fieldRect = { top: 100, bottom: 130, left: 40, width: 200 }
  function mockFieldRect(rect: typeof fieldRect) {
    fieldRect = rect
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(
      () =>
        ({
          ...fieldRect,
          right: fieldRect.left + fieldRect.width,
          height: fieldRect.bottom - fieldRect.top,
          x: fieldRect.left,
          y: fieldRect.top,
          toJSON: () => ({}),
        }) as DOMRect,
    )
  }
  function mountFloating(modelValue = '') {
    return mount(SearchableSelect, { props: { modelValue, options: OPTIONS, floating: true }, attachTo: document.body })
  }

  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('панель выводится в <body>, а не внутри компонента, и позиционируется от поля', async () => {
    mockFieldRect({ top: 100, bottom: 130, left: 40, width: 200 })
    const wrapper = mountFloating()
    await wrapper.find('input').trigger('focus')

    expect(wrapper.find('.ss-panel').exists()).toBe(false) // внутри rootEl панели нет
    expect(panel()).not.toBeNull()
    expect(panel()!.classList.contains('floating')).toBe(true)
    expect(panel()!.style.left).toBe('40px')
    expect(panel()!.style.width).toBe('200px')
    expect(panel()!.style.top).toBe('134px')
    expect([...panel()!.querySelectorAll('.ss-option')].map((o) => o.textContent?.trim())).toEqual(['Москва', 'Санкт-Петербург', 'Новосибирск'])
    wrapper.unmount()
  })

  it('без floating панель по-прежнему внутри компонента, без fixed-класса и инлайн-координат', async () => {
    const wrapper = mount(SearchableSelect, { props: { modelValue: '', options: OPTIONS }, attachTo: document.body })
    await wrapper.find('input').trigger('focus')

    const el = wrapper.find('.ss-panel')
    expect(el.exists()).toBe(true)
    expect(el.classes()).not.toContain('floating')
    expect(el.attributes('style')).toBeUndefined()
    wrapper.unmount()
  })

  it('когда снизу не хватает места, список открывается вверх', async () => {
    mockFieldRect({ top: 700, bottom: 730, left: 40, width: 200 })
    const wrapper = mountFloating()
    await wrapper.find('input').trigger('focus')

    expect(panel()!.style.top).toBe('')
    expect(panel()!.style.bottom).toBe(`${window.innerHeight - 700 + 4}px`)
    wrapper.unmount()
  })

  it('выбор опции в плавающей панели работает как обычно и закрывает список', async () => {
    mockFieldRect({ top: 100, bottom: 130, left: 40, width: 200 })
    const wrapper = mountFloating()
    await wrapper.find('input').trigger('focus')

    panel()!
      .querySelectorAll('.ss-option')[1]
      .dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['spb'])
    expect(panel()).toBeNull()
    wrapper.unmount()
  })

  it('клик внутри панели не закрывает список, клик вне — закрывает', async () => {
    mockFieldRect({ top: 100, bottom: 130, left: 40, width: 200 })
    const wrapper = mountFloating()
    await wrapper.find('input').trigger('focus')

    panel()!.dispatchEvent(new MouseEvent('click', { bubbles: true })) // например, по полосе прокрутки списка
    await wrapper.vm.$nextTick()
    expect(panel()).not.toBeNull()

    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(panel()).toBeNull()
    wrapper.unmount()
  })

  it('при прокрутке страницы панель следует за полем, а прокрутка самого списка положение не трогает', async () => {
    mockFieldRect({ top: 100, bottom: 130, left: 40, width: 200 })
    const wrapper = mountFloating()
    await wrapper.find('input').trigger('focus')
    expect(panel()!.style.top).toBe('134px')

    mockFieldRect({ top: 60, bottom: 90, left: 40, width: 200 })
    panel()!.dispatchEvent(new Event('scroll')) // прокрутка внутри списка — пересчёта нет
    await wrapper.vm.$nextTick()
    expect(panel()!.style.top).toBe('134px')

    window.dispatchEvent(new Event('scroll')) // прокрутка предка — панель едет за полем
    await wrapper.vm.$nextTick()
    expect(panel()!.style.top).toBe('94px')
    wrapper.unmount()
  })

  it('если поле целиком ушло за пределы окна при прокрутке, список закрывается', async () => {
    mockFieldRect({ top: 100, bottom: 130, left: 40, width: 200 })
    const wrapper = mountFloating()
    await wrapper.find('input').trigger('focus')

    mockFieldRect({ top: -60, bottom: -30, left: 40, width: 200 })
    window.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()

    expect(panel()).toBeNull()
    wrapper.unmount()
  })

  it('при размонтировании панель убирается из <body>, а слушатели окна снимаются', async () => {
    mockFieldRect({ top: 100, bottom: 130, left: 40, width: 200 })
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    const wrapper = mountFloating()
    await wrapper.find('input').trigger('focus')
    expect(panel()).not.toBeNull()

    wrapper.unmount()

    expect(panel()).toBeNull()
    expect(removeSpy).toHaveBeenCalledWith('scroll', expect.any(Function), true)
    expect(removeSpy).toHaveBeenCalledWith('resize', expect.any(Function))
  })
})
