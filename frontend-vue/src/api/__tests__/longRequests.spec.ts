// B-11: общий таймаут запросов (30 с) не должен обрывать заведомо долгие операции — формирование отчётов и
// расчёт/применение синхронизации портов: сервер может честно работать дольше, а клиент уже показал бы «Сервер не отвечает».
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ClientErrorCode, DEFAULT_REQUEST_TIMEOUT_MS, LONG_REQUEST_TIMEOUT_MS } from '../client'
import { generateAuditLogReport, generateInventoryReport, generateStructuralAppendixReport } from '../reports'
import { generateReportFromTemplate } from '../reportTemplates'
import { applyPortSync, previewPortSync } from '../portSync'

const LONG_OPERATIONS: Array<[string, () => Promise<unknown>]> = [
  ['формирование регламентного отчёта', () => generateInventoryReport(null, [])],
  ['формирование приложения к структурной схеме', () => generateStructuralAppendixReport('ЕАИС ТО', [])],
  ['выгрузка журнала аудита', () => generateAuditLogReport(null, null)],
  ['формирование отчёта по шаблону', () => generateReportFromTemplate('t-1')],
  ['предпросмотр синхронизации портов', () => previewPortSync({})],
  ['применение синхронизации портов', () => applyPortSync({}, 'hash-1')],
]

beforeEach(() => {
  localStorage.clear()
  vi.useFakeTimers()
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(init.signal?.reason ?? new DOMException('aborted', 'AbortError')), { once: true })
        }),
    ),
  )
})

afterEach(() => {
  vi.useRealTimers()
})

describe('B-11: долгие операции ждут дольше таймаута по умолчанию', () => {
  it('долгий таймаут больше обычного', () => {
    expect(LONG_REQUEST_TIMEOUT_MS).toBeGreaterThan(DEFAULT_REQUEST_TIMEOUT_MS)
  })

  it.each(LONG_OPERATIONS)('%s: через 30 с запрос ещё ждёт, а по истечении долгого таймаута — «Сервер не отвечает»', async (_name, run) => {
    const result = run().then(
      () => 'resolved',
      (e: unknown) => e,
    )
    let settled = false
    void result.then(() => (settled = true))

    await vi.advanceTimersByTimeAsync(DEFAULT_REQUEST_TIMEOUT_MS + 1_000)
    expect(settled).toBe(false)

    await vi.advanceTimersByTimeAsync(LONG_REQUEST_TIMEOUT_MS)
    expect(await result).toMatchObject({ code: ClientErrorCode.REQUEST_TIMEOUT })
  })
})
