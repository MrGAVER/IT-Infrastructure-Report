import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { flushPromises } from '@vue/test-utils'
import { useStackSharedVlans } from '../useStackSharedVlans'
import type { StackVlanRow } from '../../api/types'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

const vlan = (n: number): StackVlanRow => ({
  vlan_id: `v-${n}`,
  vlan_number: n,
  vlan_name: `Vlan${n}`,
  domain_id: null,
  is_shared: true,
  ip_address: `10.0.${n}.1`,
  prefix_length: 24,
  is_management: false,
  is_uniform: true,
  assigned_count: 2,
  member_count: 2,
  members: [],
})

/** Сервер: на GET /device-stacks/{id}/vlans отдаёт server[id]; calls копит id запрошенных стеков. */
function stubServer(server: Record<string, StackVlanRow[]>, calls: string[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const m = url.match(/\/device-stacks\/([^/]+)\/vlans/)
      if (!m) return jsonResponse({}, 404)
      calls.push(m[1])
      if (!(m[1] in server)) return jsonResponse({ detail: 'Стек не найден' }, 404)
      return jsonResponse({ stack_id: m[1], member_count: 2, items: server[m[1]], available: [] })
    }),
  )
}

let calls: string[]
beforeEach(() => {
  calls = []
})

describe('useStackSharedVlans', () => {
  it('ничего не запрашивает, пока нет раскрытых строк', async () => {
    stubServer({ a: [vlan(10)] }, calls)

    const vlans = useStackSharedVlans(() => [])
    await flushPromises()

    expect(calls).toEqual([])
    expect(vlans.stateOf('a')).toBeUndefined()
  })

  it('при раскрытии строки загружает общие VLAN этого стека: сначала loading, потом ready', async () => {
    stubServer({ a: [vlan(10)] }, calls)
    const needed = ref<string[]>([])
    const vlans = useStackSharedVlans(() => needed.value)

    needed.value = ['a']
    await nextTick()
    expect(vlans.stateOf('a')).toEqual({ status: 'loading' })
    await flushPromises()

    expect(vlans.stateOf('a')).toEqual({ status: 'ready', items: [vlan(10)] })
    expect(calls).toEqual(['a'])
  })

  it('уже загруженный стек повторно не запрашивается: свернул и раскрыл снова — без запроса', async () => {
    stubServer({ a: [vlan(10)], b: [] }, calls)
    const needed = ref<string[]>(['a'])
    useStackSharedVlans(() => needed.value)
    await flushPromises()

    needed.value = []
    await flushPromises()
    needed.value = ['a', 'b']
    await flushPromises()

    expect(calls).toEqual(['a', 'b'])
  })

  it('ошибка загрузки одного стека не мешает остальным; retry повторяет запрос', async () => {
    const server: Record<string, StackVlanRow[]> = { ok: [vlan(20)] }
    stubServer(server, calls)
    const vlans = useStackSharedVlans(() => ['ok', 'broken'])
    await flushPromises()

    expect(vlans.stateOf('ok')?.status).toBe('ready')
    expect(vlans.stateOf('broken')).toMatchObject({ status: 'error' })

    server.broken = []
    vlans.retry('broken')
    await flushPromises()

    expect(vlans.stateOf('broken')).toEqual({ status: 'ready', items: [] })
  })

  it('invalidate() сбрасывает кэш, и раскрытые строки загружаются заново', async () => {
    const server: Record<string, StackVlanRow[]> = { a: [vlan(10)] }
    stubServer(server, calls)
    const vlans = useStackSharedVlans(() => ['a'])
    await flushPromises()

    server.a = [vlan(10), vlan(11)]
    vlans.invalidate()
    await flushPromises()

    expect(calls).toEqual(['a', 'a'])
    expect(vlans.stateOf('a')).toMatchObject({ status: 'ready', items: [{ vlan_number: 10 }, { vlan_number: 11 }] })
  })

  it('ответ, пришедший после invalidate(), не затирает более свежую загрузку', async () => {
    // Первый запрос зависает; пока он висит, кэш сбрасывается, второй запрос отвечает сразу и даёт свежие данные.
    let releaseFirst: (r: Response) => void = () => {}
    let call = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        call += 1
        if (call === 1) return new Promise<Response>((resolve) => (releaseFirst = resolve))
        return Promise.resolve(jsonResponse({ items: [vlan(11)], available: [], member_count: 2 }))
      }),
    )
    const vlans = useStackSharedVlans(() => ['a'])
    await nextTick()

    vlans.invalidate()
    await flushPromises()
    expect(vlans.stateOf('a')).toMatchObject({ status: 'ready', items: [{ vlan_number: 11 }] })

    releaseFirst(jsonResponse({ items: [vlan(10)], available: [], member_count: 2 }))
    await flushPromises()

    expect(vlans.stateOf('a')).toMatchObject({ status: 'ready', items: [{ vlan_number: 11 }] })
  })
})
