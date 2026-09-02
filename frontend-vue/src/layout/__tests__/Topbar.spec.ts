import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import Topbar from '../Topbar.vue'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('Topbar.vue', () => {
  it('показывает имя пользователя "Администратор" вместо "Андрей Л."', () => {
    const wrapper = mount(Topbar, { props: { title: 'Дашборд', crumb: 'Главная' } })
    expect(wrapper.find('.who b').text()).toBe('Администратор')
    expect(wrapper.text()).not.toContain('Андрей Л.')
  })

  it('инициалы в кружке соответствуют новому имени', () => {
    const wrapper = mount(Topbar, { props: { title: 'Дашборд', crumb: 'Главная' } })
    expect(wrapper.find('.avatar').text()).toBe('А')
  })
})
