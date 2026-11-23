import { describe, it, expect, vi } from 'vitest'
import { useConsistencyReport } from '../useConsistencyReport'
import { finding, reportOf, RULES } from '../../__tests__/consistencyFixtures'
import type { ConsistencyReport } from '../../api/consistency'

const json = (body: unknown) => new Response(JSON.stringify(body))

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
