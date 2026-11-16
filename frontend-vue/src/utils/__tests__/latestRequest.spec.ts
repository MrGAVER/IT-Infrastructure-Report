import { describe, expect, it } from 'vitest'
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
