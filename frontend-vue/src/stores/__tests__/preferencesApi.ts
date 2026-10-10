// Общий помощник тестов: подменяет fetch так, чтобы /api/v1/preferences вёл себя как сервер (хранит значения,
// применяет изменения теми же правилами, что backend/app/services/preferences.py) и записывает запросы.
import { vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { applyGlobalPatch, applyUserPatch, usePreferencesStore } from '../preferences'
import type { GlobalPreferences, GlobalPreferencesPatch, UserPreferences, UserPreferencesPatch } from '../../api/preferences'

export interface PreferencesApiStub {
  /** «Серверное» состояние — его можно менять между запросами. */
  server: { user: UserPreferences; global: GlobalPreferences }
  userPuts: UserPreferencesPatch[]
  globalPuts: GlobalPreferencesPatch[]
  gets: number
  /** Статус, которым сервер отвечает на следующие PUT (например 403/500); 0 — нормальная работа. */
  failPutsWith: number
  /** Статус для GET (например 500); 0 — нормальная работа. */
  failGetWith: number
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** Подменяет глобальный fetch ТОЛЬКО для /preferences; любые другие адреса получают пустой список. */
export function stubPreferencesApi(initial: { user?: UserPreferences; global?: GlobalPreferences } = {}): PreferencesApiStub {
  const stub: PreferencesApiStub = {
    server: { user: { ...(initial.user ?? {}) }, global: { ...(initial.global ?? {}) } },
    userPuts: [],
    globalPuts: [],
    gets: 0,
    failPutsWith: 0,
    failGetWith: 0,
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/preferences') && method === 'GET') {
        stub.gets++
        if (stub.failGetWith) return json({ detail: 'Ошибка сервера' }, stub.failGetWith)
        return json({ global: stub.server.global, user: stub.server.user })
      }
      if (url.endsWith('/preferences/user') && method === 'PUT') {
        const patch = JSON.parse(init!.body as string) as UserPreferencesPatch
        stub.userPuts.push(patch)
        if (stub.failPutsWith) return json({ detail: 'Не удалось сохранить' }, stub.failPutsWith)
        stub.server.user = applyUserPatch(stub.server.user, patch)
        return json({ global: stub.server.global, user: stub.server.user })
      }
      if (url.endsWith('/preferences/global') && method === 'PUT') {
        const patch = JSON.parse(init!.body as string) as GlobalPreferencesPatch
        stub.globalPuts.push(patch)
        if (stub.failPutsWith) return json({ detail: 'Общие настройки может менять только администратор.' }, stub.failPutsWith)
        stub.server.global = applyGlobalPatch(stub.server.global, patch)
        return json({ global: stub.server.global, user: stub.server.user })
      }
      return json({ items: [], total: 0, offset: 0, limit: 1000 })
    }),
  )
  return stub
}

/** «Перезагрузка страницы» в тесте без HTTP: новое приложение (новый pinia), в которое настройки уже подтянуты с
 * сервера — те самые, что были в старом. Так проверяется, что выбор пользователя переживает перезагрузку. */
export function reloadPinia(): void {
  const old = usePreferencesStore()
  const user = JSON.parse(JSON.stringify(old.user))
  const global = JSON.parse(JSON.stringify(old.global))
  setActivePinia(createPinia())
  const fresh = usePreferencesStore()
  fresh.user = user
  fresh.global = global
  fresh.loadedFor = 'anonymous'
}
