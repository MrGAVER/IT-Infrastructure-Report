import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import StaleRecordHost from '../StaleRecordHost.vue'
import { useStaleRecordConflict } from '../../composables/useStaleRecordConflict'

beforeEach(() => useStaleRecordConflict().resolve('stay'))

describe('StaleRecordHost', () => {
  it('без вопроса окна нет', () => {
    const wrapper = mount(StaleRecordHost)
    expect(wrapper.find('[data-testid="stale-record"]').exists()).toBe(false)
    expect(wrapper.find('[role="alertdialog"]').exists()).toBe(false)
  })

  it('вопрос открывает alertdialog с именем-заголовком и текстом сервера', async () => {
    const wrapper = mount(StaleRecordHost)
    const answer = useStaleRecordConflict().ask('Запись изменена другим пользователем (id=1).')
    await nextTick()

    const dialog = wrapper.get('[role="alertdialog"]')
    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(wrapper.get(`#${dialog.attributes('aria-labelledby')}`).text()).toBe('Запись изменили, пока вы её редактировали')
    expect(wrapper.get('[data-testid="stale-record-message"]').text()).toBe('Запись изменена другим пользователем (id=1).')
    useStaleRecordConflict().resolve('stay')
    await answer
  })

  it.each([
    ['stale-record-overwrite', 'overwrite'],
    ['stale-record-reload', 'reload'],
    ['stale-record-stay', 'stay'],
  ] as const)('кнопка %s возвращает форме выбор «%s» и закрывает окно', async (testId, choice) => {
    const wrapper = mount(StaleRecordHost)
    const answer = useStaleRecordConflict().ask('конфликт')
    await nextTick()

    await wrapper.get(`[data-testid="${testId}"]`).trigger('click')

    await expect(answer).resolves.toBe(choice)
    expect(wrapper.find('[role="alertdialog"]').exists()).toBe(false)
  })

  it('закрытие окна (Esc, клик по фону) — «остаться в форме»: ничего не сохраняется', async () => {
    const wrapper = mount(StaleRecordHost)
    const answer = useStaleRecordConflict().ask('конфликт')
    await nextTick()

    wrapper.findComponent({ name: 'BaseModal' }).vm.$emit('close')

    await expect(answer).resolves.toBe('stay')
  })
})
