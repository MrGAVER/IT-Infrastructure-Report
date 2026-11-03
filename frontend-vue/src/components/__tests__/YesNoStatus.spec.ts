import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import YesNoStatus from '../YesNoStatus.vue'
import { declaration, readStyles, ruleBody } from '../../__tests__/cssSource'

// UI-12 (ревью merge/review-2158-executors): «Нет» у SIEM и СКЗИ светилось оранжевым, как предупреждение.

describe('YesNoStatus.vue', () => {
  it('«Да» — зелёный статус on, подпись и точка на месте', () => {
    const wrapper = mount(YesNoStatus, { props: { value: true } })

    expect(wrapper.classes()).toEqual(expect.arrayContaining(['status', 'on']))
    expect(wrapper.classes()).not.toContain('neutral')
    expect(wrapper.text()).toBe('Да')
    expect(wrapper.find('.status-dot').exists()).toBe(true)
  })

  it('«Нет» — нейтральный статус: класс off сохранён (для общих стилей и тестов), но добавлен neutral', () => {
    const wrapper = mount(YesNoStatus, { props: { value: false } })

    expect(wrapper.classes()).toEqual(expect.arrayContaining(['status', 'off', 'neutral']))
    expect(wrapper.classes()).not.toContain('on')
    expect(wrapper.text()).toBe('Нет')
  })

  it('подписи можно заменить', () => {
    const wrapper = mount(YesNoStatus, { props: { value: false, yesLabel: 'Применяется', noLabel: 'Не применяется' } })

    expect(wrapper.text()).toBe('Не применяется')
  })

  it('neutral перекрашивает текст в приглушённый цвет; общий base.css при этом не тронут', () => {
    expect(declaration(ruleBody(readStyles('src/components/YesNoStatus.vue'), '.status.neutral'), 'color')).toBe('var(--ink-muted)')
    expect(declaration(ruleBody(readStyles('src/styles/base.css'), '.status.off'), 'color')).toBe('var(--status-warn)')
  })
})
