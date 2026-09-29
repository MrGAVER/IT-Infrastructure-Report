import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceVlanListEditor from '../DeviceVlanListEditor.vue'
import { useCatalogsStore } from '../../stores/catalogs'
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

    it('пункт 3 правки "создание физического устройства": вложенное создание НОВОГО Домена VLAN (внутри формы добавления VLAN) эмитится наружу отдельным событием vlan-domain-created', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
          const method = init?.method ?? 'GET'
          if (method === 'POST' && url.endsWith('/resources/vlan-domains')) {
            return jsonResponse({ id: 'domain-new', name: 'Новый домен' }, 201)
          }
          return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
        }),
      )
      const rows: DeviceVlanDraftRow[] = [{ vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' }]
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions } })

      await wrapper.find('.col-vlan button').trigger('click') // "+" у VLAN — открывает QuickAddModal('vlans')
      // Вложенный "+" у поля "Домен VLAN" ВНУТРИ этой модалки (domain_id -> nestedQuickAdd в
      // quickAdd/schema.ts) — оба тепортированы в document.body как соседние узлы, поэтому
      // ищем именно по aria-label, а не по общему для обеих модалок ".modal".
      await teleportedContent().find('button[aria-label="Добавить: Домен VLAN"]').trigger('click')

      const domainModal = teleportedContent().findAll('.modal')[1]
      await domainModal.find('input[type="text"]').setValue('Новый домен') // Наименование
      await domainModal.find('form').trigger('submit')
      await flushPromises()

      expect(wrapper.emitted('vlan-domain-created')?.[0]).toEqual([{ id: 'domain-new', name: 'Новый домен' }])
      // Сам VLAN в этот момент ещё не создан — только что созданный домен лишь подставился в
      // его поле domain_id (см. onNestedCreated в QuickAddModal.vue); vlan-created пока нет.
      expect(wrapper.emitted('vlan-created')).toBeUndefined()
    })

    it('фикс п.2.2: если устройство уже состоит ровно в одном домене VLAN, поле домена в форме добавления предзаполнено им', async () => {
      const catalogs = useCatalogsStore()
      catalogs.items['vlan-domains'] = [{ id: 'domain-x', name: 'Домен X' }]
      const rows: DeviceVlanDraftRow[] = [{ vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' }]
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions, deviceDomainId: 'domain-x' } })

      await wrapper.find('.col-vlan button').trigger('click')

      const domainInput = teleportedContent().find('.fk-row .searchable-select input')
      expect((domainInput.element as HTMLInputElement).value).toBe('Домен X')
    })

    it('без единственного домена (устройство ни в одном или в нескольких) поле домена в форме добавления пустое, как раньше', async () => {
      const rows: DeviceVlanDraftRow[] = [{ vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' }]
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions } }) // deviceDomainId не передан

      await wrapper.find('.col-vlan button').trigger('click')

      const domainInput = teleportedContent().find('.fk-row .searchable-select input')
      expect((domainInput.element as HTMLInputElement).value).toBe('')
    })
  })

  describe('пункт 3 правки "домен VLAN": кнопка "Включить в домен"', () => {
    const joinableDomains = [
      { id: 'dom-1', name: 'Ядро сети', description: null, source_device_id: null, auto_sync: false },
      { id: 'dom-2', name: 'Доступ', description: null, source_device_id: null, auto_sync: false },
    ]

    it('раздел не показывается, если joinableDomains пуст (устройство уже во всех доменах или доменов нет)', () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [], vlanOptions, joinableDomains: [] } })
      expect(wrapper.find('.join-domain-row').exists()).toBe(false)
    })

    it('показывает список доступных для включения доменов и по клику эмитит join-domain', async () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [], vlanOptions, joinableDomains } })

      const select = wrapper.find('.join-domain-row select')
      expect(select.findAll('option').map((o) => o.text())).toEqual(['— включить в домен —', 'Ядро сети', 'Доступ'])

      await select.setValue('dom-2')
      await wrapper.find('.join-domain-row button').trigger('click')

      expect(wrapper.emitted('join-domain')?.[0]).toEqual(['dom-2'])
    })

    it('кнопка "Включить" неактивна, пока домен не выбран', () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [], vlanOptions, joinableDomains } })
      expect((wrapper.find('.join-domain-row button').element as HTMLButtonElement).disabled).toBe(true)
    })

    it('после включения сбрасывает выбор в select (готов к следующему выбору)', async () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [], vlanOptions, joinableDomains } })
      const select = wrapper.find('.join-domain-row select')
      await select.setValue('dom-1')
      await wrapper.find('.join-domain-row button').trigger('click')

      expect((select.element as HTMLSelectElement).value).toBe('')
    })
  })

  describe('memberDomains: домены, в которые включено устройство', () => {
    it('показывает сохранённые домены и помечает домены, которые будут включены при сохранении', () => {
      const wrapper = mount(DeviceVlanListEditor, {
        props: {
          modelValue: [],
          vlanOptions,
          memberDomains: [
            { id: 'dom-1', name: 'Ядро сети', pending: false },
            { id: 'dom-2', name: 'Филиал', pending: true },
          ],
        },
      })
      const chips = wrapper.findAll('[data-testid="member-domain"]')
      expect(chips[0].text()).toBe('Ядро сети')
      expect(chips[1].text()).toContain('Филиал — будет включено при сохранении')
      expect(chips[1].classes()).toContain('pending')
      expect(chips[0].classes()).not.toContain('pending')
    })

    it('кнопка × есть только у pending-чипа и эмитит cancel-join-domain с id домена; у сохранённого членства отмены нет', async () => {
      const wrapper = mount(DeviceVlanListEditor, {
        props: {
          modelValue: [],
          vlanOptions,
          memberDomains: [
            { id: 'dom-1', name: 'Ядро сети', pending: false },
            { id: 'dom-2', name: 'Филиал', pending: true },
          ],
        },
      })
      const chips = wrapper.findAll('[data-testid="member-domain"]')
      expect(chips[0].find('[data-testid="cancel-join-domain"]').exists()).toBe(false)
      const cancel = chips[1].find('[data-testid="cancel-join-domain"]')
      expect(cancel.attributes('aria-label')).toBe('Отменить включение в домен «Филиал»')

      await cancel.trigger('click')
      expect(wrapper.emitted('cancel-join-domain')).toEqual([['dom-2']])
    })

    it('без доменов блок не рисуется', () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [], vlanOptions, memberDomains: [] } })
      expect(wrapper.find('[data-testid="member-domains"]').exists()).toBe(false)
    })
  })
})
