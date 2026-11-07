import { computed, onBeforeUnmount, shallowReactive, type ComputedRef } from 'vue'

// F-01/F-03 (код-ревью main): окна приложения вкладываются друг в друга («+» быстрого добавления поверх формы устройства,
// выбор VLAN поверх окна группы портов). Порядок вложенности раньше держался на числах z-index («60 против 70») и на порядке
// в DOM. Теперь он один — стек открытых окон: по нему окно знает, что оно верхнее (только верхнее перехватывает Tab) и на
// сколько слоёв поднять подложку над окном под ним.
//
// Запись в стек делается в setup(), а не в onMounted: у родителя setup идёт раньше, чем у ребёнка, а onMounted — наоборот
// (дети монтируются первыми), поэтому окно, вложенное в другое, при монтировании попало бы ПОД родителя.

const stack = shallowReactive<symbol[]>([])

/**
 * Открыто ли хотя бы одно модальное окно. Реактивно: по нему AppShell делает фон страницы inert (FE-03 ревью), пока окно открыто.
 * Атрибут inert ставит один владелец — AppShell, а окна только сообщают о себе стеком: так окно, закрывшееся под открытым мобильным
 * меню, не снимет inert, поставленный меню. Запись в стеке снимается в onBeforeUnmount, то есть до onUnmounted окна (возврат фокуса,
 * useFocusTrap), а перерисовка AppShell идёт в том же проходе планировщика раньше хуков onUnmounted — к возврату фокуса inert уже снят.
 */
export const hasOpenModal = computed(() => stack.length > 0)

export interface ModalLayer {
  /** Номер окна от низа стека: 0 у нижнего, 1 у окна поверх него и так далее. Реактивен: закрылось нижнее — верхние сдвинулись. */
  depth: ComputedRef<number>
  /** Окно сейчас верхнее среди открытых. */
  isTop: () => boolean
}

/** Ставит окно в стек открытых окон и снимает его при размонтировании. Вызывать в setup(). */
export function useModalStack(): ModalLayer {
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
