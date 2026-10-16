import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import StatCard from '../StatCard.vue'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/devices', component: { template: '<div/>' } }],
  })
}

describe('StatCard.vue', () => {
  it('без to — обычный блок: число не ссылка (как на экранах со своей сводкой)', () => {
    const wrapper = mount(StatCard, { props: { value: 7, label: 'Всего' } })

    expect(wrapper.find('a').exists()).toBe(false)
    expect(wrapper.find('.num').text()).toBe('7')
    expect(wrapper.find('.lbl').text()).toBe('Всего')
  })

  it('с to — число становится ссылкой на раздел, подпись остаётся обычным текстом', () => {
    const wrapper = mount(StatCard, { props: { value: 42, label: 'Физические устройства', to: '/devices' }, global: { plugins: [makeRouter()] } })

    const link = wrapper.find('a.num-link')
    expect(link.exists()).toBe(true)
    expect(link.text()).toBe('42')
    expect(link.attributes('href')).toBe('/devices')
    expect(wrapper.find('.lbl').element.tagName).toBe('DIV')
  })

  it('у ссылки есть доступное имя с подписью карточки: по одной цифре «42» назначение ссылки не понять', () => {
    const wrapper = mount(StatCard, { props: { value: 42, label: 'Физические устройства', to: '/devices' }, global: { plugins: [makeRouter()] } })

    const link = wrapper.find('a.num-link')
    expect(link.attributes('aria-label')).toBe('Физические устройства: 42. Открыть раздел')
    expect(link.attributes('title')).toBe('Открыть: Физические устройства')
  })

  it('ноль тоже ссылка: переход нужен и к пустому разделу (оттуда добавляют первую запись)', () => {
    const wrapper = mount(StatCard, { props: { value: 0, label: 'Контейнеры', to: '/devices' }, global: { plugins: [makeRouter()] } })

    expect(wrapper.find('a.num-link').text()).toBe('0')
  })
})
