import { describe, expect, it, vi } from 'vitest'
import { createLatestRequest } from '../latestRequest'

describe('createLatestRequest', () => {
  it('единственный запрос — последний', () => {
    const latest = createLatestRequest()
    expect(latest.begin()()).toBe(true)
  })

  it('новый begin() делает предыдущий запрос устаревшим, а себя — последним', () => {
    const latest = createLatestRequest()
    const first = latest.begin()
    const second = latest.begin()
    expect(first()).toBe(false)
    expect(second()).toBe(true)
  })

  it('ответ остаётся последним, пока не начат следующий запрос', () => {
    const latest = createLatestRequest()
    const first = latest.begin()
    expect(first()).toBe(true)
    expect(first()).toBe(true)
    latest.begin()
    expect(first()).toBe(false)
  })

  it('экземпляры независимы: запрос из одного потока загрузки не отменяет другой', () => {
    const a = createLatestRequest()
    const b = createLatestRequest()
    const fromA = a.begin()
    b.begin()
    b.begin()
    expect(fromA()).toBe(true)
  })
})

describe('createLatestRequest: invalidate', () => {
  it('делает запущенные запросы устаревшими', () => {
    const latest = createLatestRequest()
    const inFlight = latest.begin()
    latest.invalidate({ loading: false })
    expect(inFlight()).toBe(false)
    expect(latest.begin()()).toBe(true) // запрос, начатый после, — по-прежнему обычный последний
  })

  it('сбрасывает loading и сообщает, шла ли загрузка', () => {
    const latest = createLatestRequest()
    const loading = { loading: true }
    expect(latest.invalidate(loading)).toBe(true)
    expect(loading.loading).toBe(false)

    expect(latest.invalidate(loading)).toBe(false) // загрузки нет — перезапускать нечего
  })
})

describe('createLatestRequest: run', () => {
  /** Запрос, ответом на который управляет тест. */
  function deferred<T>() {
    let resolve!: (value: T) => void
    let reject!: (error: unknown) => void
    const promise = new Promise<T>((res, rej) => {
      resolve = res
      reject = rej
    })
    return { promise, resolve, reject }
  }

  const fresh = () => ({ loading: false, error: 'прежняя ошибка' as string | null, data: [] as string[] })

  it('ведёт loading, очищает прежнюю ошибку и применяет ответ', async () => {
    const latest = createLatestRequest()
    const state = fresh()
    const request = deferred<string[]>()

    const done = latest.run(state, { fetch: () => request.promise, apply: (v) => void (state.data = v), errorMessage: 'сбой' })
    expect(state.loading).toBe(true)
    expect(state.error).toBeNull()

    request.resolve(['a'])
    await done
    expect(state.data).toEqual(['a'])
    expect(state.loading).toBe(false)
  })

  it('устаревший ответ не применяется и не гасит loading более позднего запроса', async () => {
    const latest = createLatestRequest()
    const state = fresh()
    const first = deferred<string[]>()
    const second = deferred<string[]>()

    const firstDone = latest.run(state, { fetch: () => first.promise, apply: (v) => void (state.data = v), errorMessage: 'сбой' })
    const secondDone = latest.run(state, { fetch: () => second.promise, apply: (v) => void (state.data = v), errorMessage: 'сбой' })

    first.resolve(['старый'])
    await firstDone
    expect(state.data).toEqual([])
    expect(state.loading).toBe(true)

    second.resolve(['новый'])
    await secondDone
    expect(state.data).toEqual(['новый'])
    expect(state.loading).toBe(false)
  })

  it('ошибка устаревшего запроса не показывается, ошибка последнего — показывается текстом исключения', async () => {
    const latest = createLatestRequest()
    const state = fresh()
    const first = deferred<string[]>()
    const second = deferred<string[]>()
    const options = (request: { promise: Promise<string[]> }) => ({ fetch: () => request.promise, apply: () => undefined, errorMessage: 'сбой' })

    const firstDone = latest.run(state, options(first))
    const secondDone = latest.run(state, options(second))

    first.reject(new Error('ошибка раннего'))
    await firstDone
    expect(state.error).toBeNull()

    second.reject(new Error('ошибка последнего'))
    await secondDone
    expect(state.error).toBe('ошибка последнего')
    expect(state.loading).toBe(false)
  })

  it('у исключения не Error берётся запасной текст; errorMessage-функция заменяет правило целиком', async () => {
    const latest = createLatestRequest()
    const state = fresh()

    await latest.run(state, { fetch: () => Promise.reject('строка'), apply: () => undefined, errorMessage: 'запасной текст' })
    expect(state.error).toBe('запасной текст')

    await latest.run(state, { fetch: () => Promise.reject(new Error('своё')), apply: () => undefined, errorMessage: (e) => `обёртка: ${(e as Error).message}` })
    expect(state.error).toBe('обёртка: своё')
  })

  it('сбой внутри apply показывается как ошибка загрузки, а loading всё равно гаснет', async () => {
    const latest = createLatestRequest()
    const state = fresh()

    await latest.run(state, {
      fetch: () => Promise.resolve([]),
      apply: () => {
        throw new Error('не смогли разобрать ответ')
      },
      errorMessage: 'сбой',
    })

    expect(state.error).toBe('не смогли разобрать ответ')
    expect(state.loading).toBe(false)
  })

  it('prepare: запрос, вытесненный за время подготовки, не стартует и loading не трогает', async () => {
    const latest = createLatestRequest()
    const state = fresh()
    const preparing = deferred<void>()
    const fetch = vi.fn(() => Promise.resolve(['данные']))

    const first = latest.run(state, { prepare: () => preparing.promise, fetch, apply: () => undefined, errorMessage: 'сбой' })
    const second = latest.run(state, { fetch: () => Promise.resolve(['второй']), apply: (v) => void (state.data = v), errorMessage: 'сбой' })
    preparing.resolve()
    await Promise.all([first, second])

    expect(fetch).not.toHaveBeenCalled()
    expect(state.data).toEqual(['второй'])
    expect(state.loading).toBe(false)
  })

  it('onStart и onError вызываются после loading/error; apply, вернувший промис, ожидается', async () => {
    const latest = createLatestRequest()
    const state = fresh()
    const calls: string[] = []

    await latest.run(state, {
      fetch: () => Promise.reject(new Error('сбой запроса')),
      apply: () => undefined,
      errorMessage: 'сбой',
      onStart: () => calls.push(`start:${state.loading}:${state.error}`),
      onError: () => calls.push(`error:${state.error}`),
    })
    expect(calls).toEqual(['start:true:null', 'error:сбой запроса'])

    let applied = false
    await latest.run(state, {
      fetch: () => Promise.resolve(1),
      apply: async () => {
        await Promise.resolve()
        applied = true
      },
      errorMessage: 'сбой',
    })
    expect(applied).toBe(true)
  })

  it('загрузка, отброшенная invalidate(), ничего не меняет: ни данные, ни loading, ни ошибку', async () => {
    const latest = createLatestRequest()
    const state = fresh()
    const request = deferred<string[]>()

    const done = latest.run(state, { fetch: () => request.promise, apply: (v) => void (state.data = v), errorMessage: 'сбой' })
    latest.invalidate(state)
    expect(state.loading).toBe(false)

    request.reject(new Error('сбой'))
    await done
    expect(state.error).toBeNull()
    expect(state.data).toEqual([])
    expect(state.loading).toBe(false)
  })
})

describe('createLatestRequest: ensure', () => {
  function makeState() {
    return { loaded: false, loading: false, error: null as string | null, data: [] as string[] }
  }
  function deferred<T>() {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((res) => (resolve = res))
    return { promise, resolve }
  }

  it('не загружено и не грузится — запускает загрузку и ждёт её', async () => {
    const latest = createLatestRequest()
    const state = makeState()
    const fetch = vi.fn(async () => ['a'])
    const load = () => latest.run(state, { fetch, apply: (v) => void ((state.data = v), (state.loaded = true)), errorMessage: 'сбой' })

    await latest.ensure(state, load)

    expect(fetch).toHaveBeenCalledOnce()
    expect(state.data).toEqual(['a'])
  })

  it('уже загружено — второй запрос не шлёт', async () => {
    const latest = createLatestRequest()
    const state = { ...makeState(), loaded: true }
    const load = vi.fn(async () => {})

    await latest.ensure(state, load)

    expect(load).not.toHaveBeenCalled()
  })

  it('идёт загрузка — ждёт её завершения, а не возвращается раньше данных, и не шлёт второй запрос', async () => {
    const latest = createLatestRequest()
    const state = makeState()
    const request = deferred<string[]>()
    const fetch = vi.fn(() => request.promise)
    const load = () => latest.run(state, { fetch, apply: (v) => void ((state.data = v), (state.loaded = true)), errorMessage: 'сбой' })

    const first = latest.ensure(state, load)
    let secondDone = false
    const second = latest.ensure(state, load).then(() => (secondDone = true))
    await Promise.resolve()
    await Promise.resolve()
    expect(secondDone).toBe(false) // раньше здесь возвращалось сразу, и вызывающий читал ещё пустые данные

    request.resolve(['a'])
    await Promise.all([first, second])

    expect(secondDone).toBe(true)
    expect(state.data).toEqual(['a'])
    expect(fetch).toHaveBeenCalledOnce()
  })
})
