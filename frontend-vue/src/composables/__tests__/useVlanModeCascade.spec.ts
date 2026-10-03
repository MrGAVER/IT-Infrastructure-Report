import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useVlanModeCascade, type CascadeHost } from '../useVlanModeCascade'
import { useToast } from '../useToast'
import { useCatalogsStore } from '../../stores/catalogs'
import type { EditedDeviceState, VlanModeCascadePlan } from '../../api/vlanModeCascade'
import { groupChange, makePlan, portChange } from '../../utils/__tests__/cascadePlanFixture'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

interface Call { url: string; method: string; body?: Record<string, unknown> }

/** Роутер fetch: .../preview берёт ответы из очереди previews, применение — из apply. */
function stubApi(previews: Array<VlanModeCascadePlan | Response>, apply: () => Response = () => jsonResponse({}, 500)) {
  const calls: Call[] = []
  const queue = [...previews]
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body as string) : undefined })
      if (url.endsWith('/preview')) {
        const next = queue.length > 1 ? queue.shift()! : queue[0]
        return next instanceof Response ? next.clone() : jsonResponse(next)
      }
      return apply()
    }),
  )
  return calls
}

const applied = (plan: VlanModeCascadePlan, ports = 1) => jsonResponse({ plan, applied: { ports, groups: 0, devices: 1 }, interfaces: [{ id: 'if-2', name: 'Gi0/2', vlan_mode: plan.target_mode }] })
const complexPlan = (patch: Partial<VlanModeCascadePlan> = {}) => makePlan({ groups: [groupChange()], totals: { ...makePlan().totals, ports: 2, groups: 1 }, ...patch })

let host: CascadeHost & { finished: number; deferredCalls: VlanModeCascadePlan[] }
let edited: EditedDeviceState | null

function mountHost(deferredPorts = 0) {
  edited = null
  host = {
    finished: 0,
    deferredCalls: [],
    edited: () => edited,
    applyDeferred(plan) {
      host.deferredCalls.push(plan)
      return deferredPorts
    },
    onFinished() {
      host.finished += 1
    },
  }
  return useVlanModeCascade(host)
}

beforeEach(() => {
  setActivePinia(createPinia())
  useToast().toasts.splice(0)
  vi.unstubAllGlobals()
})

describe('useVlanModeCascade', () => {
  it('тривиальный план применяется сразу: кэш портов обновлён, хозяин уведомлён, окна подтверждения нет', async () => {
    const plan = makePlan()
    const calls = stubApi([plan], () => applied(plan))
    const catalogs = useCatalogsStore()
    catalogs.items['interfaces'] = [{ id: 'if-2', name: 'Gi0/2', vlan_mode: 'trunk' }]
    const cascade = mountHost()

    const outcome = await cascade.start('if-2', 'access', '«Gi0/2» (sw-02)')

    expect(outcome).toBe('applied')
    expect(calls.map((c) => c.method)).toEqual(['POST', 'POST'])
    expect(calls[1].body).toMatchObject({ mode: 'access', plan_hash: 'hash-1', confirm: true })
    expect(cascade.pending.value).toBeNull()
    expect(catalogs.items['interfaces'][0]).toMatchObject({ vlan_mode: 'access' })
    expect(host.finished).toBe(1)
    expect(useToast().toasts.at(-1)).toMatchObject({ type: 'success', message: 'Режим Access установлен у портов: 1' })
  })

  it('сложный план ждёт подтверждения: до confirm() записи нет; confirm() применяет, вносит deferred-часть в черновик и сообщает о форме', async () => {
    const plan = complexPlan()
    const calls = stubApi([plan], () => applied(plan, 2))
    const cascade = mountHost(3)

    expect(await cascade.start('if-2', 'access', '«Gi0/2» (sw-02)')).toBe('confirm')
    expect(cascade.pending.value).toMatchObject({ interfaceId: 'if-2', portLabel: '«Gi0/2» (sw-02)' })
    expect(calls.filter((c) => !c.url.endsWith('/preview'))).toHaveLength(0)

    await cascade.confirm()

    expect(host.deferredCalls).toEqual([plan])
    expect(cascade.pending.value).toBeNull()
    expect(host.finished).toBe(1)
    expect(useToast().toasts.at(-1)?.message).toBe('Режим Access установлен у портов: 2; в этой форме изменено портов: 3 — сохраните форму')
  })

  it('снимок формы, с которым считался план, уходит и при применении — иначе hash не сойдётся', async () => {
    const plan = complexPlan()
    const calls = stubApi([plan], () => applied(plan))
    const cascade = mountHost()
    edited = { device_id: 'dev-1', ports: {}, groups: {} }
    await cascade.start('if-2', 'access', 'x')
    edited = { device_id: 'dev-1', ports: { 'if-1': { name: 'Gi0/1', mode: 'trunk', group: null, vlan_ids: [] } }, groups: {} } // форма изменилась после предпросмотра

    await cascade.confirm()

    expect(calls[0].body?.edited).toEqual({ device_id: 'dev-1', ports: {}, groups: {} })
    expect(calls[1].body?.edited).toEqual({ device_id: 'dev-1', ports: {}, groups: {} })
  })

  it('preview(): пустой план — null, сообщение и завершение; применения нет', async () => {
    const calls = stubApi([makePlan({ empty: true, groups: [], ports: [], devices: [], totals: { ...makePlan().totals, ports: 0 } })])
    const cascade = mountHost()

    expect(await cascade.preview('if-2', 'access', 'x')).toBeNull()
    expect(await cascade.start('if-2', 'access', 'x')).toBe('unchanged')

    expect(calls.every((c) => c.url.endsWith('/preview'))).toBe(true)
    expect(host.finished).toBe(2)
    expect(useToast().toasts.at(-1)).toMatchObject({ type: 'info' })
  })

  it('409 при применении: новый план заменяет показанный, ждёт повторного подтверждения, ничего не завершается', async () => {
    const first = complexPlan({ hash: 'old' })
    const second = complexPlan({ hash: 'new', totals: { ...makePlan().totals, ports: 4, groups: 2 } })
    const calls = stubApi([first, second], () => jsonResponse({ detail: 'Данные изменились после предпросмотра' }, 409))
    const cascade = mountHost()
    await cascade.start('if-2', 'access', 'x')

    await cascade.confirm()

    expect(calls.filter((c) => c.url.endsWith('/preview'))).toHaveLength(2)
    expect(cascade.pending.value?.plan.hash).toBe('new')
    expect(host.finished).toBe(0)
    expect(cascade.applying.value).toBe(false)
    expect(useToast().toasts.at(-1)).toMatchObject({ type: 'warning' })
  })

  it('409, после которого менять уже нечего: сообщение и завершение', async () => {
    const empty = makePlan({ empty: true, groups: [], ports: [], devices: [], totals: { ...makePlan().totals, ports: 0 } })
    stubApi([complexPlan(), empty], () => jsonResponse({ detail: 'Данные изменились' }, 409))
    const cascade = mountHost()
    await cascade.start('if-2', 'access', 'x')

    await cascade.confirm()

    expect(cascade.pending.value).toBeNull()
    expect(host.finished).toBe(1)
  })

  it('прочая ошибка применения — toast, план остаётся для повторной попытки; applying сбрасывается', async () => {
    stubApi([complexPlan()], () => jsonResponse({ detail: 'Сбой записи' }, 500))
    const cascade = mountHost()
    await cascade.start('if-2', 'access', 'x')

    await cascade.confirm()

    expect(useToast().toasts.at(-1)).toMatchObject({ type: 'error' })
    expect(cascade.pending.value).not.toBeNull()
    expect(cascade.applying.value).toBe(false)
    expect(host.finished).toBe(0)
  })

  it('ошибка предпросмотра пробрасывается вызывающему, окно не открывается', async () => {
    stubApi([jsonResponse({ detail: 'Область изменения превышает 1000 портов' }, 422)])
    const cascade = mountHost()

    await expect(cascade.start('if-2', 'access', 'x')).rejects.toThrow('Область изменения превышает 1000 портов')

    expect(cascade.pending.value).toBeNull()
  })

  it('cancel() закрывает окно без записи и без уведомления хозяина', async () => {
    const calls = stubApi([complexPlan()])
    const cascade = mountHost()
    await cascade.start('if-2', 'access', 'x')

    cascade.cancel()

    expect(cascade.pending.value).toBeNull()
    expect(calls).toHaveLength(1)
    expect(host.finished).toBe(0)
  })

  it('план только с портом самой формы, применённый через commit, сообщает только о форме (на сервер ничего не записано)', async () => {
    const own = makePlan({ ports: [portChange({ deferred: true })], totals: { ...makePlan().totals, deferred_ports: 1, immediate_ports: 0, immediate_devices: 0 } })
    stubApi([own], () => applied(own, 0))
    const cascade = mountHost(1)

    await cascade.start('if-2', 'access', 'x')

    expect(useToast().toasts.at(-1)?.message).toBe('Режим Access: в этой форме изменено портов: 1 — сохраните форму')
  })
})
