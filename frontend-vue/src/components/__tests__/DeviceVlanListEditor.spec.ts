import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceVlanListEditor from '../DeviceVlanListEditor.vue'
import type { DeviceVlanDraftRow, VLANDefinition } from '../../api/types'

const vlanOptions: VLANDefinition[] = [
  { id: 'v-10', vlan_id: 10, name: 'Мониторинг', description: '', domain_id: null, domain_name: '', devices: [] },
  { id: 'v-20', vlan_id: 20, name: 'Управление', description: '', domain_id: 'dom-1', domain_name: 'Ядро сети', devices: [] },
]

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

describe('DeviceVlanListEditor.vue', () => {
  it('показывает подсказку, если VLAN не назначены', () => {
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [], vlanOptions } })
    expect(wrapper.text()).toContain('VLAN не назначены')
  })

  it('добавляет пустую строку по клику на "+ VLAN"', async () => {
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [], vlanOptions } })
    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' }])
  })

  it('показывает домен в подписи опции VLAN', () => {
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [{ vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' }], vlanOptions } })
    expect(wrapper.find('.col-vlan select').text()).toContain('20 — Управление [Ядро сети]')
  })

  it('обновляет IP-адрес, не мутируя исходный проп', async () => {
    const rows: DeviceVlanDraftRow[] = [{ id: 'dv-1', vlan_id: 'v-10', ip_address: '', prefix_length: '', is_management: false, description: '' }]
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions } })

    await wrapper.find('input.col-ip').setValue('10.0.10.5')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ id: 'dv-1', vlan_id: 'v-10', ip_address: '10.0.10.5', prefix_length: '', is_management: false, description: '' }])
    expect(rows[0].ip_address).toBe('')
  })

  it('отмечает VLAN как управляющий чекбоксом', async () => {
    const rows: DeviceVlanDraftRow[] = [{ vlan_id: 'v-10', ip_address: '', prefix_length: '', is_management: false, description: '' }]
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions } })

    await wrapper.find('input[type="checkbox"]').setValue(true)

    const emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as DeviceVlanDraftRow[])[0].is_management).toBe(true)
  })

  it('удаляет строку по клику на кнопку удаления', async () => {
    const rows: DeviceVlanDraftRow[] = [
      { id: 'dv-1', vlan_id: 'v-10', ip_address: '', prefix_length: '', is_management: false, description: '' },
      { id: 'dv-2', vlan_id: 'v-20', ip_address: '', prefix_length: '', is_management: true, description: '' },
    ]
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions } })

    await wrapper.findAll('.icon-btn.danger')[0].trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([rows[1]])
  })

  describe('быстрое добавление VLAN (п.3.9)', () => {
    it('рядом с полем VLAN есть кнопка быстрого добавления', () => {
      const rows: DeviceVlanDraftRow[] = [{ vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' }]
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions } })
      expect(wrapper.find('.col-vlan button').exists()).toBe(true)
    })

    it('созданный VLAN подставляется в строку и наружу эмитится vlan-created', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/vlans')) {
            return jsonResponse({ id: 'v-new', vlan_id: 42, name: 'Гостевой' }, 201)
          }
          return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
        }),
      )
      const rows: DeviceVlanDraftRow[] = [{ vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' }]
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions } })

      await wrapper.find('.col-vlan button').trigger('click')
      await teleportedContent().find('input[type="number"]').setValue('42') // VLAN ID
      await teleportedContent().findAll('input[type="text"]')[0].setValue('Гостевой') // Имя
      await teleportedContent().find('form').trigger('submit')
      await flushPromises()

      const emitted = wrapper.emitted('update:modelValue')!
      expect((emitted[0][0] as DeviceVlanDraftRow[])[0].vlan_id).toBe('v-new')
      // Полная запись, а не просто факт создания — родителю (DeviceFormModal.vue) нужен
      // domain_id, чтобы при необходимости добавить устройство в участники домена (фикс п.1.3.8).
      expect(wrapper.emitted('vlan-created')?.[0]).toEqual([{ id: 'v-new', vlan_id: 42, name: 'Гостевой' }])
    })
  })
})
