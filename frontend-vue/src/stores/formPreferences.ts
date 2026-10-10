// Стор клиентских настроек форм (меню «Настройки»). Сейчас одна настройка — при каком количестве строк
// сворачивается блок «VLAN устройства» в форме физического устройства (DeviceVlanListEditor.vue).
// Персистится в localStorage по тому же принципу, что stores/organization.ts и stores/theme.ts: это
// настройка отображения конкретного браузера, а не доменные данные — отдельный ресурс на бэкенде
// ради одного числа избыточен.
import { defineStore } from 'pinia'
import { DEFAULT_VLAN_COLLAPSE_ROWS, isValidVlanCollapseLimit, normalizeVlanCollapseLimit } from '../utils/deviceVlans'

const STORAGE_KEY = 'itr.deviceVlanCollapseRows'

function readStoredLimit(): number {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored !== null) return normalizeVlanCollapseLimit(stored)
  } catch {
    /* localStorage недоступен (приватный режим и т.п.) — используем значение по умолчанию */
  }
  return DEFAULT_VLAN_COLLAPSE_ROWS
}

export const useFormPreferencesStore = defineStore('formPreferences', {
  state: () => ({
    /** Блок «VLAN устройства» свёрнут, если в нём строк БОЛЬШЕ этого числа. */
    deviceVlanCollapseRows: readStoredLimit(),
  }),
  actions: {
    /**
     * Сохраняет порог. Недопустимое значение (не целое, вне 1..1000) НЕ подменяется молча — возвращается
     * false, и вызывающий показывает ошибку; значение в сторе при этом не меняется.
     *
     * @example
     * const ok = useFormPreferencesStore().setDeviceVlanCollapseRows(15) // true
     */
    setDeviceVlanCollapseRows(value: unknown): boolean {
      if (!isValidVlanCollapseLimit(value)) return false
      this.deviceVlanCollapseRows = normalizeVlanCollapseLimit(value)
      try {
        localStorage.setItem(STORAGE_KEY, String(this.deviceVlanCollapseRows))
      } catch {
        /* сохранить не удалось — не критично, просто не переживёт перезагрузку */
      }
      return true
    },
    reset() {
      this.setDeviceVlanCollapseRows(DEFAULT_VLAN_COLLAPSE_ROWS)
    },
  },
})
