import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ApproveFindingModal from '../ApproveFindingModal.vue'
import { MAX_APPROVAL_COMMENT_LENGTH } from '../../api/consistency'
import { finding } from '../../__tests__/consistencyFixtures'

const problem = finding({ message: 'IP-адрес 10.0.0.5 назначен разным объектам: srv-1, srv-2.' })
const mountModal = (busy = false, findings = [problem]) => mount(ApproveFindingModal, { props: { findings, busy } })
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

  describe('несколько проблем сразу', () => {
    const many = (count: number) => Array.from({ length: count }, (_, index) => finding({ message: `проблема ${index + 1}` }))

    it('заголовок и кнопка называют число проблем, а окно говорит, что одобряются ВСЕ подходящие под фильтры, а не видимые', () => {
      const wrapper = mountModal(false, many(12))

      expect(wrapper.find('h2').text()).toBe('Одобрить 12 проблем?')
      expect(wrapper.find('[role="dialog"]').attributes('aria-label')).toBe('Одобрение проблем')
      expect(wrapper.text()).toContain('подходящие под текущие фильтры, а не только показанные на этой странице')
      expect(button(wrapper, 'Одобрить все (12)').exists()).toBe(true)
    })

    it('показывает первые пять проблем, остальные — числом: окно не растёт на сотни строк', () => {
      const wrapper = mountModal(false, many(12))

      expect(wrapper.findAll('.problems li:not(.more)').map((item) => item.text())).toEqual([
        'проблема 1',
        'проблема 2',
        'проблема 3',
        'проблема 4',
        'проблема 5',
      ])
      expect(wrapper.find('.problems .more').text()).toBe('и ещё 7')
    })

    it('ровно пять проблем — без строки «и ещё»', () => {
      expect(mountModal(false, many(5)).find('.problems .more').exists()).toBe(false)
    })

    it.each([
      [2, 'Одобрить 2 проблемы?'],
      [21, 'Одобрить 21 проблему?'],
    ])('число склоняется: %i → «%s»', (count, title) => {
      expect(mountModal(false, many(count)).find('h2').text()).toBe(title)
    })

    it('подтверждение отдаёт один комментарий на все проблемы', async () => {
      const wrapper = mountModal(false, many(3))
      await wrapper.find('textarea').setValue('  VRRP  ')
      await button(wrapper, 'Одобрить все (3)').trigger('click')

      expect(wrapper.emitted('confirm')).toEqual([['VRRP']])
    })

    it('одна проблема — прежнее окно: текст проблемы и кнопка «Одобрить», без списка', () => {
      const wrapper = mountModal()

      expect(wrapper.find('.problems').exists()).toBe(false)
      expect(wrapper.find('h2').text()).toBe('Одобрить проблему?')
      expect(button(wrapper, 'Одобрить').exists()).toBe(true)
    })
  })
})
