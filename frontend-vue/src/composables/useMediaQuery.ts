import { onBeforeUnmount, ref, type Ref } from 'vue'

/**
 * Реактивный результат медиа-запроса (например, '(max-width: 760px)'). Нужен там, где от ширины окна зависит не только стиль, но
 * и состав интерфейса: CSS скрыл бы элемент, но не избавил бы от его монтирования и подсчёта. Без window.matchMedia (jsdom, SSR)
 * возвращает false и ничего не подписывает.
 */
export function useMediaQuery(query: string): Ref<boolean> {
  const matches = ref(false)
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return matches

  const list = window.matchMedia(query)
  matches.value = list.matches
  const onChange = (event: MediaQueryListEvent) => {
    matches.value = event.matches
  }
  list.addEventListener('change', onChange)
  onBeforeUnmount(() => list.removeEventListener('change', onChange))
  return matches
}
