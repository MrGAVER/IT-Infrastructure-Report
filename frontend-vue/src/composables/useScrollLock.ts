import { onBeforeUnmount, onMounted } from 'vue'

// F-01 (код-ревью main): при открытом окне body оставался overflow: visible, и страница под подложкой прокручивалась колесом
// и клавишами. Блокировка со счётчиком: окон может быть несколько (вложенные), body отпускается только когда закрылось последнее.

let locks = 0
let saved: { overflow: string; paddingRight: string } | null = null

function lock(): void {
  locks += 1
  if (locks > 1) return
  const { body, documentElement } = document
  saved = { overflow: body.style.overflow, paddingRight: body.style.paddingRight }
  // Полоса прокрутки исчезает вместе с прокруткой, и страница позади окна разъезжается на её ширину. Компенсируем отступом.
  // В jsdom clientWidth всегда 0 — там полосы нет, компенсировать нечего.
  const scrollbar = documentElement.clientWidth > 0 ? window.innerWidth - documentElement.clientWidth : 0
  if (scrollbar > 0) {
    const current = Number.parseFloat(window.getComputedStyle(body).paddingRight) || 0
    body.style.paddingRight = `${current + scrollbar}px`
  }
  body.style.overflow = 'hidden'
}

function unlock(): void {
  if (locks === 0) return
  locks -= 1
  if (locks > 0 || !saved) return
  document.body.style.overflow = saved.overflow
  document.body.style.paddingRight = saved.paddingRight
  saved = null
}

/**
 * Блокирует прокрутку страницы, пока окно смонтировано. Вызывать в setup() окна.
 *
 * Парность держится на уровне экземпляра (FE-06 ревью): onBeforeUnmount срабатывает и у окна, которое прошло setup(), но не успело
 * смонтироваться (родитель переключил v-if в том же такте, ожидающий Suspense снят). Безусловный unlock уменьшал бы общий счётчик без
 * парного lock, и страница отпускалась бы под ещё открытым вторым окном.
 */
export function useScrollLock(): void {
  let held = false
  onMounted(() => {
    lock()
    held = true
  })
  onBeforeUnmount(() => {
    if (!held) return
    held = false
    unlock()
  })
}
