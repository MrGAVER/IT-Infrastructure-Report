// R2-01 (ревью merge/review-f06-stage2-f05-executors): усечённая полная загрузка не должна быть тихой.
import { describe, it, expect, beforeEach } from 'vitest'
import { useToast } from '../useToast'
import { warnIfTruncated } from '../useTruncationWarning'

const page = (loaded: number, total: number, truncated: boolean | undefined) => ({
  items: Array.from({ length: loaded }, (_, i) => ({ id: i })),
  total,
  truncated: truncated as boolean,
})

beforeEach(() => {
  useToast().toasts.splice(0)
})

describe('warnIfTruncated', () => {
  it('усечённая загрузка: предупреждение с числом загруженных и общим числом записей, возвращает true', () => {
    const shown = warnIfTruncated(page(50_000, 51_000, true), 'подключений')

    expect(shown).toBe(true)
    const [toast, ...rest] = useToast().toasts
    expect(rest).toHaveLength(0)
    expect(toast.type).toBe('warning')
    expect(toast.message).toContain('подключений')
    expect(toast.message).toContain((50_000).toLocaleString('ru-RU'))
    expect(toast.message).toContain((51_000).toLocaleString('ru-RU'))
  })

  it('полная загрузка: тишина, возвращает false', () => {
    expect(warnIfTruncated(page(2500, 2500, false), 'подключений')).toBe(false)
    expect(useToast().toasts).toHaveLength(0)
  })

  it('ответ без поля truncated (старый мок или чужой формат) предупреждением не считается', () => {
    expect(warnIfTruncated(page(10, 10, undefined), 'подключений')).toBe(false)
    expect(useToast().toasts).toHaveLength(0)
  })
})
