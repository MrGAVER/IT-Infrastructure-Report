// Тонкая обёртка над fetch() для /api/v1.
//
// В dev-режиме запросы идут на относительный путь /api/v1/..., а Vite dev-сервер
// проксирует их на бэкенд (см. vite.config.ts, server.proxy) — то же самое
// поведение, что и в проде, где FastAPI отдаёт собранный dist/ со своего же origin
// (см. backend/app/main.py:spa_fallback: отдаёт index.html из FRONTEND_DIR).
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

/** Пути, на которых ответ 401 означает «неверные данные в форме», а не «сессия недействительна»:
 * вход (`/auth/login`) и смена собственного пароля (`/auth/me/password`). Сервер отвечает на неверный ТЕКУЩИЙ пароль кодом
 * 422 WRONG_CURRENT_PASSWORD (backend/app/services/auth.py:change_own_password, A-22), а не 401 — запись оставлена на случай старого
 * сервера. Для этих путей UNAUTHORIZED_EVENT не отправляется, иначе опечатка в форме завершила бы сессию. */
const SESSION_NEUTRAL_401_PATHS: ReadonlySet<string> = new Set(['/auth/login', '/auth/me/password'])

export class ApiError extends Error {
  status: number
  /** Код ошибки из detail.code (см. backend/app/constants.py:ErrorCode) — например
   * DUPLICATE_SYSTEM_NAME, RACK_POSITION_OCCUPIED, REFERENCED_BY_OTHER_RECORDS.
   * Используется, чтобы предлагать "сохранить всё равно?" так же, как в прежнем
   * vanilla-фронтенде (parseApiError()/confirm() в saveForm, до 2.60.0). */
  code: string | null
  /** Через сколько секунд повторить запрос — из заголовка Retry-After (429 TOO_MANY_ATTEMPTS при переборе пароля).
   * null — заголовка нет или он не распознан. */
  retryAfter: number | null
  constructor(status: number, message: string, code: string | null = null, retryAfter: number | null = null) {
    super(message)
    this.status = status
    this.code = code
    this.retryAfter = retryAfter
  }
}

/** Retry-After: целое число секунд либо HTTP-дата (RFC 9110). Возвращает секунды (≥ 0, округление вверх) или null. */
export function parseRetryAfter(value: string | null | undefined, now: number = Date.now()): number | null {
  const text = value?.trim()
  if (!text) return null
  if (/^\d+$/.test(text)) {
    const seconds = Number(text)
    return Number.isSafeInteger(seconds) ? seconds : null
  }
  // HTTP-дата всегда содержит названия дня и месяца; без этой проверки Date.parse принял бы за дату и «-5», и «1.5».
  if (!/[A-Za-z]/.test(text)) return null
  // HTTP-дата (RFC 9110) всегда с поясом (GMT), поэтому Date.parse здесь однозначен — правило B-03 про naive-даты сервера не при чём.
  // eslint-disable-next-line no-restricted-syntax
  const at = Date.parse(text)
  if (Number.isNaN(at)) return null
  return Math.max(0, Math.ceil((at - now) / 1000))
}

/** Ожидание ответа по умолчанию: зависший запрос не должен блокировать экран бесконечно. */
export const DEFAULT_REQUEST_TIMEOUT_MS = 30_000
/** Для заведомо долгих операций (формирование отчётов, расчёт и применение синхронизации портов). */
export const LONG_REQUEST_TIMEOUT_MS = 180_000

/** Коды ошибок, которые порождает сам клиент (в отличие от ErrorCode — кодов ответов сервера). */
export const ClientErrorCode = {
  /** Сервер не ответил за отведённое время (см. RequestOptions.timeoutMs). */
  REQUEST_TIMEOUT: 'REQUEST_TIMEOUT',
} as const

/** Необязательные параметры запроса для методов `api.*`. */
export interface RequestOptions {
  /** Отмена запроса снаружи (смена фильтра, уход с экрана). Отменённый запрос отклоняется исходным `AbortError`,
   * а не `ApiError`, — вызывающий код отличает «отменили сами» от «сервер не ответил». */
  signal?: AbortSignal
  /** Сколько ждать ответ целиком (включая тело), мс. По умолчанию DEFAULT_REQUEST_TIMEOUT_MS. */
  timeoutMs?: number
}

/** Объединяет внешнюю отмену и таймаут в один AbortSignal. Таймер сделан на AbortController + setTimeout, а не на
 * AbortSignal.timeout()/any(): работает в любом браузере и управляется фейковыми таймерами в тестах. */
function createRequestSignal(external: AbortSignal | null | undefined, timeoutMs: number) {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  const onExternalAbort = () => controller.abort(external?.reason)
  if (external?.aborted) onExternalAbort()
  else external?.addEventListener('abort', onExternalAbort, { once: true })
  return {
    signal: controller.signal,
    wasTimeout: () => timedOut && !external?.aborted,
    dispose() {
      clearTimeout(timer)
      external?.removeEventListener('abort', onExternalAbort)
    },
  }
}

/** Низкоуровневый запрос: то же, что `api.*`, но с произвольным `init` (свои заголовки, метод, тело). Служебные
 * заголовки добавляются, а не заменяются, поэтому `init.headers` безопасен. Обычному коду достаточно `api.*`. */
export async function request<T>(path: string, init: RequestInit = {}, options: RequestOptions = {}): Promise<T> {
  // Заголовки вызывающего кода дополняются, а не заменяются: служебные (Content-Type, Authorization, X-Setup-Token)
  // выставляются только если вызывающий не задал их сам. Раньше `{ headers, ...init }` целиком подменял набор.
  const headers = new Headers(init.headers)
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const token = getStoredToken()
  if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)
  // Токен установки уходит только на /auth/*: остальным эндпоинтам он ни к чему.
  const setupToken = path.startsWith('/auth/') ? getStoredSetupToken() : null
  if (setupToken && !headers.has('X-Setup-Token')) headers.set('X-Setup-Token', setupToken)

  const guard = createRequestSignal(options.signal ?? init.signal, options.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS)
  try {
    const res = await fetch(`${API_BASE}${path}`, { ...init, headers, signal: guard.signal })
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
      // Не для путей из SESSION_NEUTRAL_401_PATHS: там 401 — это ожидаемая ошибка в форме
      // ("неверный пароль" при входе, "неверный текущий пароль" при смене), а не признак того,
      // что сессия уже вошедшего пользователя недействительна.
      if (res.status === 401 && !SESSION_NEUTRAL_401_PATHS.has(path)) {
        window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
      }
      throw new ApiError(res.status, message, code, parseRetryAfter(res.headers.get('Retry-After')))
    }
    if (res.status === 204) return null as T
    return (await res.json()) as T
  } catch (e) {
    if (guard.wasTimeout()) {
      throw new ApiError(0, 'Сервер не отвечает. Проверьте соединение и повторите попытку.', ClientErrorCode.REQUEST_TIMEOUT)
    }
    throw e
  } finally {
    guard.dispose()
  }
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>(path, {}, options),
  post: <T>(path: string, body: unknown, options?: RequestOptions) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }, options),
  put: <T>(path: string, body: unknown, options?: RequestOptions) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body) }, options),
  delete: <T>(path: string, options?: RequestOptions) => request<T>(path, { method: 'DELETE' }, options),
}

/**
 * Универсальный CRUD-ресурс — см. backend/app/api/resources.py, /api/v1/resources/{resource}.
 * Важно: эндпоинт всегда отдаёт {items, total, offset, limit} (см.
 * backend/app/services/crud/generic.py:list_resource), а НЕ голый массив — легко перепутать
 * с /api/v1/devices, у которого total есть, но offset/limit нет (там нет пагинации
 * на бэкенде, см. api/types.ts:DevicesResponse).
 */
export interface PagedResponse<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}

export function listResource<T>(resource: string, params?: Record<string, string | number>, options?: RequestOptions) {
  const qs = params
    ? '?' + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()
    : ''
  return api.get<PagedResponse<T>>(`/resources/${resource}${qs}`, options)
}

/** Размер страницы при полной загрузке ресурса: серверный максимум (resources.py: le=1000). */
const PAGE_LIMIT = 1000
/** Предохранитель от бесконечного цикла при некорректном `total`: не более 50 000 записей. */
const MAX_PAGES = 50

/**
 * Загружает ВСЕ записи ресурса, дочитывая страницы через `offset`, пока не получен весь `total`.
 *
 * Зачем: сервер отдаёт не более 1000 записей за запрос, а `listResource(..., { limit: 1000 })`
 * молча обрезал бы всё сверх этого (таблицы, счётчики и проверки занятости работали бы по
 * неполным данным без какой-либо ошибки). Порядок на сервере детерминирован (created_at, id),
 * поэтому постраничное дочитывание не даёт ни дублей, ни пропусков.
 *
 * `params` — только фильтры ресурса; `limit` и `offset` выставляются здесь и из `params`
 * перекрываются. Пустая страница при неполном `total` прерывает цикл (защита от зацикливания).
 * `options.signal` отменяет всю загрузку, `options.timeoutMs` относится к каждому запросу страницы.
 *
 * @example
 *   const res = await listAllResource<Connection>('connections')
 *   const links = await listAllResource<VLANDomainDeviceLink>('vlan-domain-devices', { domain_id })
 */
export async function listAllResource<T>(
  resource: string,
  params: Record<string, string | number> = {},
  options?: RequestOptions,
): Promise<PagedResponse<T>> {
  const first = await listResource<T>(resource, { ...params, limit: PAGE_LIMIT, offset: 0 }, options)
  const items = [...first.items]
  for (let page = 1; items.length < first.total && page < MAX_PAGES; page++) {
    const next = await listResource<T>(resource, { ...params, limit: PAGE_LIMIT, offset: page * PAGE_LIMIT }, options)
    if (!next.items.length) break // сервер ничего не вернул — выходим, чтобы не зациклиться
    items.push(...next.items)
  }
  return { items, total: first.total, offset: 0, limit: items.length }
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
  /** 403: первичная настройка аутентификации — только с localhost или по токену установки (заголовок X-Setup-Token). */
  SETUP_ACCESS_DENIED: 'SETUP_ACCESS_DENIED',
  /** 403: адрес клиента не входит в список разрешённых (фильтр адресов приложения) — повтор запроса не поможет. */
  CLIENT_NOT_ALLOWED: 'CLIENT_NOT_ALLOWED',
  /** 429: слишком много неудачных попыток входа; заголовок Retry-After → ApiError.retryAfter. */
  TOO_MANY_ATTEMPTS: 'TOO_MANY_ATTEMPTS',
  INTEGRITY_ERROR: 'INTEGRITY_ERROR',
  /** 403: запрос, меняющий данные, пришёл со страницы другого origin (защита от CSRF); повтор не поможет — см. INFRA_REGISTRY_CORS_ORIGINS. */
  CROSS_ORIGIN_BLOCKED: 'CROSS_ORIGIN_BLOCKED',
  /** 422: неверный текущий пароль при смене собственного пароля. Сессию не завершает (в отличие от 401), попытка считается неудачным входом. */
  WRONG_CURRENT_PASSWORD: 'WRONG_CURRENT_PASSWORD',
} as const
