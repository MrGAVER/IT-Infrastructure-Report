// Настройки интерфейса в localStorage браузера. Используются в двух случаях:
//  1) аутентификация выключена — пользователей нет, личные настройки (тема, размеры страниц, порог
//     сворачивания) хранит сам браузер (readLocalUserPreferences / writeLocalUserPreferences);
//  2) аутентификация включена — при входе значения, оставшиеся в браузере от прежних версий или от работы
//     без аутентификации, разово переносятся на сервер (readLocalSettings / removeLocalSettings, см.
//     stores/preferences.ts:migrateLocalSettings).
// Модуль не зависит от сторов. Токен сессии (itr:auth-token) сюда не относится: это учётные данные, и в
// браузере он остаётся всегда (api/client.ts).
import type { UserPreferences } from '../api/preferences'

export const LOCAL_COLOR_SCHEME_KEY = 'itr.colorScheme'
/** Название организации теперь общее и хранится на сервере; ключ нужен только для разового переноса. */
export const LOCAL_ORGANIZATION_NAME_KEY = 'itr.organizationName'
/** Общий порог сворачивания длинных списков. Имя ключа историческое (появился для блока «VLAN устройства»). */
export const LOCAL_COLLAPSE_ROWS_KEY = 'itr.deviceVlanCollapseRows'
export const LOCAL_PAGE_SIZE_PREFIX = 'itr.pageSize.'

export interface LocalSettings {
  colorScheme?: string
  organizationName?: string
  collapseRows?: number
  pageSizes: Record<string, number>
  /** Все найденные ключи настроек (в том числе с испорченным значением) — их удаляют после переноса. */
  keys: string[]
}

const COLOR_SCHEME_PATTERN = /^[a-z0-9_-]{1,32}$/
const LIST_ID_PATTERN = /^[A-Za-z0-9_.-]{1,60}$/

function isCount(value: number): boolean {
  return Number.isInteger(value) && value >= 1 && value <= 1000
}

/** Читает и проверяет значения. Испорченное (не прошло проверку) в результат не попадает, но ключ остаётся
 * в keys — чтобы его тоже убрали при переносе. Недоступный localStorage (приватный режим) — пустой результат. */
export function readLocalSettings(): LocalSettings {
  const result: LocalSettings = { pageSizes: {}, keys: [] }
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (!key) continue
      const value = localStorage.getItem(key)
      if (value === null) continue
      if (key === LOCAL_COLOR_SCHEME_KEY) {
        result.keys.push(key)
        if (COLOR_SCHEME_PATTERN.test(value)) result.colorScheme = value
      } else if (key === LOCAL_ORGANIZATION_NAME_KEY) {
        result.keys.push(key)
        if (value.trim() && value.length <= 200) result.organizationName = value.trim()
      } else if (key === LOCAL_COLLAPSE_ROWS_KEY) {
        result.keys.push(key)
        const n = Number(value)
        if (value.trim() !== '' && isCount(n)) result.collapseRows = n
      } else if (key.startsWith(LOCAL_PAGE_SIZE_PREFIX)) {
        result.keys.push(key)
        const listId = key.slice(LOCAL_PAGE_SIZE_PREFIX.length)
        const n = Number(value)
        if (LIST_ID_PATTERN.test(listId) && value.trim() !== '' && isCount(n)) result.pageSizes[listId] = n
      }
    }
  } catch {
    /* localStorage недоступен — читать нечего */
  }
  return result
}

export function removeLocalSettings(keys: readonly string[]): void {
  try {
    for (const key of keys) localStorage.removeItem(key)
  } catch {
    /* см. readLocalSettings */
  }
}

/** Личные настройки из браузера (без названия организации — оно серверное) в том же виде, что приходят с сервера. */
export function readLocalUserPreferences(): UserPreferences {
  const local = readLocalSettings()
  const prefs: UserPreferences = {}
  if (local.colorScheme !== undefined) prefs.color_scheme = local.colorScheme
  if (local.collapseRows !== undefined) prefs.device_vlan_collapse_rows = local.collapseRows
  if (Object.keys(local.pageSizes).length) prefs.page_sizes = local.pageSizes
  return prefs
}

/** Приводит личные настройки в браузере в точное соответствие с prefs: заданные значения записываются, а
 * ключи тех настроек, которых в prefs нет (сброшены к умолчанию), удаляются. Ключ названия организации не
 * трогается. Недоступный localStorage не роняет запись: настройка просто не переживёт перезагрузку. */
export function writeLocalUserPreferences(prefs: UserPreferences): void {
  try {
    const setOrRemove = (key: string, value: string | undefined) => {
      if (value === undefined) localStorage.removeItem(key)
      else localStorage.setItem(key, value)
    }
    setOrRemove(LOCAL_COLOR_SCHEME_KEY, prefs.color_scheme)
    setOrRemove(LOCAL_COLLAPSE_ROWS_KEY, prefs.device_vlan_collapse_rows === undefined ? undefined : String(prefs.device_vlan_collapse_rows))
    const wanted = prefs.page_sizes ?? {}
    for (const [listId, size] of Object.entries(wanted)) localStorage.setItem(LOCAL_PAGE_SIZE_PREFIX + listId, String(size))
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i)
      if (key && key.startsWith(LOCAL_PAGE_SIZE_PREFIX) && !(key.slice(LOCAL_PAGE_SIZE_PREFIX.length) in wanted)) localStorage.removeItem(key)
    }
  } catch {
    /* см. readLocalSettings */
  }
}
