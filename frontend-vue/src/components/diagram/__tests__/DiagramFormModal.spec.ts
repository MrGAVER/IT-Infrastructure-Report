import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DiagramFormModal from '../DiagramFormModal.vue'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })),
  )
})

describe('DiagramFormModal.vue', () => {
  it('создаёт диаграмму с пустым scope_filter, если ничего не выбрано в области охвата', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/diagrams')) {
        return jsonResponse({ id: 'd-new', name: 'Моя диаграмма' }, 201)
      }
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mount(DiagramFormModal)
    await flushPromises()
    await wrapper.find('input[type="text"]').setValue('Моя диаграмма')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const postCall = fetchMock.mock.calls.find(([, init]) => (init?.method ?? 'GET') === 'POST')
    const payload = JSON.parse((postCall![1] as RequestInit).body as string)
    expect(payload.name).toBe('Моя диаграмма')
    expect(payload.scope_filter).toEqual({})
    expect(wrapper.emitted('created')?.[0]).toEqual(['d-new'])
  })

  it('не отправляет запрос без названия', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 }))
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(DiagramFormModal)
    await flushPromises()
    fetchMock.mockClear()

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining('/diagrams'), expect.objectContaining({ method: 'POST' }))
    expect(wrapper.emitted('created')).toBeUndefined()
  })

  it('клик по "Отмена" эмитит close', async () => {
    const wrapper = mount(DiagramFormModal)
    await flushPromises()
    const cancelBtn = wrapper.findAll('button').find((b) => b.text() === 'Отмена')
    await cancelBtn!.trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('выбор структурных единиц попадает в scope_filter.structural_unit_ids', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/resources/structural-units')) {
        return jsonResponse({ items: [{ id: 'su-1', name: 'Филиал А', parent_id: null }], total: 1, offset: 0, limit: 1000 })
      }
      if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/diagrams')) {
        return jsonResponse({ id: 'd-new' }, 201)
      }
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const wrapper = mount(DiagramFormModal)
    await flushPromises()
    await wrapper.find('input[type="text"]').setValue('С фильтром')

    const select = wrapper.findAll('select').find((s) => s.attributes('multiple') !== undefined)!
    const option = select.find('option')
    ;(option.element as HTMLOptionElement).selected = true
    await select.trigger('change')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const postCall = fetchMock.mock.calls.find(([u, init]) => (init?.method ?? 'GET') === 'POST' && (u as string).endsWith('/diagrams'))
    const payload = JSON.parse((postCall![1] as RequestInit).body as string)
    expect(payload.scope_filter.structural_unit_ids).toEqual(['su-1'])
  })
})
