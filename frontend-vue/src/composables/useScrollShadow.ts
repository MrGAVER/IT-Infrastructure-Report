// Подсказка «таблица прокручивается» (UI-06 ревью merge/review-2158-executors): на телефоне видны 3 колонки из 9, остальное —
// за горизонтальной прокруткой, и без подсказки пользователь не знает, что она есть.
//
// Композабл следит за контейнером с overflow-x: auto и сообщает, есть ли ещё содержимое слева и справа от видимой части. Сама
// «тень» рисуется стилями компонента ScrollableTableWrap.vue по этим двум флагам. Пересчёт — при прокрутке, при смене размеров
// контейнера или таблицы внутри него (ResizeObserver) и при перерисовке (update() вызывает сам компонент).
import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/** Допуск в пиксели: у дробной прокрутки scrollLeft/scrollWidth округляются, и «до конца не дотянуто на 0,4px» не считается остатком. */
const EDGE_TOLERANCE_PX = 1

export interface ScrollShadowState {
  /** Слева за краем есть непоказанное содержимое (контейнер прокручен вправо). */
  canScrollLeft: Ref<boolean>
  /** Справа за краем есть непоказанное содержимое. */
  canScrollRight: Ref<boolean>
  /** Пересчитать флаги по текущим размерам и прокрутке. */
  update: () => void
}

export function useScrollShadow(target: Ref<HTMLElement | null>): ScrollShadowState {
  const canScrollLeft = ref(false)
  const canScrollRight = ref(false)
  let observer: ResizeObserver | null = null

  function update(): void {
    const el = target.value
    if (!el) return
    const maxScrollLeft = el.scrollWidth - el.clientWidth
    canScrollLeft.value = el.scrollLeft > EDGE_TOLERANCE_PX
    canScrollRight.value = el.scrollLeft < maxScrollLeft - EDGE_TOLERANCE_PX
  }

  onMounted(() => {
    update()
    const el = target.value
    // ResizeObserver есть во всех современных браузерах, но не в jsdom: без него остаются пересчёт при прокрутке и перерисовке.
    if (el && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(update)
      observer.observe(el)
      // Ширину прокручиваемого содержимого задаёт таблица внутри: её рост (длинные значения) меняет scrollWidth, а размер контейнера нет.
      for (const child of Array.from(el.children)) observer.observe(child)
    }
  })

  onBeforeUnmount(() => {
    observer?.disconnect()
    observer = null
  })

  return { canScrollLeft, canScrollRight, update }
}
