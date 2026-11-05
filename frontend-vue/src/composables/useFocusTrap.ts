import { onBeforeUnmount, onMounted, onUnmounted, toValue, type MaybeRefOrGetter } from 'vue'

// F-01 (код-ревью main, WCAG 2.4.3 и 2.1.2): после открытия окна активным оставался элемент под подложкой, а первый Tab уводил
// фокус из окна в фон. Что делает ловушка:
//  1. при открытии переносит фокус в окно: на элемент с autofocus, иначе на сам диалог (tabindex="-1" — скринридер озвучит его
//     имя). «Первое поле» не угадывается: у SearchableSelect фокус раскрывает список;
//  2. Tab с последнего элемента переходит на первый, Shift+Tab с первого — на последний; пока фокус вне окна (клик по
//     подложке уводит его на body), Tab возвращает его внутрь;
//  3. при закрытии возвращает фокус на элемент, открывший окно.
// Из вложенных окон реагирует только верхнее — см. modalStack.ts.

const TABBABLE_SELECTOR = [
  'a[href]',
  'area[href]',
  'button',
  'input:not([type="hidden"])',
  'select',
  'textarea',
  'summary',
  '[contenteditable]:not([contenteditable="false"])',
  '[tabindex]',
].join(',')

function isTabbable(el: HTMLElement): boolean {
  if (el.tabIndex < 0 || el.matches(':disabled')) return false
  // В группе радиокнопок Tab останавливается только на выбранной: невыбранные — не границы окна.
  if (el instanceof HTMLInputElement && el.type === 'radio' && el.name && !el.checked) {
    const hasChecked = Array.from(el.ownerDocument.querySelectorAll<HTMLInputElement>('input[type="radio"]:checked')).some(
      (radio) => radio.name === el.name && radio.form === el.form,
    )
    if (hasChecked) return false
  }
  return true
}

function isVisible(el: HTMLElement): boolean {
  if (el.closest('[inert], [hidden]')) return false
  // checkVisibility есть во всех актуальных браузерах; без него (старые движки, jsdom) элемент считается видимым.
  return typeof el.checkVisibility === 'function' ? el.checkVisibility({ visibilityProperty: true }) : true
}

/** Первый и последний видимые элементы окна, до которых доходит Tab. Ищет с краёв и останавливается на первом найденном. */
function boundaryTabbables(root: HTMLElement): { first: HTMLElement | null; last: HTMLElement | null } {
  const candidates = Array.from(root.querySelectorAll<HTMLElement>(TABBABLE_SELECTOR)).filter(isTabbable)
  const first = candidates.find(isVisible) ?? null
  let last: HTMLElement | null = null
  for (let i = candidates.length - 1; i >= 0; i -= 1) {
    if (isVisible(candidates[i])) {
      last = candidates[i]
      break
    }
  }
  return { first, last }
}

/**
 * Удерживает фокус внутри окна. Вызывать в setup() окна.
 *
 * @param dialog диалог (элемент с role="dialog"): ref или функция — подложка может отдать его уже после монтирования.
 * @param isTop окно сейчас верхнее среди открытых (useModalStack): вложенные окна не должны перехватывать Tab друг у друга.
 *
 * @example
 * const { isTop } = useModalStack()
 * useFocusTrap(dialogRef, isTop)
 */
export function useFocusTrap(dialog: MaybeRefOrGetter<HTMLElement | null | undefined>, isTop: () => boolean = () => true): void {
  // Элемент, открывший окно, — это тот, что был в фокусе к моменту setup (клик по кнопке, Enter на строке).
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null

  function onKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Tab' || event.defaultPrevented || !isTop()) return
    const root = toValue(dialog)
    if (!root) return
    const { first, last } = boundaryTabbables(root)
    if (!first || !last) {
      event.preventDefault()
      root.focus()
      return
    }
    const active = document.activeElement
    if (!root.contains(active)) {
      event.preventDefault()
      ;(event.shiftKey ? last : first).focus()
    } else if (event.shiftKey && (active === first || active === root)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && active === last) {
      event.preventDefault()
      first.focus()
    }
  }

  onMounted(() => {
    const root = toValue(dialog)
    if (root) {
      if (!root.hasAttribute('tabindex')) root.setAttribute('tabindex', '-1')
      // Фокус не отбираем у того, кто уже его занял: дочерний компонент (его onMounted идёт раньше) или вложенное окно, которое
      // смонтировалось вместе с этим — оно верхнее и забрало фокус первым; в <body> оно лежит отдельно, поэтому contains() его не видит.
      if (isTop() && !root.contains(document.activeElement)) {
        const target = root.querySelector<HTMLElement>('[autofocus]')
        if (target && isTabbable(target) && isVisible(target)) target.focus()
        else root.focus({ preventScroll: true })
      }
    }
    document.addEventListener('keydown', onKeydown)
  })

  onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))

  // Фокус возвращается в onUnmounted, а не в onBeforeUnmount: хуки размонтирования вложенных окон сработают раньше хука родителя,
  // поэтому когда закрываются сразу оба, последним фокус получает элемент ПОД нижним окном — а не кнопка внутри уже убранного.
  onUnmounted(() => {
    if (opener && opener !== document.body && opener.isConnected) opener.focus()
  })
}
