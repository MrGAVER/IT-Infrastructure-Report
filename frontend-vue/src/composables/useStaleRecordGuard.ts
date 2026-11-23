// Защита формы от потерянных обновлений (оптимистичная блокировка): форма запоминает updated_at записи, который получила при чтении,
// и передаёт его серверу при сохранении. Если запись успел изменить другой пользователь, сервер отвечает 409 STALE_RECORD, и форма
// не затирает чужую правку молча, а спрашивает, что делать (useStaleRecordConflict → StaleRecordHost).
//
// Токен обновляется из ответа сервера после каждой удачной записи: форма остаётся открытой, если не удался следующий шаг сохранения
// (порты, VLAN, ПО), и повторное нажатие «Сохранить» не должно считать конфликтом изменение, сделанное самой этой формой.
import { ApiError, ErrorCode, updateResource } from '../api/client'
import { useContainersStore } from '../stores/containers'
import { useDevicesStore } from '../stores/devices'
import { useInformationSystemsStore } from '../stores/informationSystems'
import { useVMsStore } from '../stores/vms'
import { useStaleRecordConflict } from './useStaleRecordConflict'

interface Timestamped {
  updated_at?: string | null
}

/** Ресурсы, формы которых защищены от потерянных обновлений, и обновление списка, из которого открывается запись. */
const RELOAD_LIST = {
  devices: () => useDevicesStore().reload(),
  vms: () => useVMsStore().reload(),
  containers: () => useContainersStore().reload(),
  'information-systems': () => useInformationSystemsStore().reload(),
} as const

export type StaleGuardedResource = keyof typeof RELOAD_LIST

export interface StaleRecordGuardOptions {
  resource: StaleGuardedResource
  /** Запись, с которой открыта форма (редактирование); нет записи или у неё нет `updated_at` — проверки не будет. */
  record: () => Timestamped | null | undefined
  /** Закрыть форму: вызывается после выбора «Загрузить свежие данные» (список к этому моменту уже обновлён). */
  close: () => void
}

export function useStaleRecordGuard(options: StaleRecordGuardOptions) {
  const conflict = useStaleRecordConflict()
  // undefined — токен ещё не прочитан: props формы читаются при первой отправке, а не при создании composable.
  let token: string | null | undefined

  function currentToken(): string | null {
    if (token === undefined) token = options.record()?.updated_at ?? null
    return token
  }

  async function send<T extends Timestamped>(id: string, payload: Record<string, unknown>, expected: string | null): Promise<T> {
    const saved = expected ? await updateResource<T>(options.resource, id, payload, expected) : await updateResource<T>(options.resource, id, payload)
    token = saved.updated_at ?? null
    return saved
  }

  return {
    /**
     * Обновляет запись с проверкой токена. Возвращает сохранённую запись либо null: пользователь отказался сохранять при конфликте
     * (остался в форме или закрыл её, загрузив свежие данные) — вызывающий код просто прекращает сохранение без сообщения об ошибке.
     * Остальные ошибки (в том числе другие 409) пробрасываются как есть.
     */
    async update<T extends Timestamped>(id: string, payload: Record<string, unknown>): Promise<T | null> {
      try {
        return await send<T>(id, payload, currentToken())
      } catch (err) {
        if (!(err instanceof ApiError) || err.code !== ErrorCode.STALE_RECORD) throw err
        const choice = await conflict.ask(err.message)
        if (choice === 'overwrite') return send<T>(id, payload, null)
        if (choice === 'reload') {
          await RELOAD_LIST[options.resource]()
          options.close()
        }
        return null
      }
    },
    /** Запомнить токен только что созданной записи: повторное сохранение формы после сбоя последующих шагов обновляет её, а не создаёт заново. */
    remember(record: Timestamped) {
      token = record.updated_at ?? null
    },
  }
}
