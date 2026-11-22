// Защита формы от потерянных обновлений (оптимистичная блокировка): форма запоминает updated_at записи, который получила при чтении,
// и передаёт его серверу при сохранении. Если запись успел изменить другой пользователь, сервер отвечает 409 STALE_RECORD, и форма
// не затирает чужую правку молча, а спрашивает, что делать (useStaleRecordConflict → StaleRecordHost).
//
// Токен фиксируется в момент создания формы и дальше меняется только по ответам сервера на собственные запросы формы: если родитель
// подменит объект записи (скажем, перечитав список после чужой правки), форма не должна «забыть» устаревший снимок и пройти проверку.
// Токен обновляется из ответа сервера после каждой удачной записи: форма остаётся открытой, если не удался следующий шаг сохранения
// (порты, VLAN, ПО), и повторное нажатие «Сохранить» не должно считать конфликтом изменение, сделанное самой этой формой.
// Вложенные шаги (порты, VLAN, ПО, IP, детали ИС) сами сдвигают версию записи-родителя, а ответ основной записи этого уже не отражает —
// поэтому после сбоя такого шага форма вызывает `refresh` (см. ниже).
import { ApiError, ErrorCode, getResource, updateResource } from '../api/client'
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
  /** Запись, с которой открыта форма (редактирование); нет записи или у неё нет `updated_at` — проверки не будет. Читается один раз, при создании guard. */
  record: () => Timestamped | null | undefined
  /** Закрыть форму: вызывается после выбора «Загрузить свежие данные» (список к этому моменту уже обновлён). */
  close: () => void
}

export function useStaleRecordGuard(options: StaleRecordGuardOptions) {
  const conflict = useStaleRecordConflict()
  // Снимок версии на момент открытия формы (форма монтируется с уже готовой записью: v-if в родителе).
  let token: string | null = options.record()?.updated_at ?? null

  async function send<T extends Timestamped>(id: string, payload: Record<string, unknown>, expected: string | null): Promise<T> {
    const saved = expected ? await updateResource<T>(options.resource, id, payload, expected) : await updateResource<T>(options.resource, id, payload)
    token = saved.updated_at ?? null
    return saved
  }

  /**
   * Перечитать версию записи у сервера. Вызывается ТОЛЬКО после того, как основная запись уже сохранена этой формой, а один из вложенных
   * шагов (порты, VLAN, ПО, IP, детали ИС) не удался: к этому моменту предыдущие шаги успели сдвинуть версию, и повторное «Сохранить» с токеном
   * из ответа основной записи было бы конфликтом формы с самой собой. Вызывать после любого другого сбоя нельзя — чужая правка, которую форма
   * ещё не видела, была бы принята за свою. Ошибка чтения не маскирует исходную ошибку сохранения: токен остаётся прежним (худший случай —
   * один лишний вопрос о конфликте).
   */
  async function refresh(id: string): Promise<void> {
    try {
      token = (await getResource<Timestamped>(options.resource, id)).updated_at ?? null
    } catch {
      // токен прежний; причину сбоя пользователь уже видит в сообщении об исходной ошибке
    }
  }

  return {
    refresh,
    /**
     * Обновляет запись с проверкой токена. Возвращает сохранённую запись либо null: пользователь отказался сохранять при конфликте
     * (остался в форме или закрыл её, загрузив свежие данные) — вызывающий код просто прекращает сохранение без сообщения об ошибке.
     * Остальные ошибки (в том числе другие 409) пробрасываются как есть.
     */
    async update<T extends Timestamped>(id: string, payload: Record<string, unknown>): Promise<T | null> {
      try {
        return await send<T>(id, payload, token)
      } catch (err) {
        if (!(err instanceof ApiError) || err.code !== ErrorCode.STALE_RECORD) throw err
        const choice = await conflict.ask(err.message)
        if (choice === 'overwrite') return send<T>(id, payload, null)
        if (choice === 'reload') {
          // Форма закрывается в любом случае: сбой перечитывания списка всплывает обычной ошибкой, а не оставляет форму в неясном состоянии.
          try {
            await RELOAD_LIST[options.resource]()
          } finally {
            options.close()
          }
        }
        return null
      }
    },
    /** Запомнить токен только что созданной записи: повторное сохранение формы после сбоя последующих шагов обновляет её, а не создаёт заново. */
    remember(record: Timestamped) {
      token = record.updated_at ?? null
    },
    /**
     * Вложенные шаги сохранения (IP, порты, ПО, детали), которые форма выполняет после успешной записи основной записи `id`, друг за другом.
     * Если шаг упал, версия записи перечитывается (см. refresh), а исходная ошибка пробрасывается как есть — форма показывает её пользователю.
     */
    async afterSave(id: string, ...steps: Array<(id: string) => Promise<unknown>>): Promise<void> {
      try {
        for (const step of steps) await step(id)
      } catch (err) {
        await refresh(id)
        throw err
      }
    },
  }
}
