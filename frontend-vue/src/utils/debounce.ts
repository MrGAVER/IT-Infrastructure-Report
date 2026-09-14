// Простой debounce без дополнительной зависимости (@vueuse/core не используется в проекте —
// заводить его целиком ради одной функции, когда нужна пара строк, избыточно). Используется
// stores/diagram.ts для дебounced-сохранения раскладки при перетаскивании узла (раздел 12 ТЗ,
// пункт 2 задач Агента B: "дебounced-сохранение раскладки").
export function debounce<Args extends unknown[]>(fn: (...args: Args) => void, waitMs: number): (...args: Args) => void {
  let timer: ReturnType<typeof setTimeout> | null = null
  return (...args: Args) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => fn(...args), waitMs)
  }
}
