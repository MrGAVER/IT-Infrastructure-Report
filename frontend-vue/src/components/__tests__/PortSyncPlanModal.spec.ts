import { describe, it, expect, beforeEach, vi } from 'vitest'
import { nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PortSyncPlanModal from '../PortSyncPlanModal.vue'
import { useToast } from '../../composables/useToast'
import type { PortSyncPlan, PortSyncPlanItem, PortSyncSummary } from '../../api/types'

const port = (name: string, device: string, vlans: number[] = []) => ({
  interface_id: `if-${name}`, name, device_id: `dev-${device}`, device_name: device, role: 'data' as const, mode: 'trunk' as const, vlans,
})

function item(overrides: Partial<PortSyncPlanItem> = {}): PortSyncPlanItem {
  return {
    connection_id: 'c-1',
    outcome: 'auto',
    reason: null,
    rule: { id: 'r-1', code: 'empty_trunk_takes_neighbor_vlans', name: 'Пустой trunk получает VLAN соседа', action: 'auto' },
    target: 'source',
    source: port('Gi0/1', 'sw-1'),
    destination: port('Gi0/2', 'sw-2', [10, 20]),
    changes: { role: null, mode: null, vlans: { from: [], to: [10, 20], skipped: [] } },
    options: [],
    warnings: [],
    ...overrides,
  }
}

function plan(items: PortSyncPlanItem[], summary: Partial<PortSyncSummary> = {}, hash = 'hash-1'): PortSyncPlan {
  const auto = items.filter((i) => i.outcome === 'auto').length
  return {
    items,
    plan_hash: hash,
    summary: {
      connections: items.length, applicable: auto, shown: items.length, total_items: items.length,
      auto, blocked: 0, manual: 0, ignored: 0, none: 0, skipped: 0, ...summary,
    },
  }
}

interface Call { url: string; method: string; body: any }
let calls: Call[]
let responses: Array<() => Response>

function stub(...queue: Array<PortSyncPlan | { status: number; detail: string }>) {
  calls = []
  responses = queue.map((r) => () => ('detail' in r ? new Response(JSON.stringify({ detail: r.detail }), { status: r.status }) : new Response(JSON.stringify(r))))
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined })
      const next = responses.length > 1 ? responses.shift()! : responses[0]
      return next()
    }),
  )
}

const mountModal = (scope = {}, title?: string) => mount(PortSyncPlanModal, { props: { scope, title } })
const previewCalls = () => calls.filter((c) => c.url.endsWith('/port-sync/preview'))
const applyCalls = () => calls.filter((c) => c.url.endsWith('/port-sync/apply'))

beforeEach(() => {
  setActivePinia(createPinia())
  useToast().toasts.splice(0)
})

describe('PortSyncPlanModal.vue', () => {
  it('при открытии строит план по заданным условиям и ничего не применяет', async () => {
    stub(plan([item()]))
    const wrapper = mountModal({ connection_ids: ['c-1'], rule_id: 'r-1' })
    await nextTick() // onMounted уже включил индикатор загрузки, DOM обновляется на следующем тике
    expect(wrapper.find('[data-loading]').exists()).toBe(true)
    await flushPromises()

    expect(previewCalls()).toHaveLength(1)
    expect(previewCalls()[0].body).toEqual({ connection_ids: ['c-1'], rule_id: 'r-1' })
    expect(applyCalls()).toEqual([])
    expect(wrapper.find('[data-loading]').exists()).toBe(false)
  })

  it('показывает сводку и согласуемое изменение: порт, устройство, правило и построчные изменения', async () => {
    stub(plan([item()]))
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.find('[data-summary]').text()).toBe('проверено подключений: 1 · будет согласовано: 1')
    const auto = wrapper.find('[data-outcome="auto"]')
    expect(auto.text()).toContain('Будет согласовано')
    expect(auto.text()).toContain('Gi0/1')
    expect(auto.text()).toContain('sw-2')
    expect(auto.text()).toContain('Правило: «Пустой trunk получает VLAN соседа»')
    expect(auto.text()).toContain('Порт «Gi0/1» (sw-1):')
    expect(auto.text()).toContain('VLAN: нет → 10, 20')
  })

  it('заблокированный пункт показывает причину, ручной — варианты, предупреждения — отдельно', async () => {
    stub(
      plan(
        [
          item({ connection_id: 'c-1', outcome: 'blocked', reason: 'Порт входит в группу «Серверные», которая задаёт режим и VLAN — измените группу' }),
          item({
            connection_id: 'c-2', outcome: 'manual', target: null, changes: null,
            rule: { id: 'r-2', code: 'role_match', name: 'Роль порта совпадает с ролью соседа', action: 'manual' },
            options: [{ target: 'source', changes: { role: 'management', mode: null, vlans: null } }],
          }),
          item({ connection_id: 'c-3', warnings: ['Не назначены VLAN, которых нет у устройства порта: 30'] }),
        ],
        { blocked: 1, manual: 1, applicable: 1 },
      ),
    )
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.find('[data-outcome="blocked"] [data-reason]').text()).toContain('Серверные')
    expect(wrapper.find('[data-outcome="manual"] [data-options]').text()).toContain('«Gi0/1» (sw-1): роль → Управление активами')
    expect(wrapper.find('[data-warning]').text()).toContain('30')
    expect(wrapper.find('[data-summary]').text()).toContain('нельзя применить: 1')
    expect(wrapper.find('[data-summary]').text()).toContain('решает человек: 1')
  })

  it('«Применить» недоступна, пока не отмечено «Я проверил план»; после отметки — доступна с числом портов', async () => {
    stub(plan([item(), item({ connection_id: 'c-2' })]))
    const wrapper = mountModal()
    await flushPromises()
    const apply = wrapper.find('[data-action="apply"]')

    expect((apply.element as HTMLButtonElement).disabled).toBe(true)
    expect(apply.text()).toBe('Применить (2)')

    await wrapper.find('[data-field="confirm"]').setValue(true)

    expect((apply.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('применение отправляет те же условия, подтверждение и хеш плана; затем закрывает окно и сообщает о результате', async () => {
    stub(plan([item()], {}, 'hash-42'), plan([item()]) /* на случай повторного запроса */)
    const wrapper = mountModal({ connection_ids: ['c-1'] })
    await flushPromises()
    // apply отвечает по-своему
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined })
        return new Response(JSON.stringify({ applied: { ports: 1, connections: 1 }, connection_ids: ['c-1'], summary: plan([]).summary }))
      }),
    )

    await wrapper.find('[data-field="confirm"]').setValue(true)
    await wrapper.find('[data-action="apply"]').trigger('click')
    await flushPromises()

    expect(applyCalls()).toHaveLength(1)
    expect(applyCalls()[0].body).toEqual({ connection_ids: ['c-1'], plan_hash: 'hash-42', confirm: true })
    expect(wrapper.emitted('applied')).toHaveLength(1)
    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(useToast().toasts.at(-1)).toMatchObject({ type: 'success', message: 'Согласовано портов: 1' })
  })

  it('409 (данные изменились после предпросмотра): ошибка, снята отметка, «Обновить план» строит новый план', async () => {
    stub(plan([item()], {}, 'old'))
    const wrapper = mountModal()
    await flushPromises()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined })
        if (url.endsWith('/port-sync/apply')) return new Response(JSON.stringify({ detail: 'Данные изменились после предпросмотра — повторите операцию' }), { status: 409 })
        return new Response(JSON.stringify(plan([item()], {}, 'new')))
      }),
    )

    await wrapper.find('[data-field="confirm"]').setValue(true)
    await wrapper.find('[data-action="apply"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-error]').text()).toContain('Данные изменились после предпросмотра')
    expect(wrapper.emitted('close')).toBeUndefined()
    expect((wrapper.find('[data-field="confirm"]').element as HTMLInputElement).checked).toBe(false)

    await wrapper.find('[data-action="refresh"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-error]').exists()).toBe(false)
    expect(previewCalls()).toHaveLength(2)
    await wrapper.find('[data-field="confirm"]').setValue(true)
    await wrapper.find('[data-action="apply"]').trigger('click')
    await flushPromises()
    expect(applyCalls().at(-1)!.body.plan_hash).toBe('new')
  })

  it('прочая ошибка применения показывается без кнопки обновления плана', async () => {
    stub(plan([item()]))
    const wrapper = mountModal()
    await flushPromises()
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'Сервер недоступен' }), { status: 500 })))

    await wrapper.find('[data-field="confirm"]').setValue(true)
    await wrapper.find('[data-action="apply"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-error]').text()).toContain('Сервер недоступен')
    expect(wrapper.find('[data-action="refresh"]').exists()).toBe(false)
  })

  it('ошибка построения плана показывается, применить нельзя', async () => {
    stub({ status: 500, detail: 'Не удалось построить план' })
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.find('[data-error]').text()).toContain('Не удалось построить план')
    expect((wrapper.find('[data-action="apply"]').element as HTMLButtonElement).disabled).toBe(true)
    expect(wrapper.find('[data-field="confirm"]').exists()).toBe(false)
  })

  it('пустой план: сообщение, нет подтверждения, «Применить» недоступна', async () => {
    stub(plan([]))
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.find('[data-empty]').text()).toContain('Нет подключений')
    expect(wrapper.find('[data-field="confirm"]').exists()).toBe(false)
    expect((wrapper.find('[data-action="apply"]').element as HTMLButtonElement).disabled).toBe(true)
  })

  it('план без применимых изменений (только ручные) применить нельзя', async () => {
    stub(plan([item({ outcome: 'manual', target: null, changes: null })], { manual: 1, applicable: 0 }))
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.find('[data-field="confirm"]').exists()).toBe(false)
    expect((wrapper.find('[data-action="apply"]').element as HTMLButtonElement).disabled).toBe(true)
  })

  it('если часть пунктов не показана, говорит об этом и о том, что применяется весь план', async () => {
    stub(plan([item()], { total_items: 450, applicable: 120 }))
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.find('[data-hidden]').text()).toBe('Показаны первые 1 из 450; применяется весь план (120).')
  })

  it('заголовок можно задать снаружи', async () => {
    stub(plan([]))
    const wrapper = mountModal({}, 'Что сделает правило «X»')
    await flushPromises()

    expect(wrapper.find('h2').text()).toBe('Что сделает правило «X»')
  })

  it('правило «объединить»: изменения показываются для обоих портов, сводка называет и подключения, и порты', async () => {
    const changes = (from: number[], to: number[]) => ({ role: null, mode: null, vlans: { from, to, skipped: [] } })
    stub(plan(
      [item({
        target: 'both', changes: null,
        rule: { id: 'r-2', code: 'trunk_vlans_union', name: 'Trunk: наборы VLAN на концах линии объединяются', action: 'auto' },
        source: port('Gi0/1', 'sw-1', [10, 20]), destination: port('Gi0/2', 'sw-2', [20, 30]),
        targets: [
          { target: 'source', changes: changes([10, 20], [10, 20, 30]), blocked: null },
          { target: 'destination', changes: changes([20, 30], [10, 20, 30]), blocked: null },
        ],
      })],
      { applicable: 2 },
    ))
    const wrapper = mountModal()
    await flushPromises()

    const blocks = wrapper.findAll('[data-target]')
    expect(blocks).toHaveLength(2)
    expect(blocks[0].text()).toContain('Порт «Gi0/1» (sw-1):')
    expect(blocks[0].text()).toContain('VLAN: 10, 20 → 10, 20, 30')
    expect(blocks[1].text()).toContain('Порт «Gi0/2» (sw-2):')
    expect(blocks[1].text()).toContain('VLAN: 20, 30 → 10, 20, 30')
    expect(wrapper.find('[data-summary]').text()).toBe('проверено подключений: 1 · будет согласовано: 1 (портов: 2)')
    expect(wrapper.text()).toContain('изменить данные портов (2)')
  })

  it('порту пары, которому изменение запрещено, показывается причина, а второй порт остаётся в плане', async () => {
    const changes = { role: null, mode: null, vlans: { from: [10], to: [10, 20], skipped: [] } }
    stub(plan(
      [item({
        target: 'both', changes: null,
        targets: [
          { target: 'source', changes, blocked: 'Порт входит в группу «Магистрали», которая задаёт режим и VLAN, — измените группу' },
          { target: 'destination', changes, blocked: null },
        ],
      })],
      { applicable: 1 },
    ))
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.find('[data-outcome="auto"]').exists()).toBe(true)
    expect(wrapper.find('[data-target-blocked]').text()).toBe('Не изменится: Порт входит в группу «Магистрали», которая задаёт режим и VLAN, — измените группу')
    const blocks = wrapper.findAll('[data-target]')
    expect(blocks[0].find('.lines').exists()).toBe(false) // у запрещённого порта строк изменений нет
    expect(blocks[1].find('.lines').text()).toContain('VLAN: 10 → 10, 20')
  })

  it('заблокированное подключение с двумя портами: у обоих показаны причина и несостоявшиеся изменения', async () => {
    const changes = { role: null, mode: null, vlans: { from: [10], to: [10, 20], skipped: [20] } }
    stub(plan(
      [item({
        outcome: 'blocked', target: 'both', changes: null,
        reason: 'Порт «Gi0/1» (sw-1): нет VLAN; Порт «Gi0/2» (sw-2): нет VLAN',
        targets: [{ target: 'source', changes, blocked: 'нет VLAN' }, { target: 'destination', changes, blocked: 'нет VLAN' }],
      })],
      { applicable: 0, auto: 0, blocked: 1 },
    ))
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.findAll('[data-target]')).toHaveLength(2)
    expect(wrapper.find('[data-reason]').text()).toContain('Порт «Gi0/1» (sw-1): нет VLAN')
    expect(wrapper.findAll('[data-target] .lines')).toHaveLength(2)
    expect(wrapper.findAll('[data-target-blocked]')).toHaveLength(0) // причина общая, а не «не изменится» у применимого плана
  })

  it('подключение, у которого расхождение останется после применения, помечено в плане, а счётчик — в сводке', async () => {
    stub(plan(
      [
        item({ connection_id: 'c-1', partial: true, warnings: ['Не назначены VLAN, которых нет у устройства порта: 30'] }),
        item({ connection_id: 'c-2' }),
      ],
      { partial: 1 },
    ))
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.find('[data-summary]').text()).toContain('расхождение останется у: 1')
    const items = wrapper.findAll('[data-outcome="auto"]')
    expect(items[0].find('[data-partial]').text()).toContain('Подключение останется в «Расхождениях»')
    expect(items[1].find('[data-partial]').exists()).toBe(false)
  })

  it('план без неполных подключений не пугает: ни пометки, ни счётчика', async () => {
    stub(plan([item()]))
    const wrapper = mountModal()
    await flushPromises()

    expect(wrapper.find('[data-partial]').exists()).toBe(false)
    expect(wrapper.find('[data-summary]').text()).not.toContain('останется')
  })
})
