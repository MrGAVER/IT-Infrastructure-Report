// Настройки форм (меню «Настройки» → «Формы»). Сейчас одна — при каком количестве строк сворачиваются длинные
// списки в форме устройства: блок «VLAN устройства» (DeviceVlanListEditor.vue) и «Открытые порты»
// (OpenPortListEditor.vue). Порог пока общий для обоих. Личная настройка пользователя: с аутентификацией хранится
// на сервере (одинакова на всех его компьютерах), без неё — в браузере (stores/preferences.ts).
//
// Имя сохранённого ключа (device_vlan_collapse_rows / itr.deviceVlanCollapseRows) историческое — он появился для
// блока VLAN и сохранён, чтобы не переносить уже записанные значения.
import { defineStore } from 'pinia'
import { usePreferencesStore } from './preferences'
import { DEFAULT_COLLAPSE_ROWS, isValidCollapseLimit, normalizeCollapseLimit } from '../utils/collapseLimit'

export const useFormPreferencesStore = defineStore('formPreferences', {
  getters: {
    /** Список свёрнут, если в нём строк БОЛЬШЕ этого числа. */
    collapseRows(): number {
      const stored = usePreferencesStore().user.device_vlan_collapse_rows
      return stored !== undefined && isValidCollapseLimit(stored) ? stored : DEFAULT_COLLAPSE_ROWS
    },
  },
  actions: {
    /**
     * Сохраняет порог. Недопустимое значение (не целое, вне 1..1000) НЕ подменяется молча — возвращается
     * false, и вызывающий показывает ошибку; значение при этом не меняется. Применяется сразу; на сервер
     * (или в браузер, без аутентификации) уходит в фоне.
     *
     * @example
     * const ok = useFormPreferencesStore().setCollapseRows(15) // true
     */
    setCollapseRows(value: unknown): boolean {
      if (!isValidCollapseLimit(value)) return false
      void usePreferencesStore().saveUser({ device_vlan_collapse_rows: normalizeCollapseLimit(value) })
      return true
    },
    reset() {
      void usePreferencesStore().saveUser({ device_vlan_collapse_rows: null })
    },
  },
})
