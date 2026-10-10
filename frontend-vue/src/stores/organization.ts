// Стор наименования организации, отображаемого в шапке сайдбара (см. Sidebar.vue). Название ОБЩЕЕ для всех
// пользователей и хранится на сервере (stores/preferences.ts, общие настройки); менять его при включённой
// аутентификации может только администратор. Раньше оно лежало в localStorage каждого браузера отдельно.
import { defineStore } from 'pinia'
import { usePreferencesStore } from './preferences'
import { DEFAULT_ORGANIZATION_NAME } from '../utils/preferenceDefaults'

export { DEFAULT_ORGANIZATION_NAME }

export const useOrganizationStore = defineStore('organization', {
  getters: {
    name(): string {
      const stored = usePreferencesStore().global.organization_name
      return stored && stored.trim() ? stored : DEFAULT_ORGANIZATION_NAME
    },
  },
  actions: {
    /** Пустая строка и значение по умолчанию сбрасывают настройку (на сервере запись удаляется). */
    setName(name: string) {
      const trimmed = name.trim()
      void usePreferencesStore().saveGlobal({ organization_name: trimmed && trimmed !== DEFAULT_ORGANIZATION_NAME ? trimmed : null })
    },
    reset() {
      void usePreferencesStore().saveGlobal({ organization_name: null })
    },
  },
})
