import { describe, expect, it } from 'vitest'
import { assertComplete, IncompleteDataError } from '../assertComplete'

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
