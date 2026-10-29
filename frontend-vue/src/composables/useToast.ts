// Единообразные toast-уведомления — тот же UX-контракт, что notify()/notifyError()
// в прежнем vanilla-фронтенде (до 2.60.0): не блокируют интерфейс,
// успех/инфо скрываются сами через 5с, предупреждения (warning) — через 10с (их нужно успеть
// прочитать и, как правило, что-то по ним сделать), ошибки остаются, пока их не закроют.
// Необязательное действие (кнопка в уведомлении) и своё время показа — для уведомлений, по которым надо что-то сделать.
import { reactive } from 'vue'
import { ApiError } from '../api/client'

/** Кнопка в уведомлении: по нажатию выполняется run, и уведомление закрывается. */
export interface ToastAction {
  label: string
  run: () => void
}

export interface Toast {
  id: number
  message: string
  type: 'success' | 'error' | 'info' | 'warning'
  action?: ToastAction
}

export interface NotifyOptions {
  action?: ToastAction
  /** Через сколько мс скрыть уведомление; по умолчанию — по типу. Для error без значения уведомление остаётся. */
  timeoutMs?: number
}

/** Время автоскрытия по типу; у error значения нет — ошибка остаётся до ручного закрытия. */
const AUTO_DISMISS_MS: Partial<Record<Toast['type'], number>> = { success: 5000, info: 5000, warning: 10000 }

let nextId = 1
const toasts = reactive<Toast[]>([])

function dismiss(id: number) {
  const idx = toasts.findIndex((t) => t.id === id)
  if (idx !== -1) toasts.splice(idx, 1)
}

function notify(message: string, type: Toast['type'] = 'info', options: NotifyOptions = {}) {
  const id = nextId++
  toasts.push({ id, message, type, ...(options.action ? { action: options.action } : {}) })
  const timeout = options.timeoutMs ?? AUTO_DISMISS_MS[type]
  if (timeout !== undefined) setTimeout(() => dismiss(id), timeout)
  return id
}

/** Разворачивает ApiError/Error в читаемое сообщение — тот же принцип, что errorMessage()
 * в прежнем vanilla-фронтенде (parseApiError().message), плюс явный type для toast. */
function notifyError(err: unknown) {
  const message = err instanceof ApiError || err instanceof Error ? err.message : String(err)
  return notify(message, 'error')
}

export function useToast() {
  return { toasts, notify, notifyError, dismiss }
}
