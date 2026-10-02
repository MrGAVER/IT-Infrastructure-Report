import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import PagerNav from '../PagerNav.vue'

const mountPager = (page: number, pageCount: number) => mount(PagerNav, { props: { page, pageCount } })
const pageButtons = (w: ReturnType<typeof mountPager>) => w.findAll('button[aria-label^="Страница"]').map((b) => b.text())

describe('PagerNav.vue', () => {
  it('при сотнях страниц рисует окно номеров, а не кнопку на каждую страницу (иначе ряд вылезает за карточку)', () => {
    const wrapper = mountPager(50, 300)

    expect(pageButtons(wrapper)).toEqual(['1', '49', '50', '51', '300'])
    expect(wrapper.findAll('.pager-gap')).toHaveLength(2)
    expect(wrapper.findAll('button')).toHaveLength(7) // 5 номеров + «‹» + «›»
  })

  it('на малом числе страниц показывает все номера без пропусков', () => {
    const wrapper = mountPager(2, 4)

    expect(pageButtons(wrapper)).toEqual(['1', '2', '3', '4'])
    expect(wrapper.find('.pager-gap').exists()).toBe(false)
  })

  it('текущая страница выделена и помечена aria-current', () => {
    const wrapper = mountPager(3, 5)

    const current = wrapper.find('button.on')
    expect(current.text()).toBe('3')
    expect(current.attributes('aria-current')).toBe('page')
    expect(wrapper.findAll('[aria-current]')).toHaveLength(1)
  })

  it('клик по номеру, «‹» и «›» сообщает новую страницу', async () => {
    const wrapper = mountPager(5, 10)

    await wrapper.find('button[aria-label="Страница 10"]').trigger('click')
    await wrapper.find('button[aria-label="Предыдущая страница"]').trigger('click')
    await wrapper.find('button[aria-label="Следующая страница"]').trigger('click')

    expect(wrapper.emitted('update:page')).toEqual([[10], [4], [6]])
  })

  it('на первой странице «‹» недоступна, на последней — «›»', () => {
    const first = mountPager(1, 3)
    const last = mountPager(3, 3)

    expect((first.find('button[aria-label="Предыдущая страница"]').element as HTMLButtonElement).disabled).toBe(true)
    expect((first.find('button[aria-label="Следующая страница"]').element as HTMLButtonElement).disabled).toBe(false)
    expect((last.find('button[aria-label="Следующая страница"]').element as HTMLButtonElement).disabled).toBe(true)
  })

  it('одна страница — одна кнопка, обе стрелки недоступны', () => {
    const wrapper = mountPager(1, 1)

    expect(pageButtons(wrapper)).toEqual(['1'])
    expect(wrapper.findAll('button:disabled')).toHaveLength(2)
  })
})
