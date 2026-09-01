// Стор наименования организации, отображаемого в шапке сайдбара (см. Sidebar.vue). Раньше
// строка "ООО «Организация»" была захардкожена в шаблоне — п.6 фикса просит вынести её в
// настройки. Персистится в localStorage по тому же принципу, что и stores/theme.ts
// (клиентская настройка отображения, не доменные данные — заводить ради одной строки
// отдельный ресурс на бэкенде и гонять его через /api/v1/resources избыточно).
import { defineStore } from 'pinia'

export const DEFAULT_ORGANIZATION_NAME = 'ООО «Организация»'

const STORAGE_KEY = 'itr.organizationName'

function readStoredName(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && stored.trim()) return stored
  } catch {
    /* localStorage недоступен (приватный режим и т.п.) — используем значение по умолчанию */
  }
  return DEFAULT_ORGANIZATION_NAME
}

export const useOrganizationStore = defineStore('organization', {
  state: () => ({
    name: readStoredName(),
  }),
  actions: {
    setName(name: string) {
      const trimmed = name.trim()
      this.name = trimmed || DEFAULT_ORGANIZATION_NAME
      try {
        localStorage.setItem(STORAGE_KEY, this.name)
      } catch {
        /* сохранить не удалось — не критично, просто не переживёт перезагрузку */
      }
    },
    reset() {
      this.setName(DEFAULT_ORGANIZATION_NAME)
    },
  },
})
