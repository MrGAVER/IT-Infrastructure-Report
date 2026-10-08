import { describe, it, expect, vi, beforeEach } from 'vitest'
import { applyVlanModeCascade, previewVlanModeCascade, type EditedDeviceState } from '../vlanModeCascade'
import { makePlan } from '../../utils/__tests__/cascadePlanFixture'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

const edited: EditedDeviceState = {
  device_id: 'dev-1',
  ports: { 'if-1': { name: 'Gi0/1', mode: 'access', group: 'new-group-1', vlan_ids: ['v10'] } },
  groups: { g1: { name: 'Серверные', mode: '', vlan_ids: [] }, 'new-group-1': { name: 'Новая', mode: 'access', vlan_ids: ['v10'] } },
}

describe('api/vlanModeCascade', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it('preview: POST с целевым режимом и состоянием формы (в теле, а не в query)', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(makePlan()))
    vi.stubGlobal('fetch', fetchMock)

    const plan = await previewVlanModeCascade('if-2', 'access', edited)

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/interfaces/if-2/vlan-mode-cascade/preview')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ mode: 'access', edited })
    expect(plan.hash).toBe('hash-1')
  })

  it('preview без устройства формы отправляет edited: null', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(makePlan()))
    vi.stubGlobal('fetch', fetchMock)

    await previewVlanModeCascade('if-2', 'trunk', null)

    expect(JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)).toEqual({ mode: 'trunk', edited: null })
  })

  it('apply: POST с hash показанного плана, тем же состоянием формы и явным confirm', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ plan: makePlan(), applied: { ports: 1, groups: 0, devices: 1 }, interfaces: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await applyVlanModeCascade('if-2', makePlan({ hash: 'abc' }), edited)

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/interfaces/if-2/vlan-mode-cascade')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ mode: 'access', edited, plan_hash: 'abc', confirm: true })
  })

  it('имя порта в пути экранируется', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(makePlan()))
    vi.stubGlobal('fetch', fetchMock)

    await previewVlanModeCascade('a/b c', 'access', null)

    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe('/api/v1/interfaces/a%2Fb%20c/vlan-mode-cascade/preview')
  })

  it('port (роль и VLAN порта-инициатора) уходит в предпросмотре и при применении; без port поля в теле нет', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ plan: makePlan(), applied: { ports: 1, groups: 0, devices: 1 }, interfaces: [], port_written: true }))
    vi.stubGlobal('fetch', fetchMock)
    const port = { role: 'management' as const, vlan_ids: ['v10'] }

    await previewVlanModeCascade('if-2', 'access', null, port)
    await applyVlanModeCascade('if-2', makePlan({ hash: 'abc' }), null, port)
    await previewVlanModeCascade('if-2', 'access', null, null)
    await applyVlanModeCascade('if-2', makePlan({ hash: 'abc' }), null)

    const bodies = fetchMock.mock.calls.map((c) => JSON.parse((c as unknown as [string, RequestInit])[1].body as string))
    expect(bodies[0]).toEqual({ mode: 'access', edited: null, port })
    expect(bodies[1]).toEqual({ mode: 'access', edited: null, port, plan_hash: 'abc', confirm: true })
    expect(bodies[2]).toEqual({ mode: 'access', edited: null })
    expect(bodies[3]).toEqual({ mode: 'access', edited: null, plan_hash: 'abc', confirm: true })
  })
})
