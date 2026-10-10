// Центральный стор настроек интерфейса (backend/app/api/preferences.py). Хранит сырые значения;
// осмысленные для интерфейса значения с умолчаниями отдают stores/theme.ts, stores/organization.ts,
// stores/formPreferences.ts и utils/pageSize.ts — они читают отсюда и сюда же пишут.
//
// Где что хранится:
//  - название организации — ОБЩЕЕ для всех, всегда на сервере;
//  - личные настройки (тема, размеры страниц, порог сворачивания): с аутентификацией — на сервере (одинаковы
//    на всех компьютерах пользователя), без неё пользователей нет — в localStorage браузера (userStorage);
//  - токен сессии — в браузере всегда (api/client.ts), это учётные данные.
//
// Сохранение на сервер оптимистичное: значение применяется сразу (интерфейс не ждёт ответа), запросы на сервер идут
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
import {
  LOCAL_ORGANIZATION_NAME_KEY,
  readLocalSettings,
  readLocalUserPreferences,
  removeLocalSettings,
  writeLocalUserPreferences,
} from '../utils/localSettings'

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
  /** id пользователя или null, если аутентификация выключена (тогда личные настройки хранит браузер). */
  userId: string | null
  /** Может ли текущий пользователь менять общие настройки (нужно только для переноса названия организации из браузера). */
  canWriteGlobal: boolean
}

/** Метка загруженного состояния, когда пользователя нет (аутентификация выключена). */
export const LOCAL_IDENTITY = 'local'

// Очередь записи — на уровне модуля, а не состояния стора: это не данные, а порядок выполнения запросов.
let writeQueue: Promise<void> = Promise.resolve()
let loadInFlight: Promise<void> | null = null

export const usePreferencesStore = defineStore('preferences', {
  state: () => ({
    user: {} as UserPreferences,
    global: {} as GlobalPreferences,
    /** Для кого загружено: id пользователя или LOCAL_IDENTITY; null — ещё не загружено или сброшено. */
    loadedFor: null as string | null,
    /** Где хранятся личные настройки: на сервере (есть учётная запись) или в браузере (аутентификация выключена). */
    userStorage: 'server' as 'server' | 'local',
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
      if (this.loadedFor === (options.userId ?? LOCAL_IDENTITY)) return
      if (loadInFlight) return loadInFlight
      loadInFlight = this.doLoad(options).finally(() => {
        loadInFlight = null
      })
      return loadInFlight
    },

    async doLoad(options: LoadOptions): Promise<void> {
      const local = options.userId === null
      this.userStorage = local ? 'local' : 'server'
      const identity = options.userId ?? LOCAL_IDENTITY
      try {
        const data = await fetchPreferences()
        this.global = data.global ?? {}
        this.user = local ? readLocalUserPreferences() : (data.user ?? {})
        this.loadFailed = false
        this.loadedFor = identity
      } catch {
        this.global = {}
        this.user = local ? readLocalUserPreferences() : {}
        this.loadFailed = true
        this.loadedFor = identity // не повторяем при каждой навигации — одно уведомление, дальше умолчания
        useToast().notify('Не удалось загрузить настройки интерфейса — используются значения по умолчанию.', 'warning')
        return
      }
      await this.migrateLocalSettings(options.canWriteGlobal)
    },

    /** Забывает загруженное (выход из учётной записи): следующий пользователь не должен увидеть чужие настройки. */
    reset() {
      this.user = {}
      this.global = {}
      this.loadedFor = null
      this.loadFailed = false
      this.userStorage = 'server'
    },

    /** Личные настройки: применяются сразу. С учётной записью на сервер уходят по очереди (не бросает — о сбое
     * сообщает уведомление), без аутентификации записываются в localStorage браузера (сервера для них нет). */
    saveUser(patch: UserPreferencesPatch): Promise<void> {
      this.user = applyUserPatch(this.user, patch)
      if (this.userStorage === 'local') {
        writeLocalUserPreferences(this.user)
        return Promise.resolve()
      }
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
        // Личные настройки без аутентификации лежат в браузере — серверный ответ их не определяет.
        if (this.userStorage === 'server') this.user = data.user ?? {}
        this.global = data.global ?? {}
      } catch {
        /* сервер недоступен — остаётся то, что показано сейчас */
      }
    },

    /** Разовый перенос значений из localStorage на сервер. Серверное значение всегда главнее локального.
     *  - Личные настройки переносятся только с учётной записью (userStorage = 'server'): без неё localStorage —
     *    их постоянный дом, и ключи остаются на месте. Если позже включить аутентификацию, их заберёт тот
     *    пользователь, который первым войдёт из этого браузера.
     *  - Название организации общее, поэтому переносится в обоих режимах — но только если на сервере его ещё нет
     *    и менять общие настройки можно (администратор или без аутентификации).
     *  Перенесённые ключи удаляются после успешной отправки (или если на сервере уже есть значение); при сбое
     *  остаются до следующего открытия приложения. */
    async migrateLocalSettings(canWriteGlobal: boolean): Promise<void> {
      const local = readLocalSettings()
      if (!local.keys.length) return
      const serverMode = this.userStorage === 'server'

      let userKeysDone = true
      if (serverMode) {
        const userPatch: UserPreferencesPatch = {}
        if (local.colorScheme !== undefined && this.user.color_scheme === undefined) userPatch.color_scheme = local.colorScheme
        if (local.collapseRows !== undefined && this.user.device_vlan_collapse_rows === undefined) {
          userPatch.device_vlan_collapse_rows = local.collapseRows
        }
        const pageSizes = Object.fromEntries(Object.entries(local.pageSizes).filter(([listId]) => this.user.page_sizes?.[listId] === undefined))
        if (Object.keys(pageSizes).length) userPatch.page_sizes = pageSizes
        if (Object.keys(userPatch).length) {
          try {
            await putUserPreferences(userPatch)
            this.user = applyUserPatch(this.user, userPatch)
          } catch {
            userKeysDone = false
          }
        }
      }

      const orgKey = LOCAL_ORGANIZATION_NAME_KEY
      let orgKeyRemovable = true
      const localOrg = local.organizationName
      if (localOrg !== undefined && localOrg !== DEFAULT_ORGANIZATION_NAME && this.global.organization_name === undefined) {
        if (canWriteGlobal) {
          try {
            await putGlobalPreferences({ organization_name: localOrg })
            this.global = applyGlobalPatch(this.global, { organization_name: localOrg })
          } catch {
            orgKeyRemovable = false
          }
        } else {
          orgKeyRemovable = false // менять общее может только администратор — не теряем значение до его входа
        }
      }

      removeLocalSettings(local.keys.filter((key) => (key === orgKey ? orgKeyRemovable : serverMode && userKeysDone)))
    },
  },
})
