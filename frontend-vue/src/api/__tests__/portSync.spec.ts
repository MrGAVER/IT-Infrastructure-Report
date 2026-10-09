import { describe, it, expect, beforeEach, vi } from 'vitest'
import { previewPortSync } from '../portSync'

let bodies: unknown[]

beforeEach(() => {
  bodies = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) => {
      bodies.push(init?.body ? JSON.parse(String(init.body)) : undefined)
      return new Response(JSON.stringify({ items: [], summary: {}, plan_hash: 'h' }))
    }),
  )
})

describe('previewPortSync', () => {
  it('без страницы отправляет только условия плана — сервер вернёт первую страницу', async () => {
    await previewPortSync({ connection_ids: ['c-1'], rule_id: 'r-1' })
    expect(bodies).toEqual([{ connection_ids: ['c-1'], rule_id: 'r-1' }])
  })

  it('следующая страница: offset/limit и plan_hash первой (в формате сервера) поверх условий плана', async () => {
    await previewPortSync({ rule_id: 'r-1' }, { offset: 300, limit: 100, planHash: 'abc' })
    expect(bodies).toEqual([{ rule_id: 'r-1', offset: 300, limit: 100, plan_hash: 'abc' }])
  })

  it('пустой planHash не отправляется (сервер считал бы его ошибкой)', async () => {
    await previewPortSync({}, { offset: 0, planHash: '' })
    expect(bodies).toEqual([{ offset: 0 }])
  })
})
