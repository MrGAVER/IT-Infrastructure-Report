// Страж стека окон и авто-размонтирование из setup.ts (см. modalLeakGuard.ts). Сам хук afterEach из теста не проверить, поэтому
// проверяются его части: условие стража и тот факт, что окно, оставленное предыдущим тестом, к началу следующего уже снято.
import { describe, it, expect } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { hasOpenModal, useModalStack } from '../composables/modalLayer'
import { assertNoOpenModals } from './modalLeakGuard'

const Win = defineComponent({
  setup() {
    useModalStack()
    return () => h('div')
  },
})

describe('assertNoOpenModals', () => {
  it('без открытых окон не бросает', () => {
    expect(() => assertNoOpenModals()).not.toThrow()
  })

  it('пока окно открыто — бросает понятную ошибку; после размонтирования — снова не бросает', () => {
    const wrapper = mount(Win)
    expect(() => assertNoOpenModals()).toThrow(/в стеке окон .* осталось открытое окно/)

    wrapper.unmount()
    expect(() => assertNoOpenModals()).not.toThrow()
  })
})

describe('enableAutoUnmount из setup.ts', () => {
  // Два теста подряд: первый открывает окно и НЕ закрывает его, второй проверяет, что к его началу окно уже снято глобальным
  // размонтированием. Если вызов из setup.ts убрать, второй тест упадёт (при случайном порядке `--sequence.shuffle` он может
  // выполниться раньше первого и пройти — тогда проверку выполнит следующий прогон).
  it('тест A: открывает окно и оставляет его открытым', () => {
    mount(Win)
    expect(hasOpenModal.value).toBe(true)
  })

  it('тест B (после A): окно из предыдущего теста уже снято', () => {
    expect(hasOpenModal.value).toBe(false)
  })
})
