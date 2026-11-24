import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ApproveFindingModal from '../ApproveFindingModal.vue'
import { MAX_APPROVAL_COMMENT_LENGTH } from '../../api/consistency'
import { finding } from '../../__tests__/consistencyFixtures'

const problem = finding({ message: 'IP-адрес 10.0.0.5 назначен разным объектам: srv-1, srv-2.' })
const mountModal = (busy = false) => mount(ApproveFindingModal, { props: { finding: problem, busy } })
const button = (wrapper: ReturnType<typeof mountModal>, text: string) => wrapper.findAll('button').find((item) => item.text() === text)!

describe('ApproveFindingModal', () => {
  it('показывает проблему и объясняет, когда одобрение теряет силу', () => {
    const wrapper = mountModal()

    expect(wrapper.find('[role="dialog"]').attributes('aria-label')).toBe('Одобрение проблемы')
    expect(wrapper.text()).toContain(problem.message)
    expect(wrapper.text()).toContain('вернётся в список')
  })

  it('без комментария отдаёт null, а пробелы по краям комментария убирает', async () => {
    const wrapper = mountModal()
    await button(wrapper, 'Одобрить').trigger('click')
    await wrapper.find('textarea').setValue('  общий адрес VRRP  ')
    await button(wrapper, 'Одобрить').trigger('click')

    expect(wrapper.emitted('confirm')).toEqual([[null], ['общий адрес VRRP']])
  })

  it('комментарий из одних пробелов — это отсутствие комментария', async () => {
    const wrapper = mountModal()
    await wrapper.find('textarea').setValue('    ')
    await button(wrapper, 'Одобрить').trigger('click')

    expect(wrapper.emitted('confirm')).toEqual([[null]])
  })

  it('длина комментария ограничена так же, как на сервере', () => {
    expect(mountModal().find('textarea').attributes('maxlength')).toBe(String(MAX_APPROVAL_COMMENT_LENGTH))
  })

  it('пока идёт запрос, обе кнопки заблокированы: двойной щелчок не отправит одобрение дважды', () => {
    const wrapper = mountModal(true)

    expect(button(wrapper, 'Одобрить').attributes('disabled')).toBeDefined()
    expect(button(wrapper, 'Отмена').attributes('disabled')).toBeDefined()
  })

  it('«Отмена» и крестик закрывают окно, ничего не подтверждая', async () => {
    const wrapper = mountModal()
    await button(wrapper, 'Отмена').trigger('click')
    await wrapper.find('button[aria-label="Закрыть"]').trigger('click')

    expect(wrapper.emitted('close')).toHaveLength(2)
    expect(wrapper.emitted('confirm')).toBeUndefined()
  })
})
