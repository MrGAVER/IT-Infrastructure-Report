import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BuildingFormModal from '../BuildingFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'

// QuickAddModal.vue телепортируется в document.body — см. QuickAddModal.spec.ts.
function teleportedContent(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
})

describe('BuildingFormModal.vue', () => {
  it('рядом с полем "Структурная единица" есть кнопка быстрого добавления', () => {
    const wrapper = mount(BuildingFormModal, { props: { building: null } })
    expect(wrapper.find('.lookup-row button').exists()).toBe(true)
  })

  it('быстрое добавление структурной единицы подставляет её в поле формы', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items = { ...catalogs.items, 'structural-units': [] } as any
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/structural-units')) {
          return jsonResponse({ id: 'su-new', name: 'Филиал «Север»' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )
    const wrapper = mount(BuildingFormModal, { props: { building: null } })

    await wrapper.find('.lookup-row button').trigger('click')
    await teleportedContent().find('input[type="text"]').setValue('Филиал «Север»')
    await teleportedContent().find('form').trigger('submit')
    await flushPromises()

    expect((wrapper.find('.lookup-row select').element as HTMLSelectElement).value).toBe('su-new')
  })
})
