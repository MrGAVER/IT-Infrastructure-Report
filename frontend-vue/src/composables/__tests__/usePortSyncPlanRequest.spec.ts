import { describe, it, expect, beforeEach } from 'vitest'
import { usePortSyncPlanRequest } from '../usePortSyncPlanRequest'

describe('usePortSyncPlanRequest', () => {
  beforeEach(() => usePortSyncPlanRequest().close())

  it('open запоминает область и заголовок, close сбрасывает; состояние общее для всех вызовов', () => {
    usePortSyncPlanRequest().open({ connection_ids: ['c-1'] }, 'Свой заголовок')

    expect(usePortSyncPlanRequest().request.value).toEqual({ scope: { connection_ids: ['c-1'] }, title: 'Свой заголовок' })
    usePortSyncPlanRequest().close()
    expect(usePortSyncPlanRequest().request.value).toBeNull()
  })

  it('без аргументов — план по всем расхождениям и заголовок по умолчанию', () => {
    usePortSyncPlanRequest().open()

    expect(usePortSyncPlanRequest().request.value).toEqual({ scope: {}, title: 'Согласование портов по правилам' })
  })
})
