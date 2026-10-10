// Серверные настройки интерфейса: GET/PUT /api/v1/preferences (backend/app/api/preferences.py).
// Раньше жили в localStorage браузера. Значения приходят только заданные — умолчания подставляют сторы,
// которые их читают (stores/theme.ts, stores/organization.ts, stores/formPreferences.ts, utils/pageSize.ts).
import { api } from './client'

/** Личные настройки пользователя (при выключенной аутентификации — общие для всех, кто открыл реестр). */
export interface UserPreferences {
  color_scheme?: string
  device_vlan_collapse_rows?: number
  /** {идентификатор списка: размер страницы} */
  page_sizes?: Record<string, number>
}

/** Общие настройки — одинаковы для всех пользователей; менять может администратор. */
export interface GlobalPreferences {
  organization_name?: string
}

export interface PreferencesResponse {
  global: GlobalPreferences
  user: UserPreferences
}

/** Изменение личных настроек. Поле, которого нет, не меняется; null сбрасывает к умолчанию. page_sizes
 * сливается с сохранённым: null у списка убирает его размер. */
export interface UserPreferencesPatch {
  color_scheme?: string | null
  device_vlan_collapse_rows?: number | null
  page_sizes?: Record<string, number | null>
}

export interface GlobalPreferencesPatch {
  organization_name?: string | null
}

export const fetchPreferences = () => api.get<PreferencesResponse>('/preferences')
export const putUserPreferences = (patch: UserPreferencesPatch) => api.put<PreferencesResponse>('/preferences/user', patch)
export const putGlobalPreferences = (patch: GlobalPreferencesPatch) => api.put<PreferencesResponse>('/preferences/global', patch)
