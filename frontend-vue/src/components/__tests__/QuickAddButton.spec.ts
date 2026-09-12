import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import QuickAddButton from '../QuickAddButton.vue'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

// Открытая QuickAddModal.vue телепортируется в document.body — см. комментарий в
// QuickAddModal.spec.ts.
function body(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
})

describe('QuickAddButton.vue', () => {
  it('модалка не отрендерена, пока кнопка не нажата', () => {
    mount(QuickAddButton, { props: { resource: 'manufacturers' } })
    expect(body().find('.overlay').exists()).toBe(false)
  })

  it('открывает модалку по клику', async () => {
    const wrapper = mount(QuickAddButton, { props: { resource: 'manufacturers' } })
    await wrapper.find('button').trigger('click')

    expect(body().text()).toContain('Добавить: Производитель')
  })

  it('закрывает модалку и эмитит created после успешного сохранения', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/manufacturers')) {
          return jsonResponse({ id: 'mfr-new', name: 'Cisco' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    const wrapper = mount(QuickAddButton, { props: { resource: 'manufacturers' } })
    await wrapper.find('button').trigger('click')
    await body().find('input[type="text"]').setValue('Cisco')
    await body().find('form').trigger('submit')
    await flushPromises()

    expect(body().find('.overlay').exists()).toBe(false)
    expect(wrapper.emitted('created')?.[0][0]).toEqual({ id: 'mfr-new', name: 'Cisco' })
  })
})
