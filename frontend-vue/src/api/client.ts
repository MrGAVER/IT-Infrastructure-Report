// Тонкая обёртка над fetch() для /api/v1.
//
// В dev-режиме запросы идут на относительный путь /api/v1/..., а Vite dev-сервер
// проксирует их на бэкенд (см. vite.config.ts, server.proxy) — то же самое
// поведение, что и в проде, где FastAPI отдаёт собранный dist/ со своего же origin
// (см. backend/app/api/system.py: GET '/' отдаёт FRONTEND_DIR/index.html).
// Благодаря этому не нужен CORS в dev и не нужно переключать base URL между режимами.
const API_BASE = '/api/v1'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    let message = text || res.statusText
    try {
      const parsed = JSON.parse(text)
      message = typeof parsed.detail === 'string' ? parsed.detail : (parsed.detail?.message ?? message)
    } catch {
      /* тело не JSON — оставляем текст как есть */
    }
    throw new ApiError(res.status, message)
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
