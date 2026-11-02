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

  describe('tone="warn" (UI-12)', () => {
    // Оранжевый «0» у «Неактивные», «Расхождения», «ID с разными именами» ложно тревожил: ноль нарушений — это норма.
    it('при значении больше нуля карточка предупреждает', () => {
      const wrapper = mount(StatCard, { props: { value: 3, label: 'Расхождения портов', tone: 'warn' } })

      expect(wrapper.find('.stat-card').classes()).toContain('warn')
    })

    it('при нуле остаётся нейтральной', () => {
      const wrapper = mount(StatCard, { props: { value: 0, label: 'Расхождения портов', tone: 'warn' } })

      expect(wrapper.find('.stat-card').classes()).not.toContain('warn')
      expect(wrapper.find('.stat-card').classes()).toContain('normal')
    })

    it('числовая строка читается как число: «0» нейтрально, «12» предупреждает', () => {
      expect(mount(StatCard, { props: { value: '0', label: 'x', tone: 'warn' } }).find('.stat-card').classes()).not.toContain('warn')
      expect(mount(StatCard, { props: { value: '12', label: 'x', tone: 'warn' } }).find('.stat-card').classes()).toContain('warn')
    })

    it('нечисловое значение («—») и отрицательное не считаются предупреждением', () => {
      expect(mount(StatCard, { props: { value: '—', label: 'x', tone: 'warn' } }).find('.stat-card').classes()).not.toContain('warn')
      expect(mount(StatCard, { props: { value: -1, label: 'x', tone: 'warn' } }).find('.stat-card').classes()).not.toContain('warn')
    })

    it('без tone карточка никогда не предупреждает, сколько бы ни было', () => {
      expect(mount(StatCard, { props: { value: 99, label: 'x' } }).find('.stat-card').classes()).not.toContain('warn')
    })

    it('значение меняется — тон пересчитывается: появилась проблема — карточка стала предупреждающей', async () => {
      const wrapper = mount(StatCard, { props: { value: 0, label: 'Неактивные', tone: 'warn' } })
      await wrapper.setProps({ value: 2 })

      expect(wrapper.find('.stat-card').classes()).toContain('warn')
    })
  })
})
