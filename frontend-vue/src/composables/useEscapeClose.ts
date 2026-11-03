import { onBeforeUnmount } from 'vue'

// UI-04 (ревью 2.158.0): Esc не закрывал ни одну из 33 модалок. Вложенные окна («+» быстрого добавления поверх формы
// устройства) нельзя закрывать общим слушателем «закрыть всё» — один Esc снёс бы обе формы и потерял введённое в нижней.
// Поэтому окна стоят в стеке, а закрывается только верхнее.

interface EscapeEntry {
  close: () => void
}

const stack: EscapeEntry[] = []

function onKeydown(event: KeyboardEvent): void {
  // defaultPrevented — Esc уже потратили на себя более «мелкие» элементы: открытый список SearchableSelect, подсказка HelpTip,
  // меню пользователя. isComposing — Esc в IME отменяет ввод символа, а не окно.
  if (event.key !== 'Escape' || event.defaultPrevented || event.isComposing) return
  const top = stack[stack.length - 1]
  if (!top) return
  event.preventDefault()
  top.close()
}

/**
 * Закрывает окно по Esc, если оно верхнее среди открытых. Вызывать в setup() окна.
 *
 * Слушатель висит на window, а не на document: событие всплывает сначала через document, поэтому обработчики на элементах и на
 * document (список выбора, подсказка, меню) всегда успевают забрать свой Esc и пометить его preventDefault, независимо от того,
 * в каком порядке они были подписаны. Запись в стек делается в setup(), а не в onMounted: у родителя setup идёт раньше, чем у
 * ребёнка, поэтому окно, вложенное в другое, всегда оказывается выше него.
 *
 * Обычно вручную не вызывается: через useOverlayDismiss его получают все модалки приложения.
 */
export function useEscapeClose(close: () => void): void {
  const entry: EscapeEntry = { close }
  stack.push(entry)
  if (stack.length === 1) window.addEventListener('keydown', onKeydown)

  onBeforeUnmount(() => {
    const index = stack.indexOf(entry)
    if (index !== -1) stack.splice(index, 1)
    if (stack.length === 0) window.removeEventListener('keydown', onKeydown)
  })
}
