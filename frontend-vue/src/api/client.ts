// Тонкая обёртка над fetch() для /api/v1.
//
// В dev-режиме запросы идут на относительный путь /api/v1/..., а Vite dev-сервер
// проксирует их на бэкенд (см. vite.config.ts, server.proxy) — то же самое
// поведение, что и в проде, где FastAPI отдаёт собранный dist/ со своего же origin
// (см. backend/app/api/system.py: GET '/' отдаёт FRONTEND_DIR/index.html).
// Благодаря этому не нужен CORS в dev и не нужно переключать base URL между режимами.
const API_BASE = '/api/v1'

// --- Токен сессии (см. stores/auth.ts) -----------------------------------------------------
// localStorage, а не Pinia-стейт как единственный источник истины: страница может быть
// перезагружена (F5, прямой переход по URL — тот же SPA-фоллбэк, что и для остальных
// маршрутов, см. backend/app/main.py:spa_fallback), и токен должен пережить перезагрузку без
// повторного похода на /auth/login. Cookie здесь намеренно не используются (см. main.py:
// allow_credentials=False) — токен передаётся только явным заголовком Authorization, который
// в отличие от cookie браузер никогда не добавляет сам, а значит нет и CSRF-поверхности.
const TOKEN_STORAGE_KEY = 'itr:auth-token'

export function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null // приватный режим браузера иногда бросает исключение на доступ к localStorage
  }
}

export function setStoredToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token)
    else localStorage.removeItem(TOKEN_STORAGE_KEY)
  } catch {
    /* см. getStoredToken — молча игнорируем окружения без доступа к localStorage */
  }
}

// --- Токен первичной настройки (INFRA_REGISTRY_SETUP_TOKEN на сервере) --------------------------
// Пока аутентификация выключена, создавать пользователей и включать её можно только с localhost либо
// с этим токеном в заголовке X-Setup-Token (backend/app/services/auth.py:require_setup_access). Нужен
// он только при удалённой настройке (Docker, обратный прокси). sessionStorage, а не localStorage:
// токен установки одноразовый по смыслу и не должен переживать закрытие вкладки.
const SETUP_TOKEN_STORAGE_KEY = 'itr:setup-token'

export function getStoredSetupToken(): string | null {
  try {
    return sessionStorage.getItem(SETUP_TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function setStoredSetupToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(SETUP_TOKEN_STORAGE_KEY, token)
    else sessionStorage.removeItem(SETUP_TOKEN_STORAGE_KEY)
  } catch {
    /* см. getStoredToken */
  }
}

/** Событие на 401 от бэкенда: токен истёк/отозван (logout на другой вкладке, смена пароля
 * администратором и т.п.). authStore слушает его в main.ts, а не наоборот (stores/auth.ts не
 * импортируется отсюда), чтобы не заводить цикл client.ts -> stores/auth.ts -> client.ts. */
export const UNAUTHORIZED_EVENT = 'itr:unauthorized'

export class ApiError extends Error {
  status: number
  /** Код ошибки из detail.code (см. backend/app/constants.py:ErrorCode) — например
   * DUPLICATE_SYSTEM_NAME, RACK_POSITION_OCCUPIED, REFERENCED_BY_OTHER_RECORDS.
   * Используется, чтобы предлагать "сохранить всё равно?" так же, как в текущем
   * vanilla-фронтенде (см. parseApiError()/confirm() в frontend/static/app.js:saveForm). */
  code: string | null
  constructor(status: number, message: string, code: string | null = null) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getStoredToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  // Токен установки уходит только на /auth/*: остальным эндпоинтам он ни к чему.
  const setupToken = path.startsWith('/auth/') ? getStoredSetupToken() : null
  if (setupToken) headers['X-Setup-Token'] = setupToken

  const res = await fetch(`${API_BASE}${path}`, { headers, ...init })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    let message = text || res.statusText
    let code: string | null = null
    try {
      const parsed = JSON.parse(text)
      if (typeof parsed.detail === 'string') {
        message = parsed.detail
      } else if (parsed.detail && typeof parsed.detail === 'object') {
        message = parsed.detail.message ?? message
        code = parsed.detail.code ?? null
      }
    } catch {
      /* тело не JSON — оставляем текст как есть */
    }
    // Не для /auth/login: там 401 — это ожидаемый "неверный пароль" в форме входа, а не
    // разлогинивание уже вошедшего пользователя, событие тут ни к чему.
    if (res.status === 401 && path !== '/auth/login') {
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
    }
    throw new ApiError(res.status, message, code)
  }
  if (res.status === 204) return null as T
  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}

/**
 * Универсальный CRUD-ресурс — см. backend/app/api/resources.py, /api/v1/resources/{resource}.
 * Важно: эндпоинт всегда отдаёт {items, total, offset, limit} (см.
 * backend/app/services/crud.py:list_resource), а НЕ голый массив — легко перепутать
 * с /api/v1/devices, у которого total есть, но offset/limit нет (там нет пагинации
 * на бэкенде, см. api/types.ts:DevicesResponse).
 */
export interface PagedResponse<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}

export function listResource<T>(resource: string, params?: Record<string, string | number>) {
  const qs = params
    ? '?' + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()
    : ''
  return api.get<PagedResponse<T>>(`/resources/${resource}${qs}`)
}

export function createResource<T>(resource: string, payload: Record<string, unknown>) {
  return api.post<T>(`/resources/${resource}`, payload)
}

export function updateResource<T>(resource: string, id: string, payload: Record<string, unknown>) {
  return api.put<T>(`/resources/${resource}/${id}`, payload)
}

export function deleteResource(resource: string, id: string) {
  return api.delete<{ status: string; id: string }>(`/resources/${resource}/${id}`)
}

/** Коды detail.code структурированных 409-ошибок — см. backend/app/constants.py:ErrorCode. */
export const ErrorCode = {
  DUPLICATE_SYSTEM_NAME: 'DUPLICATE_SYSTEM_NAME',
  RACK_POSITION_OCCUPIED: 'RACK_POSITION_OCCUPIED',
  REFERENCED_BY_OTHER_RECORDS: 'REFERENCED_BY_OTHER_RECORDS',
  DUPLICATE_USERNAME: 'DUPLICATE_USERNAME',
  WEAK_PASSWORD: 'WEAK_PASSWORD',
  LAST_ADMIN_ACCOUNT: 'LAST_ADMIN_ACCOUNT',
  ACCOUNT_LOCKED: 'ACCOUNT_LOCKED',
  AUTH_REQUIRES_ADMIN: 'AUTH_REQUIRES_ADMIN',
} as const
