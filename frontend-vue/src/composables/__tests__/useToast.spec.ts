import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useToast } from '../useToast'

describe('useToast: автоскрытие по типу', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useToast().toasts.splice(0)
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('success и info скрываются через 5с', () => {
    const { toasts, notify } = useToast()
    notify('успех', 'success')
    notify('инфо', 'info')
    vi.advanceTimersByTime(4999)
    expect(toasts).toHaveLength(2)
    vi.advanceTimersByTime(2)
    expect(toasts).toHaveLength(0)
  })

  it('warning живёт дольше — скрывается через 10с, а не 5с', () => {
    const { toasts, notify } = useToast()
    notify('предупреждение', 'warning')
    vi.advanceTimersByTime(5001)
    expect(toasts.map((t) => t.type)).toEqual(['warning'])
    vi.advanceTimersByTime(5000)
    expect(toasts).toHaveLength(0)
  })

  it('error не скрывается сам — только по dismiss', () => {
    const { toasts, notify, dismiss } = useToast()
    const id = notify('ошибка', 'error')
    vi.advanceTimersByTime(600_000)
    expect(toasts).toHaveLength(1)
    dismiss(id)
    expect(toasts).toHaveLength(0)
  })
})

describe('useToast: действие и своё время показа', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useToast().toasts.splice(0)
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('действие сохраняется в уведомлении; у обычного уведомления поля action нет', () => {
    const { toasts, notify } = useToast()
    const run = () => {}
    notify('с действием', 'warning', { action: { label: 'Открыть', run } })
    notify('обычное', 'info')

    expect(toasts[0].action).toEqual({ label: 'Открыть', run })
    expect('action' in toasts[1]).toBe(false)
  })

  it('timeoutMs заменяет время по типу: warning с 30с живёт дольше стандартных 10с', () => {
    const { toasts, notify } = useToast()
    notify('долгое', 'warning', { timeoutMs: 30000 })

    vi.advanceTimersByTime(10001)
    expect(toasts).toHaveLength(1)
    vi.advanceTimersByTime(20000)
    expect(toasts).toHaveLength(0)
  })
})
