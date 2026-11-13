import { describe, expect, it, vi } from 'vitest'
import { assertComplete, IncompleteDataError, loadAllComplete } from '../assertComplete'

const page = (items: unknown[], total: number, truncated: boolean) => ({ items, total, offset: 0, limit: items.length, truncated })

describe('B-02: assertComplete', () => {
  it('полный ответ возвращается как есть (тот же объект)', () => {
    const res = page([{ id: 'a' }, { id: 'b' }], 2, false)

    expect(assertComplete(res, 'Установленное ПО')).toBe(res)
  })

  it('пустой, но полный список — не ошибка (total=0)', () => {
    expect(() => assertComplete(page([], 0, false), 'VLAN устройства')).not.toThrow()
  })

  it('усечённый ответ — IncompleteDataError с названием списка, числами и пояснением про блокировку сохранения', () => {
    const res = page(new Array(50_000).fill({ id: 'x' }), 51_000, true)

    let error: unknown
    try {
      assertComplete(res, 'Установленное ПО')
    } catch (e) {
      error = e
    }

    expect(error).toBeInstanceOf(IncompleteDataError)
    expect(error).toBeInstanceOf(Error)
    expect(error).toMatchObject({ name: 'IncompleteDataError', what: 'Установленное ПО', loaded: 50_000, total: 51_000 })
    const message = (error as Error).message
    expect(message).toContain('«Установленное ПО»')
    expect(message).toContain('загружен не полностью')
    expect(message).toMatch(/50\D000 из 51\D000/) // разделитель тысяч зависит от окружения (пробел/неразрывный пробел)
    expect(message).toContain('Сохранение заблокировано')
  })

  it('усечение с пустой страницей (сервер обещал больше, чем отдал) тоже ошибка, даже если записей не получено вовсе', () => {
    expect(() => assertComplete(page([], 5, true), 'Порты устройства')).toThrow(IncompleteDataError)
  })

  it('принимает и «настоящий» AllPagesResponse, и усечённый ответ вида {items,total,truncated} без остальных полей', () => {
    expect(assertComplete({ items: [1], total: 1, truncated: false }, 'x').items).toEqual([1])
    expect(() => assertComplete({ items: [1], total: 9, truncated: true }, 'x')).toThrow(IncompleteDataError)
  })
})

// ИБ-05 (ревью merge/review-r3-executors): запись, удалённая во время загрузки, делает `total` первой страницы устаревшим, и `truncated`
// ложно срабатывает. Один повтор полной загрузки перед ошибкой это снимает.
describe('ИБ-05: loadAllComplete', () => {
  it('полный ответ с первого раза возвращается как есть, повторной загрузки нет', async () => {
    const res = page([{ id: 'a' }], 1, false)
    const load = vi.fn(async () => res)

    await expect(loadAllComplete(load, 'Установленное ПО')).resolves.toBe(res)
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('первая загрузка усечена, вторая полная — ошибки нет, возвращается вторая', async () => {
    const stale = page([{ id: 'a' }], 2, true) // total=2, а запись «b» успели удалить — получена одна
    const fresh = page([{ id: 'a' }], 1, false)
    const load = vi.fn().mockResolvedValueOnce(stale).mockResolvedValueOnce(fresh)

    await expect(loadAllComplete(load, 'VLAN устройства')).resolves.toBe(fresh)
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('обе загрузки усечены — IncompleteDataError с числами из ВТОРОЙ загрузки; больше двух попыток не бывает', async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce(page([{ id: 'a' }], 2000, true))
      .mockResolvedValueOnce(page([{ id: 'a' }, { id: 'b' }], 3000, true))

    const error = await loadAllComplete(load, 'Порты устройства').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(IncompleteDataError)
    expect(error).toMatchObject({ what: 'Порты устройства', loaded: 2, total: 3000 })
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('ошибка самой загрузки пробрасывается сразу и не повторяется (повтор запроса — дело вызывающего)', async () => {
    const load = vi.fn().mockRejectedValue(new Error('сеть недоступна'))

    await expect(loadAllComplete(load, 'x')).rejects.toThrow('сеть недоступна')
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('ошибка при повторной загрузке тоже пробрасывается как есть, а не превращается в IncompleteDataError', async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce(page([], 5, true))
      .mockRejectedValueOnce(new Error('503'))

    await expect(loadAllComplete(load, 'x')).rejects.toThrow('503')
  })
})
