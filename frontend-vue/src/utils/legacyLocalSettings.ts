// Разовый перенос настроек, которые прежние версии хранили в localStorage браузера, на сервер.
//
// Модуль только читает и удаляет СТАРЫЕ ключи (в новом коде localStorage для настроек не используется) и не
// зависит от сторов — переносом заведует stores/preferences.ts. Токен сессии (itr:auth-token) сюда не
// относится: это учётные данные, и в браузере он остаётся (api/client.ts).
export const LEGACY_COLOR_SCHEME_KEY = 'itr.colorScheme'
export const LEGACY_ORGANIZATION_NAME_KEY = 'itr.organizationName'
export const LEGACY_VLAN_COLLAPSE_ROWS_KEY = 'itr.deviceVlanCollapseRows'
export const LEGACY_PAGE_SIZE_PREFIX = 'itr.pageSize.'

export interface LegacyLocalSettings {
  colorScheme?: string
  organizationName?: string
  deviceVlanCollapseRows?: number
  pageSizes: Record<string, number>
  /** Все найденные старые ключи (в том числе испорченные) — их удаляют после переноса. */
  keys: string[]
}

const COLOR_SCHEME_PATTERN = /^[a-z0-9_-]{1,32}$/
const LIST_ID_PATTERN = /^[A-Za-z0-9_.-]{1,60}$/

function isCount(value: number): boolean {
  return Number.isInteger(value) && value >= 1 && value <= 1000
}

/** Читает и проверяет старые значения. Испорченное (не прошло проверку) в результат не попадает, но ключ
 * остаётся в keys — чтобы его тоже убрали. Недоступный localStorage (приватный режим) — пустой результат. */
export function readLegacyLocalSettings(): LegacyLocalSettings {
  const result: LegacyLocalSettings = { pageSizes: {}, keys: [] }
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (!key) continue
      const value = localStorage.getItem(key)
      if (value === null) continue
      if (key === LEGACY_COLOR_SCHEME_KEY) {
        result.keys.push(key)
        if (COLOR_SCHEME_PATTERN.test(value)) result.colorScheme = value
      } else if (key === LEGACY_ORGANIZATION_NAME_KEY) {
        result.keys.push(key)
        if (value.trim() && value.length <= 200) result.organizationName = value.trim()
      } else if (key === LEGACY_VLAN_COLLAPSE_ROWS_KEY) {
        result.keys.push(key)
        const n = Number(value)
        if (value.trim() !== '' && isCount(n)) result.deviceVlanCollapseRows = n
      } else if (key.startsWith(LEGACY_PAGE_SIZE_PREFIX)) {
        result.keys.push(key)
        const listId = key.slice(LEGACY_PAGE_SIZE_PREFIX.length)
        const n = Number(value)
        if (LIST_ID_PATTERN.test(listId) && value.trim() !== '' && isCount(n)) result.pageSizes[listId] = n
      }
    }
  } catch {
    /* localStorage недоступен — переносить нечего */
  }
  return result
}

export function removeLegacyLocalSettings(keys: readonly string[]): void {
  try {
    for (const key of keys) localStorage.removeItem(key)
  } catch {
    /* см. readLegacyLocalSettings */
  }
}
