import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises, DOMWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import DeviceInterfacesEditor from '../DeviceInterfacesEditor.vue'
import type { CatalogItem, InterfaceDraftRow, VLANDefinition } from '../../api/types'

const typeOptions: CatalogItem[] = [{ id: 't-eth', name: 'Ethernet' }]
const speedOptions: CatalogItem[] = [{ id: 's-1g', name: '1 Гбит/с' }]
const vlanOptions: VLANDefinition[] = []

// QuickAddModal.vue телепортируется в document.body — см. QuickAddModal.spec.ts.
function teleportedContent(): DOMWrapper<HTMLElement> {
  return new DOMWrapper(document.body)
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

function emptyRow(): InterfaceDraftRow {
  return { name: '', interface_type_id: '', mac_address: '', speed_id: '', is_management: false, is_data_transfer: false, description: '', vlan_ids: [], ips: [] }
}

beforeEach(() => {
  setActivePinia(createPinia())
  document.body.innerHTML = ''
})

describe('DeviceInterfacesEditor.vue', () => {
  it('показывает подсказку, если интерфейсы не добавлены', () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })
    expect(wrapper.text()).toContain('Интерфейсы не добавлены')
  })

  it('добавляет пустую строку по клику на "+ Интерфейс"', async () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })
    await wrapper.findAll('button.btn-secondary')[1].trigger('click') // 0 = "Сгенерировать", 1 = "+ Интерфейс"

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([emptyRow()])
  })

  it('генерирует интерфейсы по шаблону имени', async () => {
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })

    const inputs = wrapper.findAll('.generator input')
    await inputs[0].setValue('3') // Количество
    await inputs[1].setValue('eth{n}') // Шаблон имени
    await wrapper.find('.generator select').setValue('t-eth') // Тип по умолчанию
    await wrapper.find('.generator button.btn-secondary').trigger('click') // Сгенерировать

    const emitted = wrapper.emitted('update:modelValue')!
    const rows = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
    expect(rows.map((r) => r.name)).toEqual(['eth1', 'eth2', 'eth3'])
    expect(rows.every((r) => r.interface_type_id === 't-eth')).toBe(true)
  })

  it('генерация сохраняет id и IP уже существующего интерфейса по индексу', async () => {
    const existing: InterfaceDraftRow[] = [{ id: 'if-1', name: 'old-name', interface_type_id: '', mac_address: '', speed_id: '', is_management: true, is_data_transfer: false, description: '', vlan_ids: ['vlan-1'], ips: [{ id: 'ip-1', ip_address: '10.0.0.1', prefix_length: '24', purpose: '' }] }]
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: existing, typeOptions, speedOptions, vlanOptions } })

    await wrapper.find('.generator button.btn-secondary').trigger('click') // Сгенерировать с количеством по умолчанию (1)

    const emitted = wrapper.emitted('update:modelValue')!
    const rows = emitted[0][0] as InterfaceDraftRow[]
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ id: 'if-1', name: 'eth1', is_management: true, vlan_ids: ['vlan-1'], ips: existing[0].ips })
  })

  it('добавляет и удаляет IP-адрес интерфейса', async () => {
    const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1' }]
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })

    await wrapper.find('.ip-head button').trigger('click')
    let emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[0][0] as InterfaceDraftRow[])[0].ips).toEqual([{ ip_address: '', prefix_length: '', purpose: '' }])

    const withIp: InterfaceDraftRow[] = [{ ...rows[0], ips: [{ id: 'ip-1', ip_address: '10.0.0.5', prefix_length: '', purpose: '' }] }]
    await wrapper.setProps({ modelValue: withIp })
    await wrapper.find('.ip-row .icon-btn.danger').trigger('click')
    emitted = wrapper.emitted('update:modelValue')!
    expect((emitted[emitted.length - 1][0] as InterfaceDraftRow[])[0].ips).toEqual([])
  })

  it('удаляет интерфейс по клику на кнопку удаления карточки', async () => {
    const rows: InterfaceDraftRow[] = [
      { ...emptyRow(), id: 'if-1', name: 'eth1' },
      { ...emptyRow(), id: 'if-2', name: 'eth2' },
    ]
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions } })

    await wrapper.find('.iface-card-head .icon-btn.danger').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([rows[1]])
  })

  it('быстрое добавление типа интерфейса подставляет его в тип по умолчанию генератора', async () => {
    // Проверяем не .value самого <select> (в изолированном юнит-тесте у него нет пары <option>
    // для новой записи — typeOptions статичный проп, а не реактивная привязка к стору, как в
    // реальном приложении, см. OpenPortListEditor.spec.ts), а реальный эффект — что
    // сгенерированные интерфейсы получают именно новый тип.
    const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: [], typeOptions, speedOptions, vlanOptions } })

    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if ((init?.method ?? 'GET') === 'POST' && url.endsWith('/resources/interface-types')) {
          return jsonResponse({ id: 't-new', name: 'InfiniBand' }, 201)
        }
        return jsonResponse({ items: [], total: 0, offset: 0, limit: 1000 })
      }),
    )

    await wrapper.find('.generator .lookup-row button').trigger('click') // "+" рядом с "Тип по умолчанию"
    await teleportedContent().find('input[type="text"]').setValue('InfiniBand')
    await teleportedContent().find('form').trigger('submit')
    await flushPromises()

    await wrapper.find('.generator input[type="number"]').setValue('1') // genCount по умолчанию — 0 для пустого modelValue
    await wrapper.find('.generator button.btn-secondary').trigger('click') // Сгенерировать
    const emitted = wrapper.emitted('update:modelValue')!
    const rows = emitted[emitted.length - 1][0] as InterfaceDraftRow[]
    expect(rows[0].interface_type_id).toBe('t-new')
  })

  describe('VLAN на порту', () => {
    const vOptions: VLANDefinition[] = [
      { id: 'v-mgmt', vlan_id: 10, name: 'Управление', description: '', domain_id: null, domain_name: '', devices: [] },
      { id: 'v-guest', vlan_id: 20, name: 'Гостевой', description: '', domain_id: 'dom-1', domain_name: 'Филиал-1', devices: [] },
    ]

    it('без допустимых VLAN показывает подсказку вместо чекбоксов', () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: [] } })
      expect(wrapper.text()).toContain('Для типа устройства VLAN не назначены')
      expect(wrapper.find('.vlan-check').exists()).toBe(false)
    })

    it('рендерит чекбокс на каждый допустимый VLAN с подписью "номер — имя [домен]"', () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1' }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      const labels = wrapper.findAll('.vlan-check').map((l) => l.text())
      expect(labels).toEqual(['10 — Управление', '20 — Гостевой [Филиал-1]'])
    })

    it('уже назначенный VLAN отображается отмеченным чекбоксом', () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_ids: ['v-guest'] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })
      const checkboxes = wrapper.findAll('.vlan-check input[type="checkbox"]')
      expect((checkboxes[0].element as HTMLInputElement).checked).toBe(false) // v-mgmt
      expect((checkboxes[1].element as HTMLInputElement).checked).toBe(true) // v-guest
    })

    it('установка чекбокса добавляет id VLAN в vlan_ids, снятие — убирает', async () => {
      const rows: InterfaceDraftRow[] = [{ ...emptyRow(), name: 'eth1', vlan_ids: ['v-mgmt'] }]
      const wrapper = mount(DeviceInterfacesEditor, { props: { modelValue: rows, typeOptions, speedOptions, vlanOptions: vOptions } })

      const checkboxes = wrapper.findAll('.vlan-check input[type="checkbox"]')
      await checkboxes[1].setValue(true) // отмечаем v-guest в дополнение к уже стоящему v-mgmt
      let emitted = wrapper.emitted('update:modelValue')!
      expect((emitted[0][0] as InterfaceDraftRow[])[0].vlan_ids).toEqual(['v-mgmt', 'v-guest'])

      await wrapper.setProps({ modelValue: emitted[0][0] as InterfaceDraftRow[] })
      await wrapper.findAll('.vlan-check input[type="checkbox"]')[0].setValue(false) // снимаем v-mgmt
      emitted = wrapper.emitted('update:modelValue')!
      expect((emitted[emitted.length - 1][0] as InterfaceDraftRow[])[0].vlan_ids).toEqual(['v-guest'])
    })
  })
})
