// B-07: страж предупреждений Vue. Сам по себе страж — единственное, что мешает числу `[Vue warn]` в журнале тестов снова вырасти
// с нуля до тысяч, поэтому он проверен отдельно: ловит настоящее предупреждение Vue, пропускает чужие сообщения и отдаёт
// «намеренные» предупреждения тесту.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { assertNoVueWarnings, takeVueWarnings } from './vueWarnings'

const Strict = defineComponent({
  props: { count: { type: String, required: true } },
  setup: (props) => () => h('span', props.count),
})

afterEach(() => {
  takeVueWarnings() // эти тесты вызывают предупреждения намеренно: общий страж из setup.ts их видеть не должен
})

describe('B-07: страж предупреждений Vue', () => {
  it('предупреждение Vue (неверный тип пропса) попадает в список и роняет проверку с понятным сообщением', () => {
    mount(Strict, { props: { count: 3 as unknown as string } })

    expect(() => assertNoVueWarnings()).toThrow(/предупреждения Vue \(1\).*Invalid prop/s)
  })

  it('takeVueWarnings забирает предупреждения и очищает список: после этого проверка проходит', () => {
    mount(Strict, { props: { count: 3 as unknown as string } })

    const taken = takeVueWarnings()

    expect(taken).toHaveLength(1)
    expect(taken[0]).toContain('[Vue warn]')
    expect(() => assertNoVueWarnings()).not.toThrow()
  })

  it('без предупреждений проверка тихо проходит', () => {
    mount(Strict, { props: { count: '3' } })

    expect(() => assertNoVueWarnings()).not.toThrow()
  })

  it('чужие console.warn не принимаются за предупреждения Vue и печатаются как обычно', () => {
    const printed = vi.fn()
    const spy = vi.spyOn(console, 'warn').mockImplementation(printed)
    try {
      console.warn('ContainerFormModal: одновременно переданы container и copyFrom')
    } finally {
      spy.mockRestore()
    }

    expect(printed).toHaveBeenCalledTimes(1)
    expect(() => assertNoVueWarnings()).not.toThrow()
  })

  it('сообщений много: в ошибке показаны первые три и счётчик остальных', () => {
    for (let i = 0; i < 5; i++) console.warn(`[Vue warn]: проблема ${i}`)

    expect(() => assertNoVueWarnings()).toThrow(/\(5\).*и ещё 2/s)
  })
})
