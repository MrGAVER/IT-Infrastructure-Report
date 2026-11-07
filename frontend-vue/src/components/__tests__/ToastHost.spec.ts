import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ToastHost from '../ToastHost.vue'
import { useToast } from '../../composables/useToast'

describe('ToastHost: уведомление с действием', () => {
  beforeEach(() => useToast().toasts.splice(0))

  it('кнопка действия есть только у уведомления с действием', async () => {
    const wrapper = mount(ToastHost, { attachTo: document.body })
    useToast().notify('обычное', 'info')
    useToast().notify('с действием', 'warning', { action: { label: 'Показать план', run: () => {} } })
    await wrapper.vm.$nextTick()

    const actions = wrapper.findAll('.toast-action')
    expect(actions).toHaveLength(1)
    expect(actions[0].text()).toBe('Показать план')
    wrapper.unmount()
  })

  it('нажатие выполняет действие и закрывает именно это уведомление', async () => {
    const run = vi.fn()
    const wrapper = mount(ToastHost, { attachTo: document.body })
    useToast().notify('другое', 'info')
    useToast().notify('с действием', 'warning', { action: { label: 'Открыть', run } })
    await wrapper.vm.$nextTick()

    await wrapper.find('.toast-action').trigger('click')

    expect(run).toHaveBeenCalledTimes(1)
    expect(useToast().toasts.map((t) => t.message)).toEqual(['другое'])
    wrapper.unmount()
  })
})

// FE-02 (ревью ветки fix/code-review-main-f06-stage2-f05): уведомления должны озвучиваться скринридером (WCAG 2.2, 4.1.3 «Status
// Messages»). Живая область обязана быть в DOM ДО появления сообщения, иначе часть скринридеров его не объявит; ошибки идут в
// отдельную «настойчивую» область, остальное — в вежливую.
describe('ToastHost: живые области для скринридера', () => {
  beforeEach(() => useToast().toasts.splice(0))

  it('обе области есть в DOM до появления первого уведомления', () => {
    const wrapper = mount(ToastHost, { attachTo: document.body })

    expect(wrapper.find('[role="status"]').exists()).toBe(true)
    expect(wrapper.find('[role="status"]').attributes('aria-live')).toBe('polite')
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('«Сохранено» попадает в область role="status", а не в role="alert"', async () => {
    const wrapper = mount(ToastHost, { attachTo: document.body })
    useToast().notify('Сохранено', 'success')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[role="status"]').text()).toContain('Сохранено')
    expect(wrapper.find('[role="alert"]').text()).not.toContain('Сохранено')
    wrapper.unmount()
  })

  it('ошибка попадает в область role="alert", а не в role="status"', async () => {
    const wrapper = mount(ToastHost, { attachTo: document.body })
    useToast().notifyError(new Error('Не удалось сохранить'))
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[role="alert"]').text()).toContain('Не удалось сохранить')
    expect(wrapper.find('[role="status"]').text()).not.toContain('Не удалось сохранить')
    wrapper.unmount()
  })

  it('информация и предупреждение — в вежливой области, в том числе с кнопкой действия', async () => {
    const run = vi.fn()
    const wrapper = mount(ToastHost, { attachTo: document.body })
    useToast().notify('Подсказка', 'info')
    useToast().notify('Список VLAN изменён', 'warning', { action: { label: 'Показать план', run } })
    await wrapper.vm.$nextTick()

    const status = wrapper.find('[role="status"]')
    expect(status.text()).toContain('Подсказка')
    expect(status.text()).toContain('Список VLAN изменён')
    expect(wrapper.find('[role="alert"]').text()).toBe('')
    await status.find('.toast-action').trigger('click')
    expect(run).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('кнопка «Закрыть» ошибки работает и в области alert', async () => {
    const wrapper = mount(ToastHost, { attachTo: document.body })
    useToast().notifyError(new Error('Сбой'))
    await wrapper.vm.$nextTick()

    await wrapper.find('[role="alert"] button[aria-label="Закрыть"]').trigger('click')

    expect(useToast().toasts).toHaveLength(0)
    wrapper.unmount()
  })

  it('в области объявляются только добавления, а не весь список заново (aria-atomic="false")', () => {
    const wrapper = mount(ToastHost, { attachTo: document.body })

    expect(wrapper.find('[role="status"]').attributes('aria-atomic')).toBe('false')
    expect(wrapper.find('[role="alert"]').attributes('aria-atomic')).toBe('false')
    wrapper.unmount()
  })
})
