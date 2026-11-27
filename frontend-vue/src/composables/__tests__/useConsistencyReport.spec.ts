import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useConsistencyReport } from '../useConsistencyReport'
import { approvalOf, approvedFinding, finding, reportOf, RULES } from '../../__tests__/consistencyFixtures'
import { useToast } from '../useToast'
import type { ConsistencyReport } from '../../api/consistency'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })

/** Запрос, который завершается только по команде теста: так порядок ответов задаёт тест. */
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}

describe('useConsistencyReport', () => {
  it('ответ более раннего запроса не затирает более поздний', async () => {
    const first = deferred<Response>()
    const second = deferred<Response>()
    const pending = [first, second]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => (url.endsWith('/rules') ? json({ rules: RULES }) : pending.shift()!.promise)),
    )
    const state = useConsistencyReport()

    const slow = state.load()
    const fast = state.load()
    second.resolve(json(reportOf([finding({ entity_name: 'новый' })])))
    await fast
    first.resolve(json(reportOf([finding({ entity_name: 'старый' })])))
    await slow

    expect(state.report.value?.findings.map((item) => item.entity_name)).toEqual(['новый'])
    expect(state.loading.value).toBe(false)
  })

  it('без каталога правил находки остаются читаемыми: название правила — его код', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => (url.endsWith('/rules') ? new Response('{}', { status: 500 }) : json(reportOf([finding()])))),
    )
    const state = useConsistencyReport()

    await state.load()

    expect(state.errorText.value).toBe('')
    expect(state.ruleTitle('duplicate_ip')).toBe('duplicate_ip')
    expect(state.ruleOptions.value).toEqual([{ code: 'duplicate_ip', title: 'duplicate_ip' }])
  })

  it('смена фильтра возвращает на первую страницу, страница не выходит за границы', async () => {
    const many = Array.from({ length: 30 }, (_, index) => finding({ entity_name: `ip-${index}`, severity: index < 5 ? 'error' : 'warning' }))
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => json(url.endsWith('/rules') ? { rules: RULES } : (reportOf(many) satisfies ConsistencyReport))),
    )
    const state = useConsistencyReport()
    await state.load()

    state.setPage(3)
    expect(state.page.value).toBe(3)
    state.setPage(99)
    expect(state.page.value).toBe(3)
    state.setPage(-4)
    expect(state.page.value).toBe(1)

    state.setPage(3)
    state.filters.severity = 'error'
    await Promise.resolve()

    expect(state.page.value).toBe(1)
    expect(state.filtered.value).toHaveLength(5)
  })

  it('смена размера страницы оставляет на экране ту же запись, посторонний размер игнорируется', async () => {
    const many = Array.from({ length: 100 }, (_, index) => finding({ entity_name: `ip-${index}` }))
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => json(url.endsWith('/rules') ? { rules: RULES } : reportOf(many))),
    )
    const state = useConsistencyReport()
    await state.load()

    state.setPage(6) // записи 51–60
    state.setPageSize(25) // 51-я запись теперь на странице 3
    expect(state.page.value).toBe(3)
    expect(state.pageItems.value[0].entity_name).toBe('ip-50')

    state.setPageSize(7)
    expect(state.pageSize.value).toBe(25)
  })
})

describe('одобрение и отзыв', () => {
  const two = () => [finding({ entity_name: 'первая' }), finding({ entity_name: 'вторая' })]

  /** Сервер: отчёт (меняется между запросами), каталог правил и ответы на POST/DELETE одобрений. */
  function stubServer(options: { report: () => unknown; write?: (method: string, url: string, body: { fingerprints?: string[] } | null) => Response }) {
    const calls: { method: string; url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const method = init.method ?? 'GET'
        calls.push({ method, url, body: init.body ? JSON.parse(init.body as string) : null })
        if (method !== 'GET') return options.write!(method, url, init.body ? JSON.parse(init.body as string) : null)
        return json(url.endsWith('/rules') ? { rules: RULES } : options.report())
      }),
    )
    return calls
  }

  it('одобренная находка меняется на месте и уходит из списка «требуют внимания», счётчики пересчитываются', async () => {
    const findings = two()
    const answer = { created: true, approval: approvalOf({ comment: 'VRRP' }) }
    const calls = stubServer({ report: () => reportOf(findings), write: () => json(answer) })
    const state = useConsistencyReport()
    await state.load()
    expect(state.counts.value).toMatchObject({ total: 2, approved: 0 })

    await expect(state.approve(findings[0], 'VRRP')).resolves.toBe(true)

    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({ fingerprint: findings[0].fingerprint, comment: 'VRRP' })
    expect(state.counts.value).toMatchObject({ total: 1, approved: 1 })
    expect(state.filtered.value.map((item) => item.entity_name)).toEqual(['вторая'])
    expect(state.report.value?.findings[0].approval?.comment).toBe('VRRP')
    expect(state.busy.value).toBeNull()
  })

  it('отзыв возвращает находку в список; без записи об одобрении запрос не отправляется', async () => {
    const findings = [approvedFinding({ entity_name: 'одобренная' }, { id: 'appr-7' }), finding({ entity_name: 'обычная' })]
    const calls = stubServer({ report: () => reportOf(findings), write: () => new Response(null, { status: 204 }) })
    const state = useConsistencyReport()
    await state.load()

    await state.revoke(findings[1]) // не одобрена — нечего отзывать
    expect(calls.filter((call) => call.method !== 'GET')).toEqual([])

    await state.revoke(findings[0])

    expect(calls.find((call) => call.method === 'DELETE')?.url).toMatch(/approvals\/appr-7$/)
    expect(state.counts.value).toMatchObject({ total: 2, approved: 0 })
  })

  it('404 (проблема уже изменилась): одобрение не засчитывается, проверка перечитывается', async () => {
    let round = 0
    const stale = finding({ entity_name: 'устаревшая' })
    const fresh = finding({ entity_name: 'новая' })
    const calls = stubServer({
      report: () => reportOf(round++ === 0 ? [stale] : [fresh]),
      write: () => json({ detail: 'Такой проблемы уже нет или она изменилась' }, 404),
    })
    const state = useConsistencyReport()
    await state.load()

    await expect(state.approve(stale, null)).resolves.toBe(false)

    expect(state.report.value?.findings.map((item) => item.entity_name)).toEqual(['новая'])
    expect(calls.filter((call) => call.method === 'GET' && !call.url.endsWith('/rules'))).toHaveLength(2)
    expect(state.busy.value).toBeNull()
  })

  it('прочая ошибка сервера: находка остаётся неодобренной, перечитывания нет', async () => {
    const findings = two()
    const calls = stubServer({ report: () => reportOf(findings), write: () => json({ detail: 'Сбой' }, 500) })
    const state = useConsistencyReport()
    await state.load()

    await expect(state.approve(findings[0], null)).resolves.toBe(false)

    expect(state.counts.value).toMatchObject({ total: 2, approved: 0 })
    expect(calls.filter((call) => call.method === 'GET' && !call.url.endsWith('/rules'))).toHaveLength(1)
  })

  it('если одобрена последняя строка последней страницы, страница не выходит за границы', async () => {
    const many = Array.from({ length: 11 }, (_, index) => finding({ entity_name: `ip-${index}` }))
    stubServer({ report: () => reportOf(many), write: () => json({ created: true, approval: approvalOf() }) })
    const state = useConsistencyReport()
    await state.load()
    state.setPage(2) // на второй странице одна запись
    expect(state.pageItems.value).toHaveLength(1)

    await state.approve(many[10], null)
    await Promise.resolve()

    expect(state.page.value).toBe(1)
    expect(state.pageItems.value).toHaveLength(10)
  })
})

describe('пакетное одобрение', () => {
  const many = (count: number) => Array.from({ length: count }, (_, index) => finding({ entity_name: `ip-${index}` }))

  /** Ответ сервера на пакет: все отпечатки запроса одобрены, кроме перечисленных в `missing`. */
  const answer = (body: { fingerprints?: string[] } | null, missing: string[] = [], already = 0) => {
    const ok = (body?.fingerprints ?? []).filter((fingerprint) => !missing.includes(fingerprint))
    return json({
      approved: ok.length - already,
      already,
      missing,
      approvals: Object.fromEntries(ok.map((fingerprint) => [fingerprint, approvalOf({ comment: 'пакет' })])),
    })
  }

  function stubServer(items: ReturnType<typeof many>, write: (body: { fingerprints?: string[] } | null, call: number) => Response) {
    const calls: { method: string; url: string; body: { fingerprints?: string[] } | null }[] = []
    let batches = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const method = init.method ?? 'GET'
        const body = init.body ? JSON.parse(init.body as string) : null
        calls.push({ method, url, body })
        if (method === 'POST') return write(body, ++batches)
        return json(url.endsWith('/rules') ? { rules: RULES } : reportOf(items))
      }),
    )
    return calls
  }

  const messages = () => useToast().toasts.map((toast) => toast.message)

  beforeEach(() => useToast().toasts.splice(0))

  it('все проблемы уходят одним запросом, строки обновляются на месте, счётчики пересчитываются', async () => {
    const items = many(3)
    const calls = stubServer(items, (body) => answer(body))
    const state = useConsistencyReport()
    await state.load()

    await expect(state.approveMany(items, 'пакет')).resolves.toBe(true)

    const posts = calls.filter((call) => call.method === 'POST')
    expect(posts).toHaveLength(1)
    expect(posts[0].body).toEqual({ fingerprints: items.map((item) => item.fingerprint), comment: 'пакет' })
    expect(state.counts.value).toMatchObject({ total: 0, approved: 3 })
    expect(state.busy.value).toBeNull()
    expect(messages()).toEqual(['Одобрено: 3 проблемы'])
  })

  it('длинный список режется на запросы по 500 (предел сервера)', async () => {
    const items = many(501)
    const calls = stubServer(items, (body) => answer(body))
    const state = useConsistencyReport()
    await state.load()

    await state.approveMany(items, null)

    const sizes = calls.filter((call) => call.method === 'POST').map((call) => call.body?.fingerprints?.length)
    expect(sizes).toEqual([500, 1])
    expect(state.counts.value).toMatchObject({ total: 0, approved: 501 })
  })

  it('пока идёт пакет, кнопки заблокированы: busy занят, после ответа свободен', async () => {
    const items = many(2)
    stubServer(items, (body) => answer(body))
    const state = useConsistencyReport()
    await state.load()

    const running = state.approveMany(items, null)
    expect(state.busy.value).not.toBeNull()
    await running

    expect(state.busy.value).toBeNull()
  })

  it('проблемы, которых уже нет, не одобряются: об этом сказано, проверка перечитывается, остальные одобрены', async () => {
    const items = many(3)
    const calls = stubServer(items, (body) => answer(body, [items[1].fingerprint]))
    const state = useConsistencyReport()
    await state.load()
    const reports = calls.filter((call) => call.method === 'GET' && !call.url.endsWith('/rules')).length

    await expect(state.approveMany(items, null)).resolves.toBe(true)

    expect(messages()[0]).toBe('Одобрено: 2 проблемы')
    expect(messages()[1]).toBe('1 проблема уже изменились или исправлены — проверка обновлена')
    expect(calls.filter((call) => call.method === 'GET' && !call.url.endsWith('/rules'))).toHaveLength(reports + 1)
  })

  it('уже одобренные называются отдельно, а не выдаются за новые', async () => {
    const items = many(3)
    stubServer(items, (body) => answer(body, [], 1))
    const state = useConsistencyReport()
    await state.load()

    await state.approveMany(items, null)

    expect(messages()).toEqual(['Одобрено: 2 проблемы, уже были одобрены: 1'])
  })

  it('сбой на первом же запросе: ничего не одобрено, окно остаётся открытым (false), причина показана', async () => {
    const items = many(2)
    stubServer(items, () => json({ detail: 'Сбой' }, 500))
    const state = useConsistencyReport()
    await state.load()

    await expect(state.approveMany(items, null)).resolves.toBe(false)

    expect(state.counts.value).toMatchObject({ total: 2, approved: 0 })
    expect(state.busy.value).toBeNull()
    expect(messages().some((text) => text.includes('Сбой'))).toBe(true)
  })

  it('404 на первом запросе: проверка перечитывается, а не выглядит как «одобрено»', async () => {
    const items = many(2)
    const calls = stubServer(items, () => json({ detail: 'нет' }, 404))
    const state = useConsistencyReport()
    await state.load()

    await expect(state.approveMany(items, null)).resolves.toBe(false)

    expect(calls.filter((call) => call.method === 'GET' && !call.url.endsWith('/rules'))).toHaveLength(2)
  })

  it('сбой посреди списка: уже одобренное остаётся одобренным, сообщение называет «одобрено N из M»', async () => {
    const items = many(501)
    stubServer(items, (body, call) => (call === 1 ? answer(body) : json({ detail: 'Сбой на второй части' }, 500)))
    const state = useConsistencyReport()
    await state.load()

    await expect(state.approveMany(items, null)).resolves.toBe(true)

    expect(state.counts.value).toMatchObject({ total: 1, approved: 500 })
    expect(messages().some((text) => text.startsWith('Одобрено 500 из 501'))).toBe(true)
  })
})

describe('пакетный отзыв и очистка устаревших', () => {
  const approved = (count: number) => Array.from({ length: count }, (_, index) => approvedFinding({ entity_name: `ip-${index}` }, { id: `appr-${index}` }))

  function stubServer(
    items: ReturnType<typeof approved>,
    write: (method: string, url: string, body: { ids?: string[] } | null, call: number) => Response,
    stale = 0,
  ) {
    const calls: { method: string; url: string; body: { ids?: string[] } | null }[] = []
    let writes = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const method = init.method ?? 'GET'
        const body = init.body ? JSON.parse(init.body as string) : null
        calls.push({ method, url, body })
        if (method !== 'GET') return write(method, url, body, ++writes)
        return json(url.endsWith('/rules') ? { rules: RULES } : reportOf(items, { stale_approvals: stale }))
      }),
    )
    return calls
  }

  const messages = () => useToast().toasts.map((toast) => toast.message)
  beforeEach(() => useToast().toasts.splice(0))

  it('отзыв шлёт идентификаторы одобрений одним запросом; строки возвращаются в «требуют внимания»', async () => {
    const items = approved(3)
    const calls = stubServer(items, (_m, _u, body) => json({ revoked: (body?.ids ?? []).length, missing: [] }))
    const state = useConsistencyReport()
    await state.load()
    expect(state.counts.value).toMatchObject({ total: 0, approved: 3 })

    await expect(state.revokeMany(items)).resolves.toBe(true)

    const posts = calls.filter((call) => call.method === 'POST')
    expect(posts).toHaveLength(1)
    expect(posts[0].body).toEqual({ ids: ['appr-0', 'appr-1', 'appr-2'] })
    expect(state.counts.value).toMatchObject({ total: 3, approved: 0 })
    expect(state.busy.value).toBeNull()
    expect(messages()).toEqual(['Отозвано: 3 одобрения'])
  })

  it('уже отсутствующие одобрения для экрана то же, что отозванные, а в сообщении названы отдельно', async () => {
    const items = approved(2)
    stubServer(items, () => json({ revoked: 1, missing: ['appr-1'] }))
    const state = useConsistencyReport()
    await state.load()

    await state.revokeMany(items)

    expect(state.counts.value).toMatchObject({ total: 2, approved: 0 })
    expect(messages()).toEqual(['Отозвано: 1 одобрение, уже были отозваны: 1'])
  })

  it('длинный список режется на запросы по 500', async () => {
    const items = approved(501)
    const calls = stubServer(items, (_m, _u, body) => json({ revoked: (body?.ids ?? []).length, missing: [] }))
    const state = useConsistencyReport()
    await state.load()

    await state.revokeMany(items)

    expect(calls.filter((call) => call.method === 'POST').map((call) => call.body?.ids?.length)).toEqual([500, 1])
  })

  it('находки без одобрения в запрос не попадают', async () => {
    const items = [...approved(1), finding({ entity_name: 'обычная' })]
    const calls = stubServer(items, (_m, _u, body) => json({ revoked: (body?.ids ?? []).length, missing: [] }))
    const state = useConsistencyReport()
    await state.load()

    await state.revokeMany(items)

    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({ ids: ['appr-0'] })
  })

  it('сбой на первом запросе: ничего не отозвано (false), причина показана; сбой посреди списка — часть отозвана, проверка перечитана', async () => {
    const first = approved(2)
    stubServer(first, () => json({ detail: 'Сбой' }, 500))
    const state = useConsistencyReport()
    await state.load()
    await expect(state.revokeMany(first)).resolves.toBe(false)
    expect(state.counts.value).toMatchObject({ approved: 2 })
    expect(messages().some((text) => text.includes('Сбой'))).toBe(true)

    useToast().toasts.splice(0)
    const long = approved(501)
    const calls = stubServer(long, (_m, _u, body, call) =>
      call === 1 ? json({ revoked: (body?.ids ?? []).length, missing: [] }) : json({ detail: 'Сбой на второй части' }, 500),
    )
    const second = useConsistencyReport()
    await second.load()
    const reportsBefore = calls.filter((call) => call.method === 'GET' && !call.url.endsWith('/rules')).length

    await expect(second.revokeMany(long)).resolves.toBe(true)

    expect(messages().some((text) => text.startsWith('Отозвано 500 из 501'))).toBe(true)
    expect(calls.filter((call) => call.method === 'GET' && !call.url.endsWith('/rules'))).toHaveLength(reportsBefore + 1)
  })

  it('очистка устаревших: DELETE, счётчик обнуляется, сообщение называет число; сбой — false и без обнуления', async () => {
    const calls = stubServer(approved(1), () => json({ removed: 4 }), 4)
    const state = useConsistencyReport()
    await state.load()
    expect(state.report.value?.stale_approvals).toBe(4)

    await expect(state.removeStale()).resolves.toBe(true)

    expect(calls.find((call) => call.method === 'DELETE')?.url).toMatch(/approvals\/stale$/)
    expect(state.report.value?.stale_approvals).toBe(0)
    expect(messages()).toEqual(['Удалено устаревших одобрений: 4'])

    stubServer(approved(1), () => json({ detail: 'Сбой' }, 500), 4)
    const failing = useConsistencyReport()
    await failing.load()
    await expect(failing.removeStale()).resolves.toBe(false)
    expect(failing.report.value?.stale_approvals).toBe(4)
  })
})
