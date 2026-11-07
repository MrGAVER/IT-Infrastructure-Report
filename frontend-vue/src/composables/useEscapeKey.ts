import { onBeforeUnmount, onMounted } from 'vue'

// UI-04 (ревью 2.158.0): Esc не закрывал ни одну из 33 модалок, а вложенные окна («+» быстрого добавления поверх формы устройства)
// нельзя закрывать общим слушателем «закрыть всё» — один Esc снёс бы обе формы и потерял введённое в нижней.
// FE-06 (ревью ветки fix/code-review-main-f06-stage2-f05): раньше для этого был свой стек (useEscapeClose), второй после modalStack, и их
// согласованность держалась на одинаковом порядке вызовов в setup(). Теперь стек один — modalStack: окно подписывается на Esc этим
// композаблом и само решает, верхнее ли оно (`isTop()` из useModalStack), а порядок окон нигде не дублируется.

/**
 * Вызывает `handler` на нажатие Esc. Вызывать в setup() окна; обработчик сам проверяет, верхнее ли окно, и помечает событие
 * обработанным (`event.preventDefault()`), если закрывает окно.
 *
 * Слушатель висит на window, а не на document: событие всплывает сначала через document, поэтому обработчики на элементах и на
 * document (список выбора, подсказка, меню) всегда успевают забрать свой Esc и пометить его preventDefault, независимо от того,
 * в каком порядке они были подписаны. Такой Esc сюда не доходит: `defaultPrevented` — признак «уже потрачен». `isComposing`: Esc в
 * IME отменяет ввод символа, а не окно.
 *
 * Подписка — в onMounted, отписка — в onBeforeUnmount: отписка от того, на что не подписывались, безвредна, а лишней подписки у
 * окна, не дошедшего до монтирования, не бывает (то же правило парности, что у useScrollLock).
 *
 * @example
 * const { isTop } = useModalStack()
 * useEscapeKey((event) => {
 *   if (!isTop()) return
 *   event.preventDefault()
 *   emit('close')
 * })
 */
export function useEscapeKey(handler: (event: KeyboardEvent) => void): void {
  function onKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || event.defaultPrevented || event.isComposing) return
    handler(event)
  }
  onMounted(() => window.addEventListener('keydown', onKeydown))
  onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
}
