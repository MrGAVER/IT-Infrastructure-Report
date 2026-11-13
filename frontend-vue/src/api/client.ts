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
// с этим токеном в заголовке X-Setup-Token (backend/app/services/auth/guards.py:require_setup_access). Нужен
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
 * 422 WRONG_CURRENT_PASSWORD (backend/app/services/auth/users.py:change_own_password, A-22), а не 401 — запись оставлена на случай старого
 * сервера. Для этих путей UNAUTHORIZED_EVENT не отправляется, иначе опечатка в форме завершила бы сессию. */
const SESSION_NEUTRAL_401_PATHS: ReadonlySet<string> = new Set(['/auth/login', '/auth/me/password'])

/**
 * Сообщает приложению, что сессия недействительна: при статусе 401 отправляет `UNAUTHORIZED_EVENT` (authStore слушает его в main.ts).
 * Для путей из SESSION_NEUTRAL_401_PATHS не отправляет: там 401 — ошибка в форме («неверный пароль»), а не конец сессии.
 *
 * Вызывают все, кто делает `fetch` напрямую и разбирает ответ сам (`request()`, скачивание файлов): иначе протухший токен при скачивании
 * показывал бы ошибку, но не возвращал бы пользователя на экран входа, как это делает любой другой запрос.
 *
 * @param path путь запроса так, как он передан в `request()` (без префикса /api/v1), либо полный адрес скачиваемого файла
 */
export function notifyUnauthorizedIfNeeded(status: number, path: string): void {
  if (status === 401 && !SESSION_NEUTRAL_401_PATHS.has(path)) {
    window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
  }
}

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
  /** Тело ответа как пришло (до MAX_ERROR_BODY_LENGTH символов) — для диагностики. Пользователю показывается `message`:
   * у не-JSON ответа (HTML страницы 502/504 от прокси) `message` — «502 Bad Gateway», а разметка остаётся только здесь. */
  body: string | null
  constructor(status: number, message: string, code: string | null = null, retryAfter: number | null = null, body: string | null = null) {
    super(message)
    this.status = status
    this.code = code
    this.retryAfter = retryAfter
    this.body = body
  }
}

/** Сколько символов тела ошибки хранить в ApiError.body: страница ошибки прокси может быть большой, а нужна она только для диагностики. */
const MAX_ERROR_BODY_LENGTH = 4096

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Строка состояния для сообщения, когда сервер не прислал читаемый текст: «502 Bad Gateway» (у HTTP/2 statusText пуст — тогда «502»). */
function statusLine(res: Response): string {
  return `${res.status} ${res.statusText}`.trim()
}

/** Сообщение и код из тела ответа с ошибкой. Контракт сервера — JSON `{detail: "текст"}` или `{detail: {message, code}}`.
 * JSON без читаемого detail (например, список ошибок валидации FastAPI) показывается текстом целиком, как и раньше — из него видно, какое поле
 * не прошло. Не-JSON тело (HTML страницы 502/504 от прокси, пустой ответ) пользователю не показывается: вместо него строка состояния. */
function parseErrorBody(text: string, res: Response): { message: string; code: string | null } {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return { message: statusLine(res), code: null }
  }
  const detail = isRecord(parsed) ? parsed.detail : undefined
  if (typeof detail === 'string') return { message: detail, code: null }
  if (isRecord(detail)) {
    return {
      message: typeof detail.message === 'string' ? detail.message : text,
      code: typeof detail.code === 'string' ? detail.code : null,
    }
  }
  return { message: text, code: null }
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

/** `ApiError` из неуспешного ответа: сообщение и код — из JSON-тела `{detail}` (parseErrorBody), задержка — из Retry-After, начало тела —
 * для диагностики. `request()` строит ошибки этим же помощником; сюда же идут вызовы, которым нужен `fetch` напрямую, потому что в
 * ответ они ждут не JSON, а файл (скачивание), и через `request()` пройти не могут. Без него пользователь видел бы сырое тело —
 * `{"detail":"Сервер занят…"}` — вместо текста сообщения. */
export async function apiErrorFromResponse(res: Response): Promise<ApiError> {
  const text = await res.text().catch(() => '')
  const { message, code } = parseErrorBody(text, res)
  return new ApiError(res.status, message, code, parseRetryAfter(res.headers.get('Retry-After')), text ? text.slice(0, MAX_ERROR_BODY_LENGTH) : null)
}

/** Ожидание ответа по умолчанию: зависший запрос не должен блокировать экран бесконечно. */
export const DEFAULT_REQUEST_TIMEOUT_MS = 30_000
/** Для заведомо долгих операций (формирование отчётов, расчёт и применение синхронизации портов). */
export const LONG_REQUEST_TIMEOUT_MS = 180_000

/** Коды ошибок, которые порождает сам клиент (в отличие от ErrorCode — кодов ответов сервера). */
export const ClientErrorCode = {
  /** Сервер не ответил за отведённое время (см. RequestOptions.timeoutMs). */
  REQUEST_TIMEOUT: 'REQUEST_TIMEOUT',
  /** Ответ 2xx пришёл не в JSON (HTML страницы прокси или «captive portal», SPA-фолбэк при неверном адресе API, обрезанное тело). */
  INVALID_RESPONSE: 'INVALID_RESPONSE',
} as const

/** Сообщение пользователю, когда успешный ответ не удалось разобрать как JSON: техническую фразу `JSON.parse` показывать нельзя. */
const INVALID_RESPONSE_MESSAGE = 'Сервер вернул ответ в неожиданном формате. Проверьте адрес сервера и настройки прокси.'

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
  // Content-Type описывает тело, поэтому ставится только когда оно есть: у GET/DELETE без тела лишний заголовок делал запрос
  // «непростым» для CORS (лишний preflight при отдельном dev-сервере).
  if (init.body !== undefined && init.body !== null && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const token = getStoredToken()
  if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)
  // Токен установки уходит только на /auth/*: остальным эндпоинтам он ни к чему.
  const setupToken = path.startsWith('/auth/') ? getStoredSetupToken() : null
  if (setupToken && !headers.has('X-Setup-Token')) headers.set('X-Setup-Token', setupToken)

  const guard = createRequestSignal(options.signal ?? init.signal, options.timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS)
  try {
    const res = await fetch(`${API_BASE}${path}`, { ...init, headers, signal: guard.signal })
    if (!res.ok) {
      const error = await apiErrorFromResponse(res)
      // Не для путей из SESSION_NEUTRAL_401_PATHS: там 401 — это ожидаемая ошибка в форме
      // ("неверный пароль" при входе, "неверный текущий пароль" при смене), а не признак того,
      // что сессия уже вошедшего пользователя недействительна (см. notifyUnauthorizedIfNeeded).
      notifyUnauthorizedIfNeeded(res.status, path)
      throw error
    }
    // 204 и пустое тело при 200 дают null: тип `T` это не отражает, поэтому вызывающий код, которому нужно тело (список, объект),
    // обязан сам учитывать null; методы, у которых тела нет (delete), его просто не читают.
    if (res.status === 204) return null as T
    // Пустое тело при 200 (прокси или сервер обрезали ответ) — не SyntaxError из res.json(), а null, как у 204. Чтение тела остаётся
    // внутри guard: таймаут по-прежнему относится к ответу целиком.
    const text = await res.text()
    if (!text) return null as T
    try {
      return JSON.parse(text) as T
    } catch {
      // B-01: не-JSON при успешном статусе — это ошибка ответа, а не «голый» SyntaxError, который не распознают проверки
      // `instanceof ApiError` / `code`. Разметка остаётся только в body (для диагностики), пользователю — понятная фраза.
      throw new ApiError(res.status, INVALID_RESPONSE_MESSAGE, ClientErrorCode.INVALID_RESPONSE, null, text.slice(0, MAX_ERROR_BODY_LENGTH))
    }
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
  post: <T>(path: string, body: unknown, options?: RequestOptions) => request<T>(path, { method: 'POST', body: JSON.stringify(body) }, options),
  put: <T>(path: string, body: unknown, options?: RequestOptions) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) }, options),
  delete: <T>(path: string, options?: RequestOptions) => request<T>(path, { method: 'DELETE' }, options),
}

/**
 * Универсальный CRUD-ресурс — см. backend/app/api/resources.py, /api/v1/resources/{resource}.
 * Важно: эндпоинт всегда отдаёт {items, total, offset, limit} (см.
 * backend/app/services/crud/generic.py:list_resource), а НЕ голый массив — легко перепутать
 * с /api/v1/devices, у которого total есть, но offset/limit нет (там нет пагинации
 * на бэкенде, см. api/types/devices.ts:DevicesResponse).
 */
export interface PagedResponse<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}

export function listResource<T>(resource: string, params?: Record<string, string | number>, options?: RequestOptions) {
  const qs = params ? '?' + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString() : ''
  return api.get<PagedResponse<T>>(`/resources/${resource}${qs}`, options)
}

/** Размер страницы при полной загрузке ресурса: серверный максимум (resources.py: le=1000). */
const PAGE_LIMIT = 1000
/** Предохранитель от бесконечного цикла при некорректном `total`: не более 50 000 записей. */
const MAX_PAGES = 50
/** Сколько страниц читается одновременно: быстрее последовательной загрузки, но без шквала запросов к однопроцессному серверу. */
const PAGE_CONCURRENCY = 4

/**
 * Убирает повторы по `id`, оставляя первое вхождение (страница с меньшим `offset`).
 *
 * Зачем: страницы читаются по `offset`, и если между запросами кто-то добавил или удалил запись, строка на стыке страниц может прийти
 * дважды (а соседняя — не прийти вовсе). Дубль в списке опаснее пропуска: форма вложенного списка сохранила бы его обратно. Строки без
 * строкового/числового `id` не трогаются: у всех ресурсов универсального CRUD `id` есть, но проверка не должна терять данные, если
 * когда-нибудь появится ресурс без него.
 */
function dedupeById<T>(items: readonly T[]): T[] {
  const seen = new Set<string | number>()
  const unique: T[] = []
  for (const row of items) {
    const id = (row as { id?: unknown } | null)?.id
    if (typeof id === 'string' || typeof id === 'number') {
      if (seen.has(id)) continue
      seen.add(id)
    }
    unique.push(row)
  }
  return unique
}

/** Ответ полной загрузки: обычная страница плюс признак того, что записей получено меньше, чем есть на сервере. */
export type AllPagesResponse<T> = PagedResponse<T> & {
  /** true — загружена только часть записей (упёрлись в MAX_PAGES или сервер отдал пустую страницу при неполном `total`).
   * Экран, которому нужна полнота, обязан показать это пользователю: иначе таблица и счётчики молча расходятся с реестром. */
  truncated: boolean
}

/**
 * Загружает ВСЕ записи ресурса, дочитывая страницы через `offset`, пока не получен весь `total`.
 *
 * Зачем: сервер отдаёт не более 1000 записей за запрос, а `listResource(..., { limit: 1000 })`
 * молча обрезал бы всё сверх этого (таблицы, счётчики и проверки занятости работали бы по
 * неполным данным без какой-либо ошибки). Порядок на сервере детерминирован (created_at, id,
 * см. services/crud/hooks.py:_default_ordering), поэтому при неизменных данных постраничное дочитывание не даёт ни дублей, ни пропусков.
 * Если данные меняются во время загрузки (другой пользователь добавил или удалил запись), строка на стыке страниц может прийти дважды:
 * повторы по `id` убираются, а потеря соседней строки видна как `truncated` (записей меньше, чем `total`).
 *
 * Первая страница читается одна (из неё известен `total`), остальные — пакетами по PAGE_CONCURRENCY страниц одновременно;
 * порядок записей в результате — по `offset`, независимо от того, какая страница пришла раньше.
 *
 * Предохранитель MAX_PAGES (50 000 записей) больше не молчит: если всё не поместилось, `truncated === true`
 * (`total` при этом настоящий, а `limit` — число загруженных записей). Пустая страница при неполном `total` тоже даёт
 * `truncated === true` и прерывает загрузку (защита от зацикливания, как и раньше).
 *
 * `params` — только фильтры ресурса; `limit` и `offset` выставляются здесь и из `params`
 * перекрываются. `options.signal` отменяет всю загрузку (запросы пакета, уже ушедшие на сервер, получают тот же signal,
 * новые пакеты не начинаются), `options.timeoutMs` относится к каждому запросу страницы.
 *
 * @example
 *   const res = await listAllResource<Connection>('connections')
 *   if (res.truncated) notify(`Показана часть данных: ${res.items.length} из ${res.total}`, 'warning')
 *   const links = await listAllResource<VLANDomainDeviceLink>('vlan-domain-devices', { domain_id })
 */
export async function listAllResource<T>(
  resource: string,
  params: Record<string, string | number> = {},
  options?: RequestOptions,
): Promise<AllPagesResponse<T>> {
  const fetchPage = (page: number) => listResource<T>(resource, { ...params, limit: PAGE_LIMIT, offset: page * PAGE_LIMIT }, options)
  const first = await fetchPage(0)
  const items = [...first.items]
  const pageCount = Math.min(Math.ceil(first.total / PAGE_LIMIT), MAX_PAGES)

  let exhausted = false // сервер вернул пустую страницу раньше, чем набрался total — дальше читать нечего
  for (let start = 1; start < pageCount && !exhausted; start += PAGE_CONCURRENCY) {
    const count = Math.min(PAGE_CONCURRENCY, pageCount - start)
    const batch = await Promise.all(Array.from({ length: count }, (_, i) => fetchPage(start + i)))
    for (const next of batch) {
      if (!next.items.length) {
        exhausted = true
        break
      }
      items.push(...next.items)
    }
  }
  // B-03: повтор на стыке страниц (запись добавили/удалили во время загрузки) убирается ДО подсчёта признака: потеря соседней строки
  // тогда видна как `items.length < total`, и экран, которому нужна полнота, не примет такой набор за целый.
  const unique = dedupeById(items)
  return { items: unique, total: first.total, offset: 0, limit: unique.length, truncated: unique.length < first.total }
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
  /** 413: тело запроса больше INFRA_REGISTRY_MAX_REQUEST_BODY_BYTES (по умолчанию 2 МБ); message сервера называет предел. Повтор того же запроса не поможет. */
  REQUEST_BODY_TOO_LARGE: 'REQUEST_BODY_TOO_LARGE',
  /** 422: неверный текущий пароль при смене собственного пароля. Сессию не завершает (в отличие от 401), попытка считается неудачным входом. */
  WRONG_CURRENT_PASSWORD: 'WRONG_CURRENT_PASSWORD',
} as const
