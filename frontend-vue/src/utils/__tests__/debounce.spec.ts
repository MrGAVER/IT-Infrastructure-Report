import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { debounce } from '../debounce'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('debounce', () => {
  it('вызывает функцию один раз после паузы, с аргументами последнего вызова', () => {
    const fn = vi.fn()
    const debounced = debounce(fn, 300)

    debounced('a')
    debounced('b')
    vi.advanceTimersByTime(299)
    expect(fn).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)

    expect(fn).toHaveBeenCalledTimes(1)
    expect(fn).toHaveBeenCalledWith('b')
  })

  it('cancel() отменяет ещё не сработавший вызов', () => {
    const fn = vi.fn()
    const debounced = debounce(fn, 300)

    debounced()
    debounced.cancel()
    vi.advanceTimersByTime(1000)

    expect(fn).not.toHaveBeenCalled()
  })

  it('после cancel() функцию можно вызывать снова', () => {
    const fn = vi.fn()
    const debounced = debounce(fn, 100)
    debounced()
    debounced.cancel()
    debounced()
    vi.advanceTimersByTime(100)
    expect(fn).toHaveBeenCalledTimes(1)
  })
})
