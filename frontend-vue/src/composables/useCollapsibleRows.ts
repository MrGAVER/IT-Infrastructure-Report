// Состояние «свёрнут / развёрнут» длинного списка строк в форме (DeviceVlanListEditor, OpenPortListEditor).
//
// Правило: список свёрнут, когда строк БОЛЬШЕ порога и пользователь не развернул его вручную. Ручное
// раскрытие сбрасывается, как только строк снова не больше порога, — следующее превышение (например, «Включить
// в домен» добавило много VLAN) снова свернёт блок. Порог undefined — сворачивание выключено (редактор
// используется без настройки порога).
import { computed, ref, watch, type Ref } from 'vue'

export interface CollapsibleRows {
  /** Строк больше порога — блок можно сворачивать (показывать кнопку). */
  exceedsLimit: Readonly<Ref<boolean>>
  /** Блок сейчас свёрнут. */
  collapsed: Readonly<Ref<boolean>>
  expand: () => void
  toggle: () => void
  /** Вызывать ПЕРЕД добавлением строки: пользователь работает со списком — новая строка не должна тут же
   * скрыться оттого, что с ней строк стало больше порога. */
  expandForAdd: () => void
}

export function useCollapsibleRows(rowCount: () => number, limit: () => number | undefined): CollapsibleRows {
  const expanded = ref(false)
  const exceedsLimit = computed(() => {
    const max = limit()
    return max !== undefined && rowCount() > max
  })
  const collapsed = computed(() => exceedsLimit.value && !expanded.value)
  watch(exceedsLimit, (exceeds) => {
    if (!exceeds) expanded.value = false
  })
  return {
    exceedsLimit,
    collapsed,
    expand: () => {
      expanded.value = true
    },
    toggle: () => {
      expanded.value = !expanded.value
    },
    expandForAdd: () => {
      const max = limit()
      if (max !== undefined && rowCount() + 1 > max) expanded.value = true
    },
  }
}
