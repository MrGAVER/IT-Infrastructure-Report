import { ref } from 'vue'
import { useEscapeClose } from './useEscapeClose'

/**
 * Клик по подложке модалки закрывает её — общий паттерн во всех *FormModal.vue этого приложения
 * (обычно реализован наивно, через `@click.self="$emit('close')"` прямо на .overlay). У наивной
 * версии есть баг: пользователь начинает выделять текст ВНУТРИ карточки модалки (mousedown на
 * каком-нибудь <span>/<label>) и утаскивает курсор за пределы карточки, на подложку, ДО того как
 * отпустить кнопку мыши. Браузер в этом случае диспатчит click с target, равным ближайшему
 * ОБЩЕМУ предку mousedown- и mouseup-целей — им оказывается сама подложка (.overlay,
 * currentTarget), и `click.self` (проверяющий только event.target === event.currentTarget у
 * самого click) срабатывает, закрывая форму и обрывая попытку выделения текста на середине.
 *
 * Фикс: закрываем только если подложка была целью И mousedown, И click — то есть весь клик,
 * от нажатия до отпускания, целиком произошёл на подложке, а не просто "закончился" на ней.
 *
 * Esc закрывает окно тем же действием (UI-04, ревью 2.158.0): «закрыть окно» одно, а способов — два. Подписку на Esc
 * делает useEscapeClose, поэтому она есть во всех модалках, которые уже вызывают этот композабл (верхнее окно из вложенных).
 *
 * @example
 * const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(() => emit('close'))
 * // <div class="overlay" @mousedown="onOverlayPointerDown" @click="onOverlayClick">
 */
export function useOverlayDismiss(onDismiss: () => void) {
  const pointerDownOnOverlay = ref(false)
  useEscapeClose(onDismiss)

  function onOverlayPointerDown(event: MouseEvent) {
    pointerDownOnOverlay.value = event.target === event.currentTarget
  }

  function onOverlayClick(event: MouseEvent) {
    if (pointerDownOnOverlay.value && event.target === event.currentTarget) onDismiss()
    pointerDownOnOverlay.value = false
  }

  return { onOverlayPointerDown, onOverlayClick }
}
