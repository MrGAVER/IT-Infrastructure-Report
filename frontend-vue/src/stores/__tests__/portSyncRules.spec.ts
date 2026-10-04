import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { usePortSyncRulesStore } from '../portSyncRules'
import type { PortSyncRule } from '../../api/types'

function rule(id: string, priority: number, overrides: Partial<PortSyncRule> = {}): PortSyncRule {
  return {
    id, code: null, builtin: false, modified: false, name: `Правило ${id}`, description: '', enabled: true, priority, action: 'auto',
    target: { role: 'any', mode: 'any', vlans: 'any' }, source: { role: 'any', mode: 'any', vlans: 'any' },
    relation: { role: 'any', mode: 'any', vlans: 'any' }, apply: { role: true, mode: false, vlans: 'keep' }, ...overrides,
  }
}

interface Call { url: string; method: string; body: unknown }
let calls: Call[]

/** Эмулятор сервера правил: хранит список, отвечает как backend/app/api/port_sync.py. */
function stubServer(initial: PortSyncRule[]) {
  let rules = initial.map((r) => ({ ...r }))
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ url, method, body })
      const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
      const idMatch = url.match(/\/port-sync\/rules\/([^/]+)(\/reset)?$/)
      if (url.endsWith('/port-sync/rules') && method === 'GET') return json({ items: rules, total: rules.length })
      if (url.endsWith('/port-sync/rules') && method === 'POST') {
        const created = rule(`new-${rules.length}`, Math.max(...rules.map((r) => r.priority)) + 10, body)
        rules.push(created)
        return json(created, 201)
      }
      if (url.endsWith('/rules/reorder')) {
        rules = (body.ids as string[]).map((id, i) => ({ ...rules.find((r) => r.id === id)!, priority: (i + 1) * 10 }))
        return json({ items: rules, total: rules.length })
      }
      if (idMatch && method === 'PUT') {
        rules = rules.map((r) => (r.id === idMatch[1] ? { ...r, ...body } : r))
        return json(rules.find((r) => r.id === idMatch[1]))
      }
      if (idMatch && idMatch[2] === '/reset') {
        rules = rules.map((r) => (r.id === idMatch[1] ? { ...r, name: 'Исходное', modified: false } : r))
        return json(rules.find((r) => r.id === idMatch[1]))
      }
      if (idMatch && method === 'DELETE') {
        if (rules.find((r) => r.id === idMatch[1])?.builtin) return json({ detail: 'Стандартное правило нельзя удалить' }, 409)
        rules = rules.filter((r) => r.id !== idMatch[1])
        return new Response(null, { status: 204 })
      }
      return json({ detail: 'нет такого маршрута' }, 404)
    }),
  )
}

beforeEach(() => setActivePinia(createPinia()))

describe('usePortSyncRulesStore', () => {
  it('load() получает правила и держит их в порядке проверки, а не в порядке ответа', async () => {
    stubServer([rule('b', 20), rule('a', 10), rule('c', 30)])
    const store = usePortSyncRulesStore()

    await store.load()

    expect(store.rules.map((r) => r.id)).toEqual(['a', 'b', 'c'])
    expect(store.loaded).toBe(true)
    expect(store.loading).toBe(false)
  })

  it('ошибка загрузки попадает в error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Сервер недоступен' }), { status: 500 })))
    const store = usePortSyncRulesStore()

    await store.load()

    expect(store.error).toBe('Сервер недоступен')
    expect(store.loaded).toBe(false)
  })

  it('create() добавляет правило из ответа сервера в конец порядка', async () => {
    stubServer([rule('a', 10), rule('b', 20)])
    const store = usePortSyncRulesStore()
    await store.load()

    const created = await store.create({ name: 'Новое', action: 'auto' })

    expect(store.rules.map((r) => r.id)).toEqual(['a', 'b', created.id])
    expect(calls.at(-1)).toMatchObject({ method: 'POST', body: { name: 'Новое', action: 'auto' } })
  })

  it('update() заменяет правило ответом сервера и пересортировывает при смене приоритета', async () => {
    stubServer([rule('a', 10), rule('b', 20)])
    const store = usePortSyncRulesStore()
    await store.load()

    await store.update('b', { priority: 5, name: 'Первое' })

    expect(store.rules.map((r) => r.id)).toEqual(['b', 'a'])
    expect(store.byId('b')?.name).toBe('Первое')
  })

  it('toggle() отправляет только переключатель «включено»', async () => {
    stubServer([rule('a', 10)])
    const store = usePortSyncRulesStore()
    await store.load()

    await store.toggle('a')

    expect(calls.at(-1)).toMatchObject({ method: 'PUT', body: { enabled: false } })
    expect(store.byId('a')?.enabled).toBe(false)
    expect(store.enabledCount).toBe(0)
  })

  it('toggle() неизвестного правила — ошибка без запроса', async () => {
    stubServer([rule('a', 10)])
    const store = usePortSyncRulesStore()
    await store.load()
    const before = calls.length

    await expect(store.toggle('нет')).rejects.toThrow('не найдено')
    expect(calls).toHaveLength(before)
  })

  it('reset() подставляет сброшенное правило', async () => {
    stubServer([rule('a', 10, { builtin: true, code: 'x', modified: true, name: 'Изменённое' })])
    const store = usePortSyncRulesStore()
    await store.load()

    await store.reset('a')

    expect(store.byId('a')).toMatchObject({ name: 'Исходное', modified: false })
    expect(calls.at(-1)).toMatchObject({ method: 'POST' })
    expect(calls.at(-1)!.url).toMatch(/\/rules\/a\/reset$/)
  })

  it('remove() убирает правило из списка; отказ сервера (стандартное) оставляет его на месте', async () => {
    stubServer([rule('a', 10), rule('std', 20, { builtin: true, code: 's' })])
    const store = usePortSyncRulesStore()
    await store.load()

    await store.remove('a')
    await expect(store.remove('std')).rejects.toThrow('нельзя удалить')

    expect(store.rules.map((r) => r.id)).toEqual(['std'])
  })

  it('move() отправляет полный новый порядок и принимает приоритеты сервера', async () => {
    stubServer([rule('a', 10), rule('b', 20), rule('c', 30)])
    const store = usePortSyncRulesStore()
    await store.load()

    await store.move('c', -1)

    expect(calls.at(-1)).toMatchObject({ method: 'POST', body: { ids: ['a', 'c', 'b'] } })
    expect(store.rules.map((r) => [r.id, r.priority])).toEqual([['a', 10], ['c', 20], ['b', 30]])
  })

  it('move() на краю списка ничего не отправляет', async () => {
    stubServer([rule('a', 10), rule('b', 20)])
    const store = usePortSyncRulesStore()
    await store.load()
    const before = calls.length

    await store.move('a', -1)
    await store.move('b', 1)

    expect(calls).toHaveLength(before)
  })
})
