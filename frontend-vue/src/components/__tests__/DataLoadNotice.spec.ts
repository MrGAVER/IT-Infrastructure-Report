import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import DataLoadNotice from '../DataLoadNotice.vue'

describe('DataLoadNotice.vue', () => {
  it('incomplete: «n из N» с разделителями тысяч, пояснение, роль status, кнопки повтора нет', () => {
    const wrapper = mount(DataLoadNotice, {
      props: { kind: 'incomplete', what: 'контейнеров', loaded: 50000, total: 60000, hint: 'Карточки посчитаны по части.' },
    })
    const text = wrapper.text().replace(/\s+/g, ' ')
    expect(text).toContain('Показана часть данных (контейнеров)')
    expect(text).toContain('загружено 50 000 из 60 000')
    expect(text).toContain('Карточки посчитаны по части.')
    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.find('[data-action="retry-load"]').exists()).toBe(false)
  })

  it('failed: роль alert, список не показывается и не сохраняется, есть «Повторить загрузку», по клику — событие retry', async () => {
    const wrapper = mount(DataLoadNotice, { props: { kind: 'failed', what: 'IP-адресов ВМ' } })
    expect(wrapper.attributes('role')).toBe('alert')
    expect(wrapper.text()).toContain('Не удалось загрузить данные (IP-адресов ВМ)')
    await wrapper.find('[data-action="retry-load"]').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('partial: объясняет, почему список не показан, и не предлагает повтор (он дал бы то же самое)', () => {
    const wrapper = mount(DataLoadNotice, { props: { kind: 'partial', what: 'ПО ВМ', loaded: 1000, total: 2000 } })
    const text = wrapper.text().replace(/\s+/g, ' ')
    expect(text).toContain('1 000 из 2 000')
    expect(text).toContain('невидимые записи были бы удалены')
    expect(wrapper.find('[data-action="retry-load"]').exists()).toBe(false)
  })

  it('смена kind пересчитывает роль (реактивность, а не значение при создании)', async () => {
    const wrapper = mount(DataLoadNotice, { props: { kind: 'failed', what: 'x' } })
    await wrapper.setProps({ kind: 'incomplete', loaded: 1, total: 2 })
    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.classes()).not.toContain('is-error')
  })
})
