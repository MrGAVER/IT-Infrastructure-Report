// Единообразные toast-уведомления — тот же UX-контракт, что notify()/notifyError()
// в текущем vanilla-фронтенде (frontend/static/core.js): не блокируют интерфейс,
// успех/инфо скрываются сами через 5с, ошибки остаются, пока их не закроют.
import { reactive } from 'vue'
import { ApiError } from '../api/client'

export interface Toast {
  id: number
  message: string
  type: 'success' | 'error' | 'info'
}

let nextId = 1
const toasts = reactive<Toast[]>([])

function dismiss(id: number) {
  const idx = toasts.findIndex((t) => t.id === id)
  if (idx !== -1) toasts.splice(idx, 1)
}

function notify(message: string, type: Toast['type'] = 'info') {
  const id = nextId++
  toasts.push({ id, message, type })
  if (type !== 'error') {
    setTimeout(() => dismiss(id), 5000)
  }
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
