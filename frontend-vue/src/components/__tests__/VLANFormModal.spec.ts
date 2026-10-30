import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import VLANFormModal from '../VLANFormModal.vue'
import { useCatalogsStore } from '../../stores/catalogs'
import type { VLANDefinition } from '../../api/types'

function teleportedContent(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function stubCreateVlan() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      if (method === 'POST' && url.endsWith('/resources/vlans')) {
        const body = JSON.parse(String(init?.body))
        return jsonResponse({ id: 'v-new', ...body }, 201)
      }
      return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
    }),
  )
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
})

describe('VLANFormModal.vue', () => {
  // Регресс: v-model на <input type="number"> Vue приводит значение к числу при вводе даже
  // без модификатора .number — form.vlan_id.trim() после этого падал TypeError'ом, и клик
  // "Добавить" внешне не давал никакого эффекта (ни ошибки, ни сохранения).
  it('клик "Добавить" после ввода VLAN ID реально создаёт VLAN, а не падает молча', async () => {
    stubCreateVlan()
    const wrapper = mount(VLANFormModal, { props: { definition: null } })

    await wrapper.find('input[type="number"]').setValue('42')
    await wrapper.find('input[type="text"]').setValue('Гостевой')
    await wrapper.findAll('.modal-foot button')[1].trigger('click') // "Добавить"
    await flushPromises()

    expect(wrapper.emitted('saved')).toBeTruthy()
    expect(wrapper.find('.form-error').exists()).toBe(false)
  })

  it('пустой VLAN ID показывает ошибку валидации, а не падает', async () => {
    stubCreateVlan()
    const wrapper = mount(VLANFormModal, { props: { definition: null } })

    await wrapper.find('input[type="text"]').setValue('Гостевой')
    await wrapper.findAll('.modal-foot button')[1].trigger('click')

    expect(wrapper.find('.form-error').text()).toContain('VLAN ID')
    expect(wrapper.emitted('saved')).toBeFalsy()
  })

  it('повторный сабмит после правки числового VLAN ID тоже не падает (форма уже "потрогала" число)', async () => {
    stubCreateVlan()
    const wrapper = mount(VLANFormModal, { props: { definition: null } })

    await wrapper.find('input[type="number"]').setValue('4200') // невалидный (> 4094)
    await wrapper.find('input[type="text"]').setValue('Гостевой')
    await wrapper.findAll('.modal-foot button')[1].trigger('click')
    expect(wrapper.find('.form-error').exists()).toBe(true) // ожидаемая ошибка валидации

    await wrapper.find('input[type="number"]').setValue('42') // исправляем
    await wrapper.findAll('.modal-foot button')[1].trigger('click')
    await flushPromises()
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('редактирование существующего VLAN подставляет его VLAN ID и позволяет сохранить', async () => {
    stubCreateVlan()
    const definition: VLANDefinition = { id: 'v-1', vlan_id: 100, name: 'Управление', description: '', domain_id: null, domain_name: '', devices: [] }
    const wrapper = mount(VLANFormModal, { props: { definition } })

    expect((wrapper.find('input[type="number"]').element as HTMLInputElement).value).toBe('100')
    await wrapper.findAll('.modal-foot button')[1].trigger('click')
    await flushPromises()
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('рядом с полем "Домен VLAN" есть кнопка быстрого добавления', () => {
    const wrapper = mount(VLANFormModal, { props: { definition: null } })
    expect(wrapper.find('.lookup-row button').exists()).toBe(true)
  })

  it('существующие домены отображаются в select, а быстрое добавление подставляет новый домен', async () => {
    const catalogs = useCatalogsStore()
    catalogs.items = { ...catalogs.items, 'vlan-domains': [{ id: 'd-1', name: 'Филиал-1' }] } as any
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/vlan-domains')) {
          return jsonResponse({ id: 'd-new', name: 'Филиал-2' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )
    const wrapper = mount(VLANFormModal, { props: { definition: null } })

    const options = wrapper
      .find('.lookup-row select')
      .findAll('option')
      .map((o) => o.text())
    expect(options).toEqual(['— локальный (без домена) —', 'Филиал-1'])

    await wrapper.find('.lookup-row button').trigger('click')
    await teleportedContent().find('input[type="text"]').setValue('Филиал-2')
    await teleportedContent().find('form').trigger('submit')
    await flushPromises()

    expect((wrapper.find('.lookup-row select').element as HTMLSelectElement).value).toBe('d-new')
  })
})
