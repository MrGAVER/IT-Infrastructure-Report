import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import StructuralUnitFormModal from '../StructuralUnitFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'

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

describe('StructuralUnitFormModal.vue', () => {
  it('рядом с полем "Родительская единица" есть кнопка быстрого добавления', () => {
    const wrapper = mount(StructuralUnitFormModal, { props: { unit: null, defaultParentId: null } })
    expect(wrapper.find('.lookup-row button').exists()).toBe(true)
  })

  it('быстрое добавление родительской единицы подставляет её в поле формы', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items = { ...catalogs.items, 'structural-units': [{ id: 'su-1', name: 'Головной офис' }] } as any
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/structural-units')) {
          return jsonResponse({ id: 'su-new', name: 'Филиал «Юг»' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )
    const wrapper = mount(StructuralUnitFormModal, { props: { unit: null, defaultParentId: null } })

    await wrapper.find('.lookup-row button').trigger('click')
    await teleportedContent().find('input[type="text"]').setValue('Филиал «Юг»')
    await teleportedContent().find('form').trigger('submit')
    await flushPromises()

    expect((wrapper.find('.lookup-row select').element as HTMLSelectElement).value).toBe('su-new')
  })

  it('редактируемая единица не может быть выбрана себе же родителем', () => {
    const catalogs = useCatalogsStore()
    catalogs.items = {
      ...catalogs.items,
      'structural-units': [
        { id: 'su-1', name: 'Головной офис' },
        { id: 'su-2', name: 'Филиал' },
      ],
    } as any
    const wrapper = mount(StructuralUnitFormModal, {
      props: { unit: { id: 'su-1', name: 'Головной офис', parent_id: null, description: null }, defaultParentId: null },
    })
    const options = wrapper.find('.lookup-row select').findAll('option').map((o) => o.element.value)
    expect(options).not.toContain('su-1')
    expect(options).toContain('su-2')
  })
})
