import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ConfirmActionModal from '../ConfirmActionModal.vue'

const mountModal = (busy = false) =>
  mount(ConfirmActionModal, { props: { title: 'Удалить устаревшие одобрения?', message: 'Записи будут удалены.', confirmLabel: 'Удалить (3)', busy } })
const button = (wrapper: ReturnType<typeof mountModal>, text: string) => wrapper.findAll('button').find((item) => item.text() === text)!

describe('ConfirmActionModal', () => {
  it('показывает заголовок и последствия, окно названо для скринридера', () => {
    const wrapper = mountModal()

    expect(wrapper.find('h2').text()).toBe('Удалить устаревшие одобрения?')
    expect(wrapper.find('.message').text()).toBe('Записи будут удалены.')
    expect(wrapper.find('[role="dialog"]').attributes('aria-label')).toBe('Удалить устаревшие одобрения?')
  })

  it('подтверждение отдаёт событие confirm, а «Отмена» и крестик — close, ничего не подтверждая', async () => {
    const wrapper = mountModal()
    await button(wrapper, 'Удалить (3)').trigger('click')
    await button(wrapper, 'Отмена').trigger('click')
    await wrapper.find('button[aria-label="Закрыть"]').trigger('click')

    expect(wrapper.emitted('confirm')).toHaveLength(1)
    expect(wrapper.emitted('close')).toHaveLength(2)
  })

  it('пока идёт запрос, обе кнопки заблокированы: двойной щелчок не повторит действие', () => {
    const wrapper = mountModal(true)

    expect(button(wrapper, 'Удалить (3)').attributes('disabled')).toBeDefined()
    expect(button(wrapper, 'Отмена').attributes('disabled')).toBeDefined()
  })
})
