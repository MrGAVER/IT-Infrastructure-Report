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
