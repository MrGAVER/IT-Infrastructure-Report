// Директива v-truncate-tooltip (п.3): если содержимое элемента обрезано (шире/выше своего
// контейнера — например, text-overflow: ellipsis в ячейке таблицы), при наведении курсора через
// секунду показывает всплывающую подсказку с полным текстом. Если текст не обрезан, подсказка не
// показывается вовсе — это не замена title, а именно условная подсказка "на случай обрезки".
//
// Реализовано как директива, а не компонент-обёртка: применяется точечно к уже существующим
// ячейкам таблиц и полям без изменения их разметки — обёртка компонентом потребовала бы менять
// родительскую вёрстку почти везде, директива нет. Подключается локально через <script setup>
// (см. соглашение Vue: импорт с именем vXxx используется в шаблоне как v-xxx), а не глобально
// через app.directive() — тот же принцип, что и у остальных composables проекта (useToast,
// useOverlayDismiss): явный импорт там, где действительно используется, без магии на весь app.
//
// @example
// <script setup lang="ts">
// import { vTruncateTooltip } from '../directives/truncateTooltip'
// </script>
// <template>
//   <span class="cell-text" v-truncate-tooltip>{{ device.system_name }}</span>
//   <!-- Явное значение — когда нужно показать текст, отличный от видимого содержимого узла: -->
//   <span v-truncate-tooltip="row.full_description">{{ row.short_label }}</span>
// </template>
import type { Directive, DirectiveBinding } from 'vue'

const SHOW_DELAY_MS = 1000

interface TooltipState {
  timer: ReturnType<typeof setTimeout> | null
  popupEl: HTMLElement | null
  text: string
  onEnter: () => void
  onLeave: () => void
}

const states = new WeakMap<HTMLElement, TooltipState>()

/** Обрезанность проверяется в момент наведения, а не при монтировании — ширина ячейки может
 * определяться таблицей/флекс-контейнером уже после первого рендера директивы. */
function isOverflowing(el: HTMLElement): boolean {
  return el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1
}

function resolveText(el: HTMLElement, binding: DirectiveBinding<string | undefined>): string {
  if (typeof binding.value === 'string' && binding.value.trim()) return binding.value.trim()
  return (el.textContent ?? '').trim()
}

function positionPopup(el: HTMLElement, popup: HTMLElement) {
  const rect = el.getBoundingClientRect()
  const viewportW = window.innerWidth || document.documentElement.clientWidth
  const viewportH = window.innerHeight || document.documentElement.clientHeight
  popup.style.left = `${Math.min(Math.max(8, rect.left), Math.max(8, viewportW - 8))}px`
  // Снизу по умолчанию; сверху — если элемент у самого низа экрана и подсказка внизу не поместится.
  if (viewportH - rect.bottom < 60) {
    popup.style.bottom = `${viewportH - rect.top + 6}px`
    popup.style.top = 'auto'
  } else {
    popup.style.top = `${rect.bottom + 6}px`
    popup.style.bottom = 'auto'
  }
}

function showPopup(el: HTMLElement, state: TooltipState) {
  if (state.popupEl || !state.text) return
  const popup = document.createElement('div')
  popup.className = 'truncate-tooltip-popup'
  popup.textContent = state.text
  document.body.appendChild(popup)
  positionPopup(el, popup)
  state.popupEl = popup
}

function hidePopup(state: TooltipState) {
  if (state.timer) {
    clearTimeout(state.timer)
    state.timer = null
  }
  if (state.popupEl) {
    state.popupEl.remove()
    state.popupEl = null
  }
}

export const vTruncateTooltip: Directive<HTMLElement, string | undefined> = {
  mounted(el, binding) {
    const state: TooltipState = { timer: null, popupEl: null, text: resolveText(el, binding), onEnter: () => {}, onLeave: () => {} }
    state.onEnter = () => {
      if (!isOverflowing(el)) return
      state.timer = setTimeout(() => showPopup(el, state), SHOW_DELAY_MS)
    }
    state.onLeave = () => hidePopup(state)
    states.set(el, state)
    el.addEventListener('mouseenter', state.onEnter)
    el.addEventListener('mouseleave', state.onLeave)
    // Клик (например, чтобы отредактировать ячейку) тоже прячет подсказку — иначе она может
    // повиснуть поверх открывшегося после клика select/input того же элемента.
    el.addEventListener('click', state.onLeave)
  },
  updated(el, binding) {
    const state = states.get(el)
    if (!state) return
    state.text = resolveText(el, binding)
    if (state.popupEl) state.popupEl.textContent = state.text
  },
  unmounted(el) {
    const state = states.get(el)
    if (!state) return
    hidePopup(state)
    el.removeEventListener('mouseenter', state.onEnter)
    el.removeEventListener('mouseleave', state.onLeave)
    el.removeEventListener('click', state.onLeave)
    states.delete(el)
  },
}
