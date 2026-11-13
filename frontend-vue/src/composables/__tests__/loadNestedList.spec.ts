import { beforeEach, describe, expect, it } from 'vitest'
import type { AllPagesResponse } from '../../api/client'
import { loadNestedList } from '../loadNestedList'
import { useToast } from '../useToast'

const page = (items: number[], total = items.length, truncated = false): AllPagesResponse<number> => ({
  items,
  total,
  offset: 0,
  limit: items.length,
  truncated,
})
const toasts = () => useToast().toasts

beforeEach(() => {
  toasts().splice(0)
})

describe('loadNestedList', () => {
  it('список получен целиком: строки возвращаются, проблемы нет, предупреждений нет', async () => {
    const result = await loadNestedList(async () => page([1, 2, 3]), 'IP-адресов ВМ')
    expect(result).toEqual({ items: [1, 2, 3], issue: null })
    expect(toasts()).toHaveLength(0)
  })

  it('пустой, но полностью загруженный список — не проблема: это настоящее «пусто», его можно сохранять', async () => {
    const result = await loadNestedList(async () => page([]), 'IP-адресов ВМ')
    expect(result.issue).toBeNull()
    expect(result.items).toEqual([])
  })

  it('сбой загрузки: failed, исходная ошибка возвращается (не глотается и не пробрасывается), строк нет', async () => {
    const boom = new Error('сервер недоступен')
    const result = await loadNestedList(async () => Promise.reject(boom), 'IP-адресов ВМ')
    expect(result.issue).toEqual({ kind: 'failed' })
    expect(result.error).toBe(boom)
    expect(result.items).toEqual([])
  })

  it('синхронное исключение в загрузчике тоже даёт failed', async () => {
    const result = await loadNestedList(() => {
      throw new Error('до запроса')
    }, 'ПО ВМ')
    expect(result.issue).toEqual({ kind: 'failed' })
  })

  it('усечённая загрузка: partial с числами «загружено из всего», строки не отдаются, прежнее предупреждение сохранено', async () => {
    const result = await loadNestedList(async () => page([1, 2], 5, true), 'открытых портов ВМ')
    expect(result.issue).toEqual({ kind: 'partial', loaded: 2, total: 5 })
    expect(result.items).toEqual([])
    expect(toasts()).toHaveLength(1)
    expect(toasts()[0].message).toContain('открытых портов ВМ')
  })
})
