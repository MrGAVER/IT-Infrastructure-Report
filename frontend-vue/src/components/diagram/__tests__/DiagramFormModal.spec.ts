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

// FE-04 (ревью ветки fix/code-review-main-f06-stage2-f05): поле «порог сворачивания» не было ограничено сверху, и значение вроде
// 99999999999999999999 уходило на сервер, где (до BE-01) давало HTTP 500. Верхняя граница — контракт между потоками ревью:
// MAX_COLLAPSE_THRESHOLD = 1_000_000 (backend/app/api/diagram_schemas.py).
describe('DiagramFormModal.vue: порог сворачивания (FE-04)', () => {
  function postCalls(fetchMock: ReturnType<typeof vi.fn>) {
    return fetchMock.mock.calls.filter(([u, init]) => (init as RequestInit | undefined)?.method === 'POST' && (u as string).endsWith('/diagrams'))
  }

  async function submitWithThreshold(raw: string) {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && url.endsWith('/diagrams')) return jsonResponse({ id: 'd-new' }, 201)
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
    })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(DiagramFormModal)
    await flushPromises()
    await wrapper.find('input[type="text"]').setValue('Диаграмма')
    await wrapper.find('input[type="number"]').setValue(raw)
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    return { wrapper, fetchMock }
  }

  it('у поля порога заданы границы: min=1, max=1000000, step=1', async () => {
    const wrapper = mount(DiagramFormModal)
    await flushPromises()
    const input = wrapper.find('input[type="number"]')
    expect(input.attributes('min')).toBe('1')
    expect(input.attributes('max')).toBe('1000000')
    expect(input.attributes('step')).toBe('1')
  })

  it.each([
    ['больше предела', '1000001'],
    ['сверхбольшое (то, что давало 500)', '99999999999999999999'],
    ['ноль', '0'],
    ['отрицательное', '-5'],
    ['дробное', '1.5'],
    ['пустое', ''],
  ])('значение «%s» не уходит на сервер, у поля показана ошибка', async (_name, raw) => {
    const { wrapper, fetchMock } = await submitWithThreshold(raw)

    expect(postCalls(fetchMock)).toHaveLength(0)
    expect(wrapper.emitted('created')).toBeUndefined()
    const error = wrapper.find('[data-testid="threshold-error"]')
    expect(error.exists()).toBe(true)
    expect(error.attributes('role')).toBe('alert')
    expect(error.text()).toContain('1000000')
    // Ошибка привязана к полю: скринридер озвучит её вместе с полем, а у самого поля есть признак ошибки.
    const input = wrapper.find('input[type="number"]')
    expect(input.attributes('aria-invalid')).toBe('true')
    expect(input.attributes('aria-describedby')).toBe(error.attributes('id'))
  })

  it.each([
    ['нижняя граница', '1', 1],
    ['верхняя граница', '1000000', 1_000_000],
    ['обычное значение', '20', 20],
  ])('%s принимается и уходит на сервер как есть', async (_name, raw, expected) => {
    const { wrapper, fetchMock } = await submitWithThreshold(raw)

    const calls = postCalls(fetchMock)
    expect(calls).toHaveLength(1)
    expect(JSON.parse((calls[0][1] as RequestInit).body as string).collapse_threshold).toBe(expected)
    expect(wrapper.find('[data-testid="threshold-error"]').exists()).toBe(false)
    expect(wrapper.emitted('created')?.[0]).toEqual(['d-new'])
  })

  it('после исправления значения ошибка исчезает, и повторная отправка проходит', async () => {
    const { wrapper, fetchMock } = await submitWithThreshold('2000000')
    expect(wrapper.find('[data-testid="threshold-error"]').exists()).toBe(true)

    await wrapper.find('input[type="number"]').setValue('50')
    expect(wrapper.find('[data-testid="threshold-error"]').exists()).toBe(false)
    expect(wrapper.find('input[type="number"]').attributes('aria-invalid')).toBeUndefined()
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(postCalls(fetchMock)).toHaveLength(1)
  })
})
