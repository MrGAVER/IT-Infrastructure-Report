// Простой debounce без дополнительной зависимости (@vueuse/core не используется в проекте —
// заводить его целиком ради одной функции, когда нужна пара строк, избыточно). Используется
// stores/diagram.ts для дебounced-сохранения раскладки при перетаскивании узла (раздел 12 ТЗ,
// пункт 2 задач Агента B: "дебounced-сохранение раскладки") и дашбордом «Подключения» для
// поиска по серверу.
//
// cancel() отменяет ещё не сработавший вызов — нужно, когда результат уже не нужен (компонент
// размонтирован) или его опережает немедленное действие (смена фильтра при набранном поиске).
export type Debounced<Args extends unknown[]> = ((...args: Args) => void) & { cancel: () => void }

export function debounce<Args extends unknown[]>(fn: (...args: Args) => void, waitMs: number): Debounced<Args> {
  let timer: ReturnType<typeof setTimeout> | null = null
  const debounced = ((...args: Args) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = null
      fn(...args)
    }, waitMs)
  }) as Debounced<Args>
  debounced.cancel = () => {
    if (timer) clearTimeout(timer)
    timer = null
  }
  return debounced
}
