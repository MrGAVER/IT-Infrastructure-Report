import { computed, onBeforeUnmount, onMounted, shallowReactive, type ComputedRef, type MaybeRefOrGetter } from 'vue'
import { useFocusTrap } from './useFocusTrap'
import { useOverlayDismiss } from './useOverlayDismiss'

// Единый модуль «слой окна» (раздел 5 ревью ветки fix/code-review-main-f06-stage2-f05, frontend п. 2).
//
// Модальное окно — одна сущность с пятью сторонами, которые раньше жили в пяти файлах, а порядок их вызова в BaseModal держался на
// комментариях:
//  1. стек открытых окон (useModalStack, hasOpenModal) — кто верхнее и на сколько слоёв поднять подложку; по нему же AppShell делает
//     фон страницы inert, пока открыто хоть одно окно;
//  2. закрытие по клику на подложку (useOverlayDismiss.ts — чистая логика указателя без состояния окна);
//  3. закрытие по Esc (useEscapeKey) — только верхнее окно, решает стек;
//  4. ловушка фокуса и возврат фокуса (useFocusTrap.ts — 115 строк независимой логики Tab со своим набором тестов) — только верхнее
//     окно, решает стек;
//  5. блокировка прокрутки страницы (useScrollLock) — со счётчиком по числу окон.
// Стороны 1, 3 и 5 живут в этом файле; 2 и 4 остаются отдельными файлами, а порядок их вызова задаёт useModalLayer.
//
// Единственная точка входа для окна — useModalLayer(): она вызывает стороны в нужном порядке. Окно (BaseModal) больше не знает ни о
// порядке, ни о том, что «верхнее» берётся из стека. Стороны экспортируются по отдельности только для тестов и для AppShell
// (hasOpenModal): вызывать их из компонентов напрямую не нужно.
//
// Порядок внутри useModalLayer не случаен:
//  — стек первым и именно в setup(), а не в onMounted: у родителя setup идёт раньше, чем у ребёнка, а onMounted — наоборот, и вложенное
//    окно при монтировании попало бы ПОД родителя; Esc и ловушка фокуса берут «верхнее» из стека, поэтому он нужен им уже готовым;
//  — стек снимает окно в onBeforeUnmount — раньше, чем useFocusTrap вернёт фокус в onUnmounted: к этому моменту AppShell уже снял inert
//    с фона, и фокус возвращается на доступный элемент;
//  — useFocusTrap запоминает элемент, открывший окно, в момент вызова (document.activeElement), поэтому до него в setup() не должно
//    быть ничего, что двигает фокус.

// --- Стек открытых окон -------------------------------------------------------------------------------------------------

// F-01/F-03 (код-ревью main): окна приложения вкладываются друг в друга («+» быстрого добавления поверх формы устройства,
// выбор VLAN поверх окна группы портов). Порядок вложенности раньше держался на числах z-index («60 против 70») и на порядке
// в DOM. Теперь он один — стек открытых окон: по нему окно знает, что оно верхнее (только верхнее перехватывает Tab) и на
// сколько слоёв поднять подложку над окном под ним.
//
// Запись в стек делается в setup(), а не в onMounted: у родителя setup идёт раньше, чем у ребёнка, а onMounted — наоборот
// (дети монтируются первыми), поэтому окно, вложенное в другое, при монтировании попало бы ПОД родителя.

// R2-05 (ревью merge/review-f06-stage2-f05-executors): запись снимается в onBeforeUnmount, и этого достаточно. Проверено на настоящем Vue
// (modalStack.spec.ts): если setup() окна бросил после регистрации, а ошибку обработал errorHandler приложения (production), запись уходит
// вместе с экземпляром — ни при v-if родителя, ни при размонтировании приложения она не залипает. onScopeDispose добавлять не нужно: он
// срабатывает там же, где onBeforeUnmount, а там, где тот молчит, молчит и он — в dev-режиме, когда ошибка setup() пробрасывается из
// mount() и Vue не размонтирует недостроенное дерево. Если в приложении появится <KeepAlive>, деактивированное окно (не размонтированное)
// останется в стеке — понадобится onDeactivated/onActivated; сейчас KeepAlive не используется.
const stack = shallowReactive<symbol[]>([])

/**
 * Открыто ли хотя бы одно модальное окно. Реактивно: по нему AppShell делает фон страницы inert (FE-03 ревью), пока окно открыто.
 * Атрибут inert ставит один владелец — AppShell, а окна только сообщают о себе стеком: так окно, закрывшееся под открытым мобильным
 * меню, не снимет inert, поставленный меню. Запись в стеке снимается в onBeforeUnmount, то есть до onUnmounted окна (возврат фокуса,
 * useFocusTrap), а перерисовка AppShell идёт в том же проходе планировщика раньше хуков onUnmounted — к возврату фокуса inert уже снят.
 */
export const hasOpenModal = computed(() => stack.length > 0)

export interface ModalStackEntry {
  /** Номер окна от низа стека: 0 у нижнего, 1 у окна поверх него и так далее. Реактивен: закрылось нижнее — верхние сдвинулись. */
  depth: ComputedRef<number>
  /** Окно сейчас верхнее среди открытых. */
  isTop: () => boolean
}

/** Ставит окно в стек открытых окон и снимает его при размонтировании. Вызывать в setup(). */
export function useModalStack(): ModalStackEntry {
  const id = Symbol('modal')
  stack.push(id)
  onBeforeUnmount(() => {
    const index = stack.indexOf(id)
    if (index !== -1) stack.splice(index, 1)
  })
  return {
    depth: computed(() => stack.indexOf(id)),
    isTop: () => stack[stack.length - 1] === id,
  }
}

// --- Esc ------------------------------------------------------------------------------------------------------------------

// UI-04 (ревью 2.158.0): Esc не закрывал ни одну из 33 модалок, а вложенные окна («+» быстрого добавления поверх формы устройства)
// нельзя закрывать общим слушателем «закрыть всё» — один Esc снёс бы обе формы и потерял введённое в нижней.
// FE-06 (ревью ветки fix/code-review-main-f06-stage2-f05): раньше для этого был свой стек (useEscapeClose), второй после стека окон, и их
// согласованность держалась на одинаковом порядке вызовов в setup(). Теперь стек один — выше: окно подписывается на Esc этим
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

// --- Блокировка прокрутки -------------------------------------------------------------------------------------------------

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

// --- Точка входа ---------------------------------------------------------------------------------------------------------------

export interface ModalLayerOptions {
  /** Диалог внутри подложки (элемент с role="dialog"): ловушка фокуса держит Tab в нём. Ref или функция — подложка отдаёт его уже после монтирования. */
  dialog: MaybeRefOrGetter<HTMLElement | null | undefined>
  /** Закрыть окно: вызывается по Esc (только у верхнего окна) и по клику на подложку. */
  onClose: () => void
}

export interface ModalLayer extends ModalStackEntry {
  /** Обработчики подложки: `@mousedown="onOverlayPointerDown" @click="onOverlayClick"`. */
  onOverlayPointerDown: (event: MouseEvent) => void
  onOverlayClick: (event: MouseEvent) => void
}

/**
 * Подключает окно ко всем сторонам слоя в правильном порядке (см. заголовок модуля). Вызывать в setup() окна один раз.
 *
 * @example
 * const overlay = ref<HTMLElement | null>(null)
 * const { depth, onOverlayPointerDown, onOverlayClick } = useModalLayer({
 *   dialog: () => overlay.value?.querySelector<HTMLElement>('[role="dialog"]') ?? overlay.value,
 *   onClose: () => emit('close'),
 * })
 */
export function useModalLayer(options: ModalLayerOptions): ModalLayer {
  const entry = useModalStack()
  const { onOverlayPointerDown, onOverlayClick } = useOverlayDismiss(options.onClose)
  // Esc — через стек: закрывается только верхнее окно. defaultPrevented и IME отсеивает сам useEscapeKey.
  useEscapeKey((event) => {
    if (!entry.isTop()) return
    event.preventDefault()
    options.onClose()
  })
  useFocusTrap(options.dialog, entry.isTop)
  useScrollLock()
  return { ...entry, onOverlayPointerDown, onOverlayClick }
}
