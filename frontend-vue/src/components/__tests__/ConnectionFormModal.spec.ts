import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ConnectionFormModal from '../ConnectionFormModal.vue'
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
  vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })))
})

describe('ConnectionFormModal.vue — быстрое добавление типа подключения', () => {
  it('подставляет id быстро добавленного типа подключения в форму', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items['connection-types'] = []
    const wrapper = mount(ConnectionFormModal, { props: { connection: null } })

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/connection-types')) {
          return jsonResponse({ id: 'ct-new', name: 'Оптоволокно' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    await wrapper.find('.lookup-row button').trigger('click') // "+" рядом с типом подключения — единственный lookup-row в форме
    await teleportedContent().find('input[type="text"]').setValue('Оптоволокно')
    await teleportedContent().find('form').trigger('submit')
    await flushPromises()

    const select = wrapper.find('.lookup-row select')
    expect((select.element as HTMLSelectElement).value).toBe('ct-new')
  })
})
