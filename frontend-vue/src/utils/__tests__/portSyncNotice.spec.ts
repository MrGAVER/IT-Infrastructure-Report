import { describe, it, expect, vi, afterEach } from 'vitest'
import { describePortSyncNotice, findPortSyncNotice, PORT_SYNC_NOTICE_MAX_CONNECTIONS } from '../portSyncNotice'

afterEach(() => vi.unstubAllGlobals())

const summary = (patch: Record<string, number> = {}) => ({
  connections: 0, applicable: 0, shown: 0, total_items: 0, auto: 0, blocked: 0, manual: 0, ignored: 0, none: 0, skipped: 0, ...patch,
})

function link(connectionId: string) {
  return {
    interface_id: `if-${connectionId}`, connection_id: connectionId, connection_type_id: 'ct', description: null,
    peer_interface_id: 'p', peer_interface_name: 'Gi0/2', peer_device_id: 'd2', peer_device_name: 'sw-02',
    peer_is_management: false, peer_is_data_transfer: true, peer_vlan_mode: 'trunk',
  }
}

function stubApi(links: unknown[], previewSummary = summary()) {
  const calls: Array<{ url: string; body?: Record<string, unknown> }> = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body ? JSON.parse(init.body as string) : undefined })
      if (url.endsWith('/devices/dev-1/interface-connections')) return new Response(JSON.stringify({ items: links }))
      if (url.endsWith('/port-sync/preview')) return new Response(JSON.stringify({ items: [], summary: previewSummary, plan_hash: 'h' }))
      throw new Error(`неожиданный запрос ${url}`)
    }),
  )
  return calls
}

describe('describePortSyncNotice', () => {
  it('нечего согласовывать (или есть только «исключено правилом») — уведомления нет', () => {
    expect(describePortSyncNotice({ auto: 0, manual: 0, blocked: 0 })).toBeNull()
  })

  it('автоматически и вручную: считает «нельзя применить» как «вручную»', () => {
    expect(describePortSyncNotice({ auto: 2, manual: 1, blocked: 1 })).toBe(
      'Список VLAN устройства изменён. У подключений этого устройства расхождение портов: 4 (автоматически по правилам — 2, вручную — 2).',
    )
  })

  it('нулевая часть в тексте не показывается', () => {
    expect(describePortSyncNotice({ auto: 3, manual: 0, blocked: 0 })).toContain('(автоматически по правилам — 3)')
    expect(describePortSyncNotice({ auto: 0, manual: 1, blocked: 0 })).toContain('(вручную — 1)')
  })
})

describe('findPortSyncNotice', () => {
  it('у устройства нет подключений — предпросмотр не запрашивается', async () => {
    const calls = stubApi([])

    expect(await findPortSyncNotice('dev-1')).toBeNull()
    expect(calls.some((c) => c.url.endsWith('/port-sync/preview'))).toBe(false)
  })

  it('есть что согласовать: уведомление и подключения для плана, дубли подключений схлопываются, запрошена одна запись страницы', async () => {
    const calls = stubApi([link('c-1'), link('c-1'), link('c-2')], summary({ auto: 1, manual: 1 }))

    const notice = await findPortSyncNotice('dev-1')

    expect(notice?.connectionIds).toEqual(['c-1', 'c-2'])
    expect(notice?.message).toContain('расхождение портов: 2')
    const preview = calls.find((c) => c.url.endsWith('/port-sync/preview'))
    expect(preview?.body).toMatchObject({ connection_ids: ['c-1', 'c-2'], limit: 1 })
  })

  it('расхождений нет — уведомления нет', async () => {
    stubApi([link('c-1')], summary({ skipped: 1, ignored: 0 }))

    expect(await findPortSyncNotice('dev-1')).toBeNull()
  })

  it('слишком много подключений для одного предпросмотра: общее напоминание без точного подсчёта и без запроса плана', async () => {
    const many = Array.from({ length: PORT_SYNC_NOTICE_MAX_CONNECTIONS + 1 }, (_, i) => link(`c-${i}`))
    const calls = stubApi(many)

    const notice = await findPortSyncNotice('dev-1')

    expect(notice?.connectionIds).toEqual([]) // окно плана построит план по всем расхождениям
    expect(notice?.message).toContain('Список VLAN устройства изменён')
    expect(calls.some((c) => c.url.endsWith('/port-sync/preview'))).toBe(false)
  })

  it('ошибка предпросмотра не глотается', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        url.endsWith('/interface-connections')
          ? new Response(JSON.stringify({ items: [link('c-1')] }))
          : new Response(JSON.stringify({ detail: 'сервер недоступен' }), { status: 500 }),
      ),
    )

    await expect(findPortSyncNotice('dev-1')).rejects.toBeTruthy()
  })
})
