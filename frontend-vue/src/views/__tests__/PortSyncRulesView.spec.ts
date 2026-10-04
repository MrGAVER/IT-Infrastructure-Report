import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PortSyncRulesView from '../PortSyncRulesView.vue'
import { useToast } from '../../composables/useToast'
import type { PortSyncRule } from '../../api/types'

function rule(id: string, priority: number, overrides: Partial<PortSyncRule> = {}): PortSyncRule {
  return {
    id, code: null, builtin: false, modified: false, name: `Правило ${id}`, description: '', enabled: true, priority, action: 'auto',
    target: { role: 'any', mode: 'any', vlans: 'any' }, source: { role: 'any', mode: 'any', vlans: 'any' },
    relation: { role: 'any', mode: 'any', vlans: 'any' }, apply: { role: true, mode: false, vlans: 'keep' }, ...overrides,
  }
}

const standard = (id: string, priority: number, overrides: Partial<PortSyncRule> = {}) => rule(id, priority, { builtin: true, code: `code-${id}`, ...overrides })

interface Call { url: string; method: string; body: any }
let calls: Call[]
let serverRules: PortSyncRule[]

function stubServer(initial: PortSyncRule[], opts: { failLoad?: boolean; failDelete?: boolean } = {}) {
  serverRules = initial.map((r) => ({ ...r }))
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ url, method, body })
      const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
      if (url.endsWith('/port-sync/rules') && method === 'GET') {
        return opts.failLoad ? json({ detail: 'Сервер недоступен' }, 500) : json({ items: serverRules, total: serverRules.length })
      }
      if (url.endsWith('/port-sync/rules') && method === 'POST') {
        const created = rule(`new-${serverRules.length}`, Math.max(0, ...serverRules.map((r) => r.priority)) + 10, body)
        serverRules.push(created)
        return json(created, 201)
      }
      if (url.endsWith('/port-sync/preview')) {
        return json({ items: [], summary: { connections: 0, applicable: 0, shown: 0, total_items: 0, auto: 0, blocked: 0, manual: 0, ignored: 0, none: 0, skipped: 0 }, plan_hash: 'h' })
      }
      if (url.endsWith('/rules/reorder')) {
        serverRules = (body.ids as string[]).map((id, i) => ({ ...serverRules.find((r) => r.id === id)!, priority: (i + 1) * 10 }))
        return json({ items: serverRules, total: serverRules.length })
      }
      const match = url.match(/\/port-sync\/rules\/([^/]+)(\/reset)?$/)
      if (match && match[2]) {
        serverRules = serverRules.map((r) => (r.id === match[1] ? { ...r, modified: false, name: 'Исходное название' } : r))
        return json(serverRules.find((r) => r.id === match[1]))
      }
      if (match && method === 'PUT') {
        serverRules = serverRules.map((r) => (r.id === match[1] ? { ...r, ...body } : r))
        return json(serverRules.find((r) => r.id === match[1]))
      }
      if (match && method === 'DELETE') {
        if (opts.failDelete) return json({ detail: 'Стандартное правило нельзя удалить' }, 409)
        serverRules = serverRules.filter((r) => r.id !== match[1])
        return new Response(null, { status: 204 })
      }
      return json({ detail: 'нет маршрута' }, 404)
    }),
  )
}

async function mountView() {
  const wrapper = mount(PortSyncRulesView)
  await flushPromises()
  return wrapper
}

const names = (w: Awaited<ReturnType<typeof mountView>>) => w.findAll('.rule .name').map((n) => n.text())
const ruleEl = (w: Awaited<ReturnType<typeof mountView>>, id: string) => w.find(`[data-rule="${id}"]`)
const toasts = () => useToast().toasts

beforeEach(() => {
  setActivePinia(createPinia())
  toasts().splice(0)
  vi.stubGlobal('confirm', vi.fn(() => true))
})

describe('PortSyncRulesView.vue', () => {
  it('показывает правила в порядке проверки с номером, пометками и описанием словами', async () => {
    stubServer([
      rule('b', 20, { enabled: false }),
      standard('a', 10, { name: 'Пустой trunk', target: { role: 'any', mode: 'trunk', vlans: 'none' }, modified: true }),
      rule('c', 30, { action: 'manual' }),
    ])
    const wrapper = await mountView()

    expect(names(wrapper)).toEqual(['Пустой trunk', 'Правило b', 'Правило c'])
    expect(wrapper.findAll('.rule .order').map((o) => o.text())).toEqual(['1', '2', '3'])
    const first = ruleEl(wrapper, 'code-a')
    expect(first.find('[data-tag="builtin"]').exists()).toBe(true)
    expect(first.find('[data-tag="modified"]').text()).toBe('Изменено')
    expect(first.find('[data-sentence]').text()).toContain('порт: режим trunk, VLAN не назначены совсем')
    expect(ruleEl(wrapper, 'b').find('[data-tag="off"]').exists()).toBe(true)
    expect(ruleEl(wrapper, 'b').classes()).toContain('off')
    expect(ruleEl(wrapper, 'c').find('[data-tag="action"]').text()).toBe('Решает человек')
  })

  it('счётчики: правил, включено, стандартных, стандартных изменено', async () => {
    stubServer([standard('a', 10, { modified: true }), standard('b', 20), rule('c', 30, { enabled: false })])
    const wrapper = await mountView()

    expect(wrapper.findAll('.stat-card .num').map((n) => n.text())).toEqual(['3', '2', '2', '1'])
  })

  it('ошибка загрузки показывается баннером', async () => {
    stubServer([], { failLoad: true })
    const wrapper = await mountView()

    expect(wrapper.find('.error-banner').text()).toContain('Сервер недоступен')
  })

  it('пустой список — сообщение', async () => {
    stubServer([])
    const wrapper = await mountView()

    expect(wrapper.find('[data-empty]').text()).toBe('Правил нет.')
  })

  it('переключатель включает и отключает правило, отправляя только «включено»', async () => {
    stubServer([rule('a', 10)])
    const wrapper = await mountView()

    await ruleEl(wrapper, 'a').find('[data-action="toggle"]').setValue(false)
    await flushPromises()

    expect(calls.at(-1)).toMatchObject({ method: 'PUT', body: { enabled: false } })
    expect(ruleEl(wrapper, 'a').find('[data-tag="off"]').exists()).toBe(true)
  })

  it('«Выше» и «Ниже» меняют порядок, на краях недоступны', async () => {
    stubServer([rule('a', 10), rule('b', 20), rule('c', 30)])
    const wrapper = await mountView()

    expect((ruleEl(wrapper, 'a').find('[data-action="up"]').element as HTMLButtonElement).disabled).toBe(true)
    expect((ruleEl(wrapper, 'c').find('[data-action="down"]').element as HTMLButtonElement).disabled).toBe(true)

    await ruleEl(wrapper, 'c').find('[data-action="up"]').trigger('click')
    await flushPromises()

    expect(calls.find((c) => c.url.endsWith('/rules/reorder'))!.body).toEqual({ ids: ['a', 'c', 'b'] })
    expect(names(wrapper)).toEqual(['Правило a', 'Правило c', 'Правило b'])
  })

  it('«Новое правило» открывает форму, сохранение добавляет правило в список и показывает уведомление', async () => {
    stubServer([rule('a', 10)])
    const wrapper = await mountView()

    await wrapper.find('[data-action="create"]').trigger('click')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    await wrapper.find('[data-field="name"]').setValue('Моё правило')
    await wrapper.find('[data-field="apply-role"]').setValue(true)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(calls.find((c) => c.method === 'POST' && c.url.endsWith('/port-sync/rules'))!.body.name).toBe('Моё правило')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(names(wrapper)).toEqual(['Правило a', 'Моё правило'])
    expect(toasts().at(-1)).toMatchObject({ type: 'success', message: expect.stringContaining('создано') })
  })

  it('«Изменить» открывает форму с данными правила (и для стандартного)', async () => {
    stubServer([standard('a', 10, { name: 'Стандартное' })])
    const wrapper = await mountView()

    await ruleEl(wrapper, 'code-a').find('[data-action="edit"]').trigger('click')

    expect((wrapper.find('[data-field="name"]').element as HTMLInputElement).value).toBe('Стандартное')
    expect(wrapper.find('[data-note="builtin"]').exists()).toBe(true)

    await wrapper.find('[data-field="name"]').setValue('Переименовано')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(calls.find((c) => c.method === 'PUT' && c.url.endsWith('/rules/a'))!.body.name).toBe('Переименовано')
    expect(names(wrapper)).toEqual(['Переименовано'])
    expect(toasts().at(-1)!.message).toContain('сохранено')
  })

  it('«Сбросить» есть только у изменённых стандартных правил и спрашивает подтверждение', async () => {
    stubServer([standard('a', 10, { modified: true }), standard('b', 20), rule('c', 30, { modified: false })])
    const wrapper = await mountView()

    expect(ruleEl(wrapper, 'code-a').find('[data-action="reset"]').exists()).toBe(true)
    expect(ruleEl(wrapper, 'code-b').find('[data-action="reset"]').exists()).toBe(false)
    expect(ruleEl(wrapper, 'c').find('[data-action="reset"]').exists()).toBe(false)

    await ruleEl(wrapper, 'code-a').find('[data-action="reset"]').trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalledTimes(1)
    expect(calls.some((c) => c.url.endsWith('/rules/a/reset'))).toBe(true)
    expect(ruleEl(wrapper, 'code-a').find('.name').text()).toBe('Исходное название')
    expect(ruleEl(wrapper, 'code-a').find('[data-action="reset"]').exists()).toBe(false)
  })

  it('отказ в подтверждении сброса ничего не отправляет', async () => {
    stubServer([standard('a', 10, { modified: true })])
    vi.stubGlobal('confirm', vi.fn(() => false))
    const wrapper = await mountView()
    const before = calls.length

    await ruleEl(wrapper, 'code-a').find('[data-action="reset"]').trigger('click')
    await flushPromises()

    expect(calls).toHaveLength(before)
  })

  it('«Удалить» есть только у пользовательских правил; удаление убирает правило после подтверждения', async () => {
    stubServer([standard('a', 10), rule('b', 20)])
    const wrapper = await mountView()

    expect(ruleEl(wrapper, 'code-a').find('[data-action="delete"]').exists()).toBe(false) // стандартное — только отключить
    await ruleEl(wrapper, 'b').find('[data-action="delete"]').trigger('click')
    await flushPromises()

    expect(calls.some((c) => c.method === 'DELETE' && c.url.endsWith('/rules/b'))).toBe(true)
    expect(names(wrapper)).toEqual(['Правило a'])
  })

  it('ошибка операции показывается тостом, правило остаётся', async () => {
    stubServer([rule('a', 10)], { failDelete: true })
    const wrapper = await mountView()

    await ruleEl(wrapper, 'a').find('[data-action="delete"]').trigger('click')
    await flushPromises()

    expect(toasts().at(-1)).toMatchObject({ type: 'error', message: expect.stringContaining('нельзя удалить') })
    expect(names(wrapper)).toEqual(['Правило a'])
  })

  it('«Что сделает» открывает план только по этому правилу', async () => {
    stubServer([rule('a', 10), rule('b', 20)])
    const wrapper = await mountView()

    await ruleEl(wrapper, 'b').find('[data-action="preview"]').trigger('click')
    await flushPromises()

    const preview = calls.find((c) => c.url.endsWith('/port-sync/preview'))!
    expect(preview.body).toEqual({ rule_id: 'b' })
    expect(wrapper.find('h2').text()).toBe('Что сделает правило «Правило b»')
  })

  it('«Согласовать по правилам…» открывает план по всем подключениям с расхождением', async () => {
    stubServer([rule('a', 10)])
    const wrapper = await mountView()

    await wrapper.find('[data-action="plan-all"]').trigger('click')
    await flushPromises()

    expect(calls.find((c) => c.url.endsWith('/port-sync/preview'))!.body).toEqual({})
  })
})
