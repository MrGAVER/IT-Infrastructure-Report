/** Защита от перекрывающихся запросов: результат разрешено применять только последнему запущенному.
 *
 * Без неё два `reload()` подряд (после сохранения формы и по событию обновления) могли закончиться в обратном порядке: ответ на ПЕРВЫЙ
 * запрос приходил позже ответа на второй и затирал свежий список устаревшим, а `loading` сбрасывался по окончании первого, пока второй
 * ещё шёл. Один экземпляр — на один поток загрузки, на уровне модуля стора (как `latest` в auditLog.ts и connectionsDashboard.ts).
 *
 * Обычная загрузка списка целиком — через `run()`: он ведёт `loading` и `error` и отбрасывает устаревшие ответы.
 *
 * Пример:
 *   const latest = createLatestRequest()
 *   async reload() {
 *     await latest.run(this, {
 *       fetch: () => api.get<Item[]>('/items'),
 *       apply: (items) => { this.all = items; this.loaded = true },
 *       errorMessage: 'Не удалось загрузить список',
 *     })
 *   }
 *
 * Если стор сам применяет подтверждённое сервером изменение к уже показанным данным (ответ на PUT/DELETE, точечное добавление записи),
 * `load()`, начатый ДО изменения, принесёт снимок без него и откатил бы изменение. Перед применением изменения вызывается `invalidate()`:
 *   const wasLoading = latest.invalidate(this)
 *   this.rules = ...                 // применить изменение
 *   if (wasLoading) void this.load() // отброшенная загрузка заменяется новой: остальные данные не остаются устаревшими
 */

/** Поля стора, которые ведёт загрузка. */
export interface LoadState {
  loading: boolean
  error: string | null
}

export interface RunOptions<T> {
  /** Сам запрос. */
  fetch: () => Promise<T>
  /** Применяет ответ — только если запрос остался последним.
   * Может вернуть промис (например, повторную загрузку другой страницы): `run` дождётся его. */
  apply: (value: T) => void | Promise<void>
  /** Текст ошибки: строка — когда у исключения нет своего сообщения (не `Error`), функция — полностью свой выбор текста. */
  errorMessage: string | ((error: unknown) => string)
  /** Выполняется после `begin()` и до отправки запроса.
   * Если за это время начат более поздний запрос — этот не стартует (и `loading` не трогает). */
  prepare?: () => Promise<void>
  /** Дополнительные действия при старте (после `loading = true`, `error = null`). */
  onStart?: () => void
  /** Дополнительные действия при ошибке последнего запроса (после записи `error`). */
  onError?: () => void
}

export function createLatestRequest() {
  let current = 0

  /** Начинает новый запрос; возвращённая функция отвечает, остаётся ли он последним запущенным. */
  function begin(): () => boolean {
    const id = ++current
    return () => id === current
  }

  return {
    begin,

    /** Делает недействительными все запущенные запросы: их ответы, ошибки и `finally` больше ничего не меняют.
     *
     * Вызывать, когда стор применяет подтверждённое сервером изменение к уже показанным данным. Сбрасывает `state.loading` — отброшенный
     * запрос его уже не сбросит. Возвращает `true`, если загрузка шла: стору стоит запустить её заново, иначе данные, которые она
     * должна была принести, так и останутся старыми (а при первой загрузке — пустыми). */
    invalidate(state: { loading: boolean }): boolean {
      current++
      const wasLoading = state.loading
      state.loading = false
      return wasLoading
    },

    /** Загрузка с защитой «последний запрос побеждает»: ведёт `loading`/`error` стора
     * и отбрасывает ответы, пришедшие после более позднего запроса. */
    async run<T>(state: LoadState, options: RunOptions<T>): Promise<void> {
      const isLatest = begin()
      if (options.prepare) {
        await options.prepare()
        if (!isLatest()) return
      }
      state.loading = true
      state.error = null
      options.onStart?.()
      try {
        const value = await options.fetch()
        if (!isLatest()) return // устаревший ответ: finally ниже его `loading` не тронет
        await options.apply(value)
      } catch (e) {
        if (isLatest()) {
          const { errorMessage } = options
          state.error = typeof errorMessage === 'function' ? errorMessage(e) : e instanceof Error ? e.message : errorMessage
          options.onError?.()
        }
      } finally {
        if (isLatest()) state.loading = false
      }
    },
  }
}
