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

  it('показывает домен в подписи опции VLAN', async () => {
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [{ vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' }], vlanOptions } })
    // Поле VLAN — SearchableSelect (поиск вводом текста), список опций открывается фокусом на поле.
    await wrapper.find('.col-vlan .searchable-select input').trigger('focus')
    expect(wrapper.find('.col-vlan .ss-panel').text()).toContain('20 — Управление [Ядро сети]')
  })

  it('поле VLAN фильтруется вводом текста и эмитит id выбранного VLAN', async () => {
    const rows: DeviceVlanDraftRow[] = [{ vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' }]
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions } })
    const input = wrapper.find('.col-vlan .searchable-select input')

    await input.trigger('focus')
    await input.setValue('управл')
    const options = wrapper.findAll('.col-vlan .ss-option')
    expect(options.map((o) => o.text())).toEqual(['20 — Управление [Ядро сети]'])
    await options[0].trigger('mousedown')

    expect(wrapper.emitted('update:modelValue')![0][0]).toEqual([{ vlan_id: 'v-20', ip_address: '', prefix_length: '', is_management: false, description: '' }])
  })

  it('уже выбранный VLAN, скрытый фильтром по домену, остаётся подписан в своей строке, но не появляется в опциях других строк', async () => {
    const hidden: VLANDefinition = { id: 'v-hidden', vlan_id: 5, name: 'Общий', description: '', domain_id: null, domain_name: '', devices: [] }
    const rows: DeviceVlanDraftRow[] = [
      { id: 'dv-1', vlan_id: 'v-hidden', ip_address: '', prefix_length: '', is_management: false, description: '' },
      { vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' },
    ]
    // vlanOptions — уже отфильтрованный родителем список (только VLAN домена устройства), в нём нет v-hidden.
    const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions: [vlanOptions[1]], allVlanDefinitions: [...vlanOptions, hidden] } })

    const inputs = wrapper.findAll('.col-vlan .searchable-select input')
    expect((inputs[0].element as HTMLInputElement).value).toBe('5 — Общий')

    await inputs[1].trigger('focus')
    const secondRowOptions = wrapper.findAll('.col-vlan .searchable-select')[1].findAll('.ss-option').map((o) => o.text())
    expect(secondRowOptions).toEqual(['20 — Управление [Ядро сети]'])
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
  describe('правило «как у открытых портов»: отсев добавленных, сортировка при добавлении, повторы', () => {
    const blank = (): DeviceVlanDraftRow => ({ vlan_id: '', ip_address: '', prefix_length: '', is_management: false, description: '' })
    const filled = (vlan_id: string, id?: string): DeviceVlanDraftRow => ({ ...(id ? { id } : {}), vlan_id, ip_address: '', prefix_length: '', is_management: false, description: '' })
    const options: VLANDefinition[] = [
      { id: 'v-30', vlan_id: 30, name: 'Гости', description: '', domain_id: null, domain_name: '', devices: [] },
      { id: 'v-10', vlan_id: 10, name: 'Мониторинг', description: '', domain_id: null, domain_name: '', devices: [] },
      { id: 'v-20', vlan_id: 20, name: 'Управление', description: '', domain_id: null, domain_name: '', devices: [] },
    ]

    async function choices(wrapper: ReturnType<typeof mount>, rowIndex: number): Promise<string[]> {
      const select = wrapper.findAll('.col-vlan .searchable-select')[rowIndex]
      await select.find('input').trigger('focus')
      return select.findAll('.ss-option').map((o) => o.text())
    }

    it('VLAN, уже добавленный в другой строке, не предлагается в списке выбора; собственный выбор строки остаётся; список по возрастанию номера', async () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [filled('v-20'), blank()], vlanOptions: options } })
      expect(await choices(wrapper, 1)).toEqual(['10 — Мониторинг', '30 — Гости'])
      expect(await choices(wrapper, 0)).toEqual(['10 — Мониторинг', '20 — Управление', '30 — Гости'])
    })

    it('когда все VLAN уже добавлены, в пустой строке показывается пояснение вместо «Ничего не найдено»', async () => {
      const rows = [filled('v-10'), filled('v-20'), filled('v-30'), blank()]
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions: options } })
      const select = wrapper.findAll('.col-vlan .searchable-select')[3]
      await select.find('input').trigger('focus')
      expect(select.text()).toContain('Все доступные VLAN уже добавлены')
    })

    it('«+ VLAN» упорядочивает заполненные строки по номеру и ставит новую пустую в конец', async () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [filled('v-30', 'dv-3'), filled('v-10', 'dv-1'), blank()], vlanOptions: options } })
      await wrapper.find('button.add-btn').trigger('click')

      const emitted = wrapper.emitted('update:modelValue')![0][0] as DeviceVlanDraftRow[]
      expect(emitted.map((r) => r.vlan_id)).toEqual(['v-10', 'v-30', '', ''])
      expect(emitted[0].id).toBe('dv-1')
    })

    it('выбор VLAN в строке НЕ переставляет строки (порядок меняется только при добавлении следующей)', async () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [filled('v-30'), blank()], vlanOptions: options } })
      const select = wrapper.findAll('.col-vlan .searchable-select')[1]
      await select.find('input').trigger('focus')
      await select.findAll('.ss-option')[0].trigger('mousedown')

      const emitted = wrapper.emitted('update:modelValue')![0][0] as DeviceVlanDraftRow[]
      expect(emitted.map((r) => r.vlan_id)).toEqual(['v-30', 'v-10'])
    })

    it('повторяющиеся строки подсвечиваются и под списком показывается одно сообщение', () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [filled('v-10'), filled('v-20'), filled('v-10')], vlanOptions: options } })
      const rows = wrapper.findAll('.nested-row')
      expect(rows.map((r) => r.classes().includes('row-duplicate'))).toEqual([true, false, true])
      expect(wrapper.find('.dup-error').text()).toContain('VLAN 10 указан несколько раз')
    })

    it('без повторов сообщения и подсветки нет', () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: [filled('v-10'), filled('v-20')], vlanOptions: options } })
      expect(wrapper.find('.dup-error').exists()).toBe(false)
      expect(wrapper.find('.row-duplicate').exists()).toBe(false)
    })
  })

  describe('сворачивание блока по порогу строк', () => {
    const makeRows = (n: number): DeviceVlanDraftRow[] =>
      Array.from({ length: n }, (_, i) => ({ id: `dv-${i}`, vlan_id: `v-${i + 1}`, ip_address: '', prefix_length: '', is_management: false, description: '' }))
    const manyOptions: VLANDefinition[] = Array.from({ length: 30 }, (_, i) => ({
      id: `v-${i + 1}`, vlan_id: i + 1, name: `Сеть ${i + 1}`, description: '', domain_id: null, domain_name: '', devices: [],
    }))
    const toggle = (w: ReturnType<typeof mount>) => w.find('[data-testid="vlan-collapse-toggle"]')

    it('по умолчанию порог 10: на пороге (ровно 10 строк) блок развёрнут и кнопки сворачивания нет', () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: makeRows(10), vlanOptions: manyOptions } })
      expect(wrapper.findAll('.nested-row')).toHaveLength(10)
      expect(wrapper.find('[data-testid="vlan-collapsed"]').exists()).toBe(false)
      expect(toggle(wrapper).exists()).toBe(false)
    })

    it('при 11 строках блок свёрнут: строк нет, есть счётчик, сводка номеров и кнопка «Развернуть»', () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: makeRows(11), vlanOptions: manyOptions } })
      expect(wrapper.findAll('.nested-row')).toHaveLength(0)
      const summary = wrapper.find('[data-testid="vlan-collapsed"]')
      expect(summary.text()).toContain('Назначено VLAN: 11')
      expect(summary.text()).toContain('1, 2, 3')
      expect(toggle(wrapper).text()).toContain('Развернуть (11)')
      expect(toggle(wrapper).attributes('aria-expanded')).toBe('false')
    })

    it('сводка длинного списка обрезается многоточием', () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: makeRows(25), vlanOptions: manyOptions } })
      expect(wrapper.find('.summary-numbers').text()).toBe('1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, …')
    })

    it('порог берётся из collapseAfter: при 3 свёрнуто уже 4 строки, при 50 — 30 строк развёрнуты', () => {
      expect(mount(DeviceVlanListEditor, { props: { modelValue: makeRows(4), vlanOptions: manyOptions, collapseAfter: 3 } }).find('[data-testid="vlan-collapsed"]').exists()).toBe(true)
      expect(mount(DeviceVlanListEditor, { props: { modelValue: makeRows(30), vlanOptions: manyOptions, collapseAfter: 50 } }).findAll('.nested-row')).toHaveLength(30)
    })

    it('кнопка разворачивает и снова сворачивает блок', async () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: makeRows(12), vlanOptions: manyOptions } })
      await toggle(wrapper).trigger('click')
      expect(wrapper.findAll('.nested-row')).toHaveLength(12)
      expect(toggle(wrapper).text()).toContain('Свернуть')
      expect(toggle(wrapper).attributes('aria-expanded')).toBe('true')

      await toggle(wrapper).trigger('click')
      expect(wrapper.findAll('.nested-row')).toHaveLength(0)
    })

    it('«+ VLAN» на свёрнутом блоке разворачивает его, чтобы новая строка была видна', async () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: makeRows(11), vlanOptions: manyOptions } })
      await wrapper.find('button.add-btn').trigger('click')
      await wrapper.setProps({ modelValue: wrapper.emitted('update:modelValue')![0][0] as DeviceVlanDraftRow[] })

      expect(wrapper.findAll('.nested-row')).toHaveLength(12)
    })

    it('добавление 11-й строки в развёрнутом блоке не сворачивает его под руками пользователя', async () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: makeRows(10), vlanOptions: manyOptions } })
      await wrapper.find('button.add-btn').trigger('click')
      await wrapper.setProps({ modelValue: wrapper.emitted('update:modelValue')![0][0] as DeviceVlanDraftRow[] })

      expect(wrapper.findAll('.nested-row')).toHaveLength(11)
      expect(wrapper.find('[data-testid="vlan-collapsed"]').exists()).toBe(false)
    })

    it('после удаления строк ниже порога флаг ручного раскрытия сбрасывается: следующее превышение снова сворачивает блок', async () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: makeRows(11), vlanOptions: manyOptions } })
      await toggle(wrapper).trigger('click') // развернули вручную
      await wrapper.setProps({ modelValue: makeRows(5) })
      await wrapper.setProps({ modelValue: makeRows(15) }) // например, «Включить в домен» добавило много VLAN

      expect(wrapper.find('[data-testid="vlan-collapsed"]').exists()).toBe(true)
    })

    it('expand() (вызывается формой при ошибке в скрытой строке) раскрывает блок', async () => {
      const wrapper = mount(DeviceVlanListEditor, { props: { modelValue: makeRows(11), vlanOptions: manyOptions } })
      ;(wrapper.vm as unknown as { expand: () => void }).expand()
      await wrapper.vm.$nextTick()
      expect(wrapper.findAll('.nested-row')).toHaveLength(11)
    })

    it('домены VLAN и блок «Включить в домен» остаются видны на свёрнутом блоке', () => {
      const wrapper = mount(DeviceVlanListEditor, {
        props: {
          modelValue: makeRows(11),
          vlanOptions: manyOptions,
          memberDomains: [{ id: 'dom-1', name: 'Ядро сети', pending: false }],
          joinableDomains: [{ id: 'dom-2', name: 'Филиал' } as never],
        },
      })
      expect(wrapper.find('[data-testid="member-domains"]').exists()).toBe(true)
      expect(wrapper.find('.join-domain-row').exists()).toBe(true)
    })
  })

  describe('VLAN, заданные общей настройкой стека: правка запрещена', () => {
    const rows: DeviceVlanDraftRow[] = [
      { vlan_id: 'v-10', ip_address: '10.0.10.1', prefix_length: '24', is_management: true, description: '' },
      { vlan_id: 'v-20', ip_address: '10.0.20.7', prefix_length: '24', is_management: false, description: '' },
    ]
    const lockedVlans = { 'v-10': 'Задано для стека «Ядро»: меняется в общих настройках VLAN стека' }

    function mountLocked() {
      return mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions, lockedVlans } })
    }

    it('у общей строки заблокированы IP, префикс, «Управление», выбор VLAN и удаление; соседняя строка редактируется', () => {
      const wrapper = mountLocked()
      const [locked, free] = wrapper.findAll('.nested-row')

      expect(locked.attributes('data-locked')).toBe('true')
      expect(locked.attributes('title')).toContain('«Ядро»')
      expect((locked.find('input.col-ip').element as HTMLInputElement).disabled).toBe(true)
      expect((locked.find('input[type="number"]').element as HTMLInputElement).disabled).toBe(true)
      expect((locked.find('input[type="checkbox"]').element as HTMLInputElement).disabled).toBe(true)
      expect((locked.find('.col-vlan .searchable-select input').element as HTMLInputElement).disabled).toBe(true)
      expect((locked.find('button[aria-label="Удалить VLAN"]').element as HTMLButtonElement).disabled).toBe(true)

      expect(free.attributes('data-locked')).toBeUndefined()
      expect((free.find('input.col-ip').element as HTMLInputElement).disabled).toBe(false)
      expect((free.find('input[type="checkbox"]').element as HTMLInputElement).disabled).toBe(false)
      expect((free.find('button[aria-label="Удалить VLAN"]').element as HTMLButtonElement).disabled).toBe(false)
    })

    it('показывает пояснение со счётчиком заблокированных VLAN; без блокировок пояснения нет', () => {
      expect(mountLocked().get('[data-testid="vlan-locked-note"]').text()).toContain('1')
      const plain = mount(DeviceVlanListEditor, { props: { modelValue: rows, vlanOptions } })
      expect(plain.find('[data-testid="vlan-locked-note"]').exists()).toBe(false)
      expect(plain.findAll('.nested-row').every((r) => r.attributes('data-locked') === undefined)).toBe(true)
    })

    it('заблокированная строка не эмитит изменений при попытке правки или удаления', async () => {
      const wrapper = mountLocked()
      const [locked] = wrapper.findAll('.nested-row')

      await locked.find('input.col-ip').setValue('9.9.9.9')
      await locked.find('button[aria-label="Удалить VLAN"]').trigger('click')

      expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    })

    it('у свободной строки правка и удаление работают как раньше', async () => {
      const wrapper = mountLocked()
      const [, free] = wrapper.findAll('.nested-row')

      await free.find('input.col-ip').setValue('10.0.20.9')

      const emitted = wrapper.emitted('update:modelValue')!
      expect((emitted.at(-1)![0] as DeviceVlanDraftRow[])[1].ip_address).toBe('10.0.20.9')
      expect((emitted.at(-1)![0] as DeviceVlanDraftRow[])[0].ip_address).toBe('10.0.10.1') // общая строка не тронута
    })
  })
})
