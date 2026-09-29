// Единообразные toast-уведомления — тот же UX-контракт, что notify()/notifyError()
// в текущем vanilla-фронтенде (frontend/static/core.js): не блокируют интерфейс,
// успех/инфо скрываются сами через 5с, предупреждения (warning) — через 10с (их нужно успеть
// прочитать и, как правило, что-то по ним сделать), ошибки остаются, пока их не закроют.
import { reactive } from 'vue'
import { ApiError } from '../api/client'

export interface Toast {
  id: number
  message: string
  type: 'success' | 'error' | 'info' | 'warning'
}

/** Время автоскрытия по типу; у error значения нет — ошибка остаётся до ручного закрытия. */
const AUTO_DISMISS_MS: Partial<Record<Toast['type'], number>> = { success: 5000, info: 5000, warning: 10000 }

let nextId = 1
const toasts = reactive<Toast[]>([])

function dismiss(id: number) {
  const idx = toasts.findIndex((t) => t.id === id)
  if (idx !== -1) toasts.splice(idx, 1)
}

function notify(message: string, type: Toast['type'] = 'info') {
  const id = nextId++
  toasts.push({ id, message, type })
  const timeout = AUTO_DISMISS_MS[type]
  if (timeout !== undefined) setTimeout(() => dismiss(id), timeout)
  return id
}

/** Разворачивает ApiError/Error в читаемое сообщение — тот же принцип, что errorMessage()
 * в core.js (parseApiError().message), плюс явный type для toast. */
function notifyError(err: unknown) {
  const message = err instanceof ApiError || err instanceof Error ? err.message : String(err)
  return notify(message, 'error')
}

export function useToast() {
  return { toasts, notify, notifyError, dismiss }
}
