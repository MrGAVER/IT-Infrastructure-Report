import { describe, it, expect, vi } from 'vitest'
import { useConsistencyReport } from '../useConsistencyReport'
import { approvalOf, approvedFinding, finding, reportOf, RULES } from '../../__tests__/consistencyFixtures'
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
  function stubServer(options: { report: () => unknown; write?: (method: string, url: string) => Response }) {
    const calls: { method: string; url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit = {}) => {
        const method = init.method ?? 'GET'
        calls.push({ method, url, body: init.body ? JSON.parse(init.body as string) : null })
        if (method !== 'GET') return options.write!(method, url)
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
