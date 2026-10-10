// Настройки форм (меню «Настройки» → «Формы»). Сейчас одна — при каком количестве строк сворачивается блок
// «VLAN устройства» в форме физического устройства (DeviceVlanListEditor.vue). Личная настройка пользователя:
// хранится на сервере (stores/preferences.ts), поэтому одинакова на всех его компьютерах.
import { defineStore } from 'pinia'
import { usePreferencesStore } from './preferences'
import { DEFAULT_VLAN_COLLAPSE_ROWS, isValidVlanCollapseLimit, normalizeVlanCollapseLimit } from '../utils/deviceVlans'

export const useFormPreferencesStore = defineStore('formPreferences', {
  getters: {
    /** Блок «VLAN устройства» свёрнут, если в нём строк БОЛЬШЕ этого числа. */
    deviceVlanCollapseRows(): number {
      const stored = usePreferencesStore().user.device_vlan_collapse_rows
      return stored !== undefined && isValidVlanCollapseLimit(stored) ? stored : DEFAULT_VLAN_COLLAPSE_ROWS
    },
  },
  actions: {
    /**
     * Сохраняет порог. Недопустимое значение (не целое, вне 1..1000) НЕ подменяется молча — возвращается
     * false, и вызывающий показывает ошибку; значение при этом не меняется. Применяется сразу, на сервер
     * уходит в фоне (при сбое — уведомление и откат).
     *
     * @example
     * const ok = useFormPreferencesStore().setDeviceVlanCollapseRows(15) // true
     */
    setDeviceVlanCollapseRows(value: unknown): boolean {
      if (!isValidVlanCollapseLimit(value)) return false
      void usePreferencesStore().saveUser({ device_vlan_collapse_rows: normalizeVlanCollapseLimit(value) })
      return true
    },
    reset() {
      void usePreferencesStore().saveUser({ device_vlan_collapse_rows: null })
    },
  },
})
