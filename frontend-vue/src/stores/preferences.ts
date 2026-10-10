// Центральный стор серверных настроек интерфейса (backend/app/api/preferences.py). Хранит сырые значения,
// пришедшие с сервера; осмысленные для интерфейса значения с умолчаниями отдают stores/theme.ts,
// stores/organization.ts, stores/formPreferences.ts и utils/pageSize.ts — они читают отсюда и сюда же пишут.
//
// Раньше эти настройки жили в localStorage браузера: на другом компьютере и после очистки браузера всё
// возвращалось к умолчаниям. Теперь источник истины — сервер; в localStorage остаётся только токен сессии.
//
// Сохранение оптимистичное: значение применяется сразу (интерфейс не ждёт ответа), запросы на сервер идут
// строго по очереди (быстрые клики по темам не должны прийти в перепутанном порядке), а при ошибке
// показывается уведомление и состояние перечитывается с сервера — интерфейс не расходится с тем, что там лежит.
import { defineStore } from 'pinia'
import {
  fetchPreferences,
  putGlobalPreferences,
  putUserPreferences,
  type GlobalPreferences,
  type GlobalPreferencesPatch,
  type UserPreferences,
  type UserPreferencesPatch,
} from '../api/preferences'
import { useToast } from '../composables/useToast'
import { DEFAULT_ORGANIZATION_NAME } from '../utils/preferenceDefaults'
import { readLegacyLocalSettings, removeLegacyLocalSettings, LEGACY_ORGANIZATION_NAME_KEY } from '../utils/legacyLocalSettings'

/** Применяет изменение к личным настройкам так же, как это делает сервер: null сбрасывает ключ, page_sizes
 * сливается (null у списка убирает его размер, пустой словарь убирает ключ). Входной объект не меняется. */
export function applyUserPatch(current: UserPreferences, patch: UserPreferencesPatch): UserPreferences {
  const next: UserPreferences = { ...current }
  if ('color_scheme' in patch) {
    if (patch.color_scheme == null) delete next.color_scheme
    else next.color_scheme = patch.color_scheme
  }
  if ('device_vlan_collapse_rows' in patch) {
    if (patch.device_vlan_collapse_rows == null) delete next.device_vlan_collapse_rows
    else next.device_vlan_collapse_rows = patch.device_vlan_collapse_rows
  }
  if (patch.page_sizes) {
    const merged = { ...(current.page_sizes ?? {}) }
    for (const [listId, size] of Object.entries(patch.page_sizes)) {
      if (size == null) delete merged[listId]
      else merged[listId] = size
    }
    if (Object.keys(merged).length) next.page_sizes = merged
    else delete next.page_sizes
  }
  return next
}

export function applyGlobalPatch(current: GlobalPreferences, patch: GlobalPreferencesPatch): GlobalPreferences {
  const next: GlobalPreferences = { ...current }
  if ('organization_name' in patch) {
    if (patch.organization_name == null) delete next.organization_name
    else next.organization_name = patch.organization_name
  }
  return next
}

export interface LoadOptions {
  /** Чьи настройки загружены: id пользователя или 'anonymous' (аутентификация выключена). Смена — перезагрузка. */
  identity: string
  /** Может ли текущий пользователь менять общие настройки (нужно только для переноса старого названия организации). */
  canWriteGlobal: boolean
}

// Очередь записи — на уровне модуля, а не состояния стора: это не данные, а порядок выполнения запросов.
let writeQueue: Promise<void> = Promise.resolve()
let loadInFlight: Promise<void> | null = null

export const usePreferencesStore = defineStore('preferences', {
  state: () => ({
    user: {} as UserPreferences,
    global: {} as GlobalPreferences,
    /** Для кого загружено (см. LoadOptions.identity); null — ещё не загружено или сброшено. */
    loadedFor: null as string | null,
    /** Загрузка не удалась — работаем на умолчаниях; настройки по-прежнему можно менять. */
    loadFailed: false,
  }),
  getters: {
    loaded: (state): boolean => state.loadedFor !== null,
  },
  actions: {
    /** Загружает настройки один раз на пользователя; повторный вызов для того же пользователя ничего не
     * делает. Никогда не бросает: без настроек интерфейс работает на умолчаниях. */
    async load(options: LoadOptions): Promise<void> {
      if (this.loadedFor === options.identity) return
      if (loadInFlight) return loadInFlight
      loadInFlight = this.doLoad(options).finally(() => {
        loadInFlight = null
      })
      return loadInFlight
    },

    async doLoad(options: LoadOptions): Promise<void> {
      try {
        const data = await fetchPreferences()
        this.user = data.user ?? {}
        this.global = data.global ?? {}
        this.loadFailed = false
        this.loadedFor = options.identity
      } catch {
        this.user = {}
        this.global = {}
        this.loadFailed = true
        this.loadedFor = options.identity // не повторяем при каждой навигации — одно уведомление, дальше умолчания
        useToast().notify('Не удалось загрузить настройки интерфейса — используются значения по умолчанию.', 'warning')
        return
      }
      await this.migrateLegacySettings(options.canWriteGlobal)
    },

    /** Забывает загруженное (выход из учётной записи): следующий пользователь не должен увидеть чужие настройки. */
    reset() {
      this.user = {}
      this.global = {}
      this.loadedFor = null
      this.loadFailed = false
    },

    /** Личные настройки: применяются сразу, на сервер уходят по очереди. Не бросает — о сбое сообщает уведомление. */
    saveUser(patch: UserPreferencesPatch): Promise<void> {
      this.user = applyUserPatch(this.user, patch)
      return this.enqueue(() => putUserPreferences(patch).then(() => undefined))
    },

    /** Общие настройки (название организации): то же, но менять их может только администратор — иначе сервер
     * ответит 403, уведомление объяснит причину, а значение откатится. */
    saveGlobal(patch: GlobalPreferencesPatch): Promise<void> {
      this.global = applyGlobalPatch(this.global, patch)
      return this.enqueue(() => putGlobalPreferences(patch).then(() => undefined))
    },

    enqueue(task: () => Promise<void>): Promise<void> {
      writeQueue = writeQueue.then(task).catch(async (err: unknown) => {
        useToast().notifyError(err)
        await this.refresh()
      })
      return writeQueue
    },

    /** Перечитывает настройки с сервера, отбрасывая оптимистичные изменения (после неудачного сохранения). */
    async refresh(): Promise<void> {
      try {
        const data = await fetchPreferences()
        this.user = data.user ?? {}
        this.global = data.global ?? {}
      } catch {
        /* сервер недоступен — остаётся то, что показано сейчас */
      }
    },

    /** Разовый перенос значений из localStorage прежних версий. Серверное значение всегда главнее старого
     * локального. Старые ключи удаляются только после того, как их содержимое либо перенесено, либо уже
     * есть на сервере: при сбое переноса они остаются до следующего открытия приложения. */
    async migrateLegacySettings(canWriteGlobal: boolean): Promise<void> {
      const legacy = readLegacyLocalSettings()
      if (!legacy.keys.length) return

      const userPatch: UserPreferencesPatch = {}
      if (legacy.colorScheme !== undefined && this.user.color_scheme === undefined) userPatch.color_scheme = legacy.colorScheme
      if (legacy.deviceVlanCollapseRows !== undefined && this.user.device_vlan_collapse_rows === undefined) {
        userPatch.device_vlan_collapse_rows = legacy.deviceVlanCollapseRows
      }
      const pageSizes = Object.fromEntries(Object.entries(legacy.pageSizes).filter(([listId]) => this.user.page_sizes?.[listId] === undefined))
      if (Object.keys(pageSizes).length) userPatch.page_sizes = pageSizes

      let userKeysDone = true
      if (Object.keys(userPatch).length) {
        try {
          await putUserPreferences(userPatch)
          this.user = applyUserPatch(this.user, userPatch)
        } catch {
          userKeysDone = false
        }
      }

      // Название организации общее: переносим, только если на сервере его ещё нет и менять общие настройки
      // можно. Иначе (его уже задали / менять нельзя) локальное значение либо лишнее, либо ждёт своего часа.
      const orgKey = LEGACY_ORGANIZATION_NAME_KEY
      let orgKeyRemovable = true
      const legacyOrg = legacy.organizationName
      if (legacyOrg !== undefined && legacyOrg !== DEFAULT_ORGANIZATION_NAME && this.global.organization_name === undefined) {
        if (canWriteGlobal) {
          try {
            await putGlobalPreferences({ organization_name: legacyOrg })
            this.global = applyGlobalPatch(this.global, { organization_name: legacyOrg })
          } catch {
            orgKeyRemovable = false
          }
        } else {
          orgKeyRemovable = false // менять общее может только администратор — не теряем значение до его входа
        }
      }

      removeLegacyLocalSettings(legacy.keys.filter((key) => (key === orgKey ? orgKeyRemovable : userKeysDone)))
    },
  },
})
