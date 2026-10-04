import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PortSyncRuleFormModal from '../PortSyncRuleFormModal.vue'
import { usePortSyncRulesStore } from '../../stores/portSyncRules'
import type { PortSyncRule } from '../../api/types'

function rule(overrides: Partial<PortSyncRule> = {}): PortSyncRule {
  return {
    id: 'r-1', code: 'empty_trunk_takes_neighbor_vlans', builtin: true, modified: false, name: 'Пустой trunk получает VLAN соседа',
    description: 'Описание', enabled: true, priority: 10, action: 'auto',
    target: { role: 'any', mode: 'trunk', vlans: 'none' }, source: { role: 'any', mode: 'trunk', vlans: 'set' },
    relation: { role: 'any', mode: 'any', vlans: 'any' }, apply: { role: false, mode: true, vlans: 'copy' }, ...overrides,
  }
}

interface Call { url: string; method: string; body: any }
let calls: Call[]

function stubApi(respond: (call: Call) => Response | undefined = () => undefined) {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const call = { url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined }
      calls.push(call)
      return respond(call) ?? new Response(JSON.stringify({ ...rule(), ...call.body, id: 'saved' }), { status: call.method === 'POST' ? 201 : 200 })
    }),
  )
}

const mountForm = (r: PortSyncRule | null) => mount(PortSyncRuleFormModal, { props: { rule: r } })
const field = (w: ReturnType<typeof mountForm>, name: string) => w.find(`[data-field="${name}"]`)

beforeEach(() => {
  setActivePinia(createPinia())
  stubApi()
})

describe('PortSyncRuleFormModal.vue — создание', () => {
  it('новое правило: пустая форма, действие «Автоматически», проверка названия до отправки', async () => {
    const wrapper = mountForm(null)

    expect(wrapper.find('h2').text()).toBe('Новое правило согласования')
    expect((field(wrapper, 'name').element as HTMLInputElement).value).toBe('')
    expect((field(wrapper, 'action').element as HTMLSelectElement).value).toBe('auto')
    expect(wrapper.find('[data-note="builtin"]').exists()).toBe(false)

    await wrapper.find('form').trigger('submit')

    expect(wrapper.find('[role="alert"]').text()).toContain('Укажите название')
    expect(calls).toEqual([])
  })

  it('автоматическое правило без изменений не отправляется: нужно выбрать роль, режим или VLAN', async () => {
    const wrapper = mountForm(null)
    await field(wrapper, 'name').setValue('Пустое')

    await wrapper.find('form').trigger('submit')

    expect(wrapper.find('[role="alert"]').text()).toContain('должно что-то менять')
    expect(calls).toEqual([])
  })

  it('собирает правило «пустой trunk получает VLAN соседа» и отправляет без priority', async () => {
    const wrapper = mountForm(null)
    await field(wrapper, 'name').setValue('  Мой пустой trunk ')
    await field(wrapper, 'target-mode').setValue('trunk')
    await field(wrapper, 'target-vlans').setValue('none')
    await field(wrapper, 'source-mode').setValue('trunk')
    await field(wrapper, 'source-vlans').setValue('set')
    await field(wrapper, 'apply-mode').setValue(true)
    await field(wrapper, 'apply-vlans').setValue('copy')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(calls).toHaveLength(1)
    expect(calls[0].method).toBe('POST')
    expect(calls[0].url).toMatch(/\/port-sync\/rules$/)
    expect(calls[0].body).toMatchObject({
      name: 'Мой пустой trunk', action: 'auto', enabled: true,
      target: { role: 'any', mode: 'trunk', vlans: 'none' },
      source: { role: 'any', mode: 'trunk', vlans: 'set' },
      relation: { role: 'any', mode: 'any', vlans: 'any' },
      apply: { role: false, mode: true, vlans: 'copy' },
    })
    expect(calls[0].body).not.toHaveProperty('priority') // сервер поставит новое правило в конец
    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(usePortSyncRulesStore().rules.map((r) => r.id)).toContain('saved')
  })

  it('правило читается предложением и обновляется по мере ввода', async () => {
    const wrapper = mountForm(null)

    expect(wrapper.find('[data-sentence]').text()).toContain('Для любой пары портов подключения')

    await field(wrapper, 'target-vlans').setValue('none')
    await field(wrapper, 'apply-role').setValue(true)

    expect(wrapper.find('[data-sentence]').text()).toContain('порт: VLAN не назначены совсем')
    expect(wrapper.find('[data-sentence]').text()).toContain('роль соседнего порта')
  })

  it('подсказка действия меняется вместе с выбором', async () => {
    const wrapper = mountForm(null)
    const auto = wrapper.find('[data-hint="action"]').text()

    await field(wrapper, 'action').setValue('ignore')

    expect(wrapper.find('[data-hint="action"]').text()).not.toBe(auto)
    expect(wrapper.find('[data-hint="action"]').text()).toContain('не согласовывать')
  })

  it('одинаковые условия на оба порта при автоматическом действии — предупреждение, что направление придётся выбирать вручную', async () => {
    const wrapper = mountForm(null)
    expect(wrapper.find('[data-hint="symmetric"]').exists()).toBe(true) // оба порта без условий

    await field(wrapper, 'target-vlans').setValue('none')
    expect(wrapper.find('[data-hint="symmetric"]').exists()).toBe(false)

    await field(wrapper, 'source-vlans').setValue('none')
    expect(wrapper.find('[data-hint="symmetric"]').exists()).toBe(true)

    await field(wrapper, 'action').setValue('manual')
    expect(wrapper.find('[data-hint="symmetric"]').exists()).toBe(false) // для ручного правила направление не нужно
  })

  it('ошибка сервера (например, название занято) остаётся в окне, правило не считается сохранённым', async () => {
    stubApi(() => new Response(JSON.stringify({ detail: 'Правило с названием «X» уже есть' }), { status: 409 }))
    const wrapper = mountForm(null)
    await field(wrapper, 'name').setValue('X')
    await field(wrapper, 'apply-role').setValue(true)

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('уже есть')
    expect(wrapper.emitted('saved')).toBeUndefined()
    expect(usePortSyncRulesStore().rules).toEqual([])
  })
})

describe('PortSyncRuleFormModal.vue — правка (в том числе стандартного правила)', () => {
  it('стандартное правило открывается заполненным и с пометкой про сброс', () => {
    const wrapper = mountForm(rule())

    expect(wrapper.find('h2').text()).toBe('Редактировать правило согласования')
    expect(wrapper.find('[data-note="builtin"]').text()).toContain('Стандартное правило')
    expect((field(wrapper, 'name').element as HTMLInputElement).value).toBe('Пустой trunk получает VLAN соседа')
    expect((field(wrapper, 'target-mode').element as HTMLSelectElement).value).toBe('trunk')
    expect((field(wrapper, 'target-vlans').element as HTMLSelectElement).value).toBe('none')
    expect((field(wrapper, 'source-vlans').element as HTMLSelectElement).value).toBe('set')
    expect((field(wrapper, 'apply-vlans').element as HTMLSelectElement).value).toBe('copy')
    expect((field(wrapper, 'apply-mode').element as HTMLInputElement).checked).toBe(true)
  })

  it('изменение стандартного правила отправляется PUT с порядком проверки и условиями', async () => {
    const wrapper = mountForm(rule())
    await field(wrapper, 'source-vlans').setValue('all')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(calls[0].method).toBe('PUT')
    expect(calls[0].url).toMatch(/\/port-sync\/rules\/r-1$/)
    expect(calls[0].body.source).toEqual({ role: 'any', mode: 'trunk', vlans: 'all' })
    expect(calls[0].body.priority).toBe(10) // порядок при правке сохраняется
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })

  it('отмена и крестик закрывают окно без запросов', async () => {
    const wrapper = mountForm(rule())

    await wrapper.find('.icon-btn').trigger('click')
    await wrapper.find('.modal-foot .btn-secondary').trigger('click')

    expect(wrapper.emitted('close')).toHaveLength(2)
    expect(calls).toEqual([])
  })

  it('правка не меняет правило в списке до ответа сервера', async () => {
    const original = rule()
    const store = usePortSyncRulesStore()
    store.rules = [original]
    const wrapper = mountForm(original)

    await field(wrapper, 'name').setValue('Другое название')
    await field(wrapper, 'target-mode').setValue('access')

    expect(store.rules[0].name).toBe('Пустой trunk получает VLAN соседа')
    expect(store.rules[0].target.mode).toBe('trunk')
  })
})
