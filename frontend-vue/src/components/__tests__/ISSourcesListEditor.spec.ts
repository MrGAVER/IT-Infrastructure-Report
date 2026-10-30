import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ISSourcesListEditor from '../ISSourcesListEditor.vue'
import type { Container, Device, ISSourceDraftRow, VirtualMachine } from '../../api/types'

const devices: Device[] = [
  { id: 'dev-1', system_name: 'srv-01', serial_number: 'SN-1' } as Device,
  { id: 'dev-2', system_name: 'srv-02', serial_number: 'SN-2' } as Device,
]
const vms: VirtualMachine[] = [
  { id: 'vm-1', name: 'app-vm-1', physical_device_id: 'dev-1' } as VirtualMachine,
  { id: 'vm-2', name: 'app-vm-2', physical_device_id: 'dev-2' } as VirtualMachine,
]
const containers: Container[] = [
  { id: 'ct-1', name: 'nginx-container', virtual_machine_id: null, physical_device_id: null, runtime: null, runtime_version: null, purpose: null },
]

function emptyRow(): ISSourceDraftRow {
  return { source_type: 'manual', owner_id: '', vmHostHint: '', ips: [], purpose: '', role: '', external_interaction: false }
}

const baseProps = { deviceOptions: devices, vmOptions: vms, containerOptions: containers }

type Wrapper = ReturnType<typeof mount>

// Физический сервер, ВМ и контейнер — SearchableSelect (классы .col-device/.col-vm/.col-container),
// а не нативные select: выбор — фокус на поле и mousedown по опции с нужной подписью.
async function pickOption(wrapper: Wrapper, column: '.col-device' | '.col-vm' | '.col-container', label: string) {
  await wrapper.find(`${column} input`).trigger('focus')
  const option = wrapper.findAll(`${column} .ss-option`).find((o) => o.text() === label)
  expect(option, `опция «${label}» в ${column}`).toBeTruthy()
  await option!.trigger('mousedown')
}

function shownValue(wrapper: Wrapper, column: '.col-device' | '.col-vm' | '.col-container'): string {
  return (wrapper.find(`${column} input`).element as HTMLInputElement).value
}

describe('ISSourcesListEditor.vue', () => {
  it('показывает подсказку, если источники не добавлены', () => {
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: [] } })
    expect(wrapper.text()).toContain('Не добавлено')
  })

  it('добавляет пустую строку с типом "вручную" по умолчанию', async () => {
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: [] } })
    await wrapper.find('button.add-btn').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([emptyRow()])
  })

  it('при смене типа сбрасывает owner_id/vmHostHint/ips выбранной строки', async () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'manual', ips: [{ ip_address: '10.0.0.1' }] }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    await wrapper.find('.source-grid select').setValue('device')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ ...emptyRow(), source_type: 'device' }])
  })

  it('при выборе ВМ owner_id становится id ВМ, тип переключается на "vm", хост виден в селекте сервера', async () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'vm' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    await pickOption(wrapper, '.col-vm', 'app-vm-2')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ ...emptyRow(), source_type: 'vm', owner_id: 'vm-2' }])

    // Хост подставлен автоматически из vmOptions по owner_id (а не хранится отдельным полем).
    await wrapper.setProps({ modelValue: emitted[0][0] as ISSourceDraftRow[] })
    expect(shownValue(wrapper, '.col-device')).toBe('srv-02')
    expect(shownValue(wrapper, '.col-vm')).toBe('app-vm-2')
  })

  it('при ручном выборе устройства (тип "ВМ") сбрасывает owner_id и запоминает хост как фильтр', async () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'vm', owner_id: 'vm-1' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    await pickOption(wrapper, '.col-device', 'srv-02')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ ...emptyRow(), source_type: 'vm', owner_id: '', vmHostHint: 'dev-2' }])
  })

  it('физический сервер, ВМ и контейнер — SearchableSelect, а не нативные select (остаётся только выбор типа)', () => {
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: [emptyRow()] } })

    expect(wrapper.findAll('.source-grid select')).toHaveLength(1)
    expect(wrapper.find('.col-device.searchable-select').exists()).toBe(true)
    expect(wrapper.find('.col-vm.searchable-select').exists()).toBe(true)
    expect(wrapper.find('.col-container.searchable-select').exists()).toBe(true)
  })

  it('активен только тот SearchableSelect, который соответствует типу источника', () => {
    const disabledOf = (type: ISSourceDraftRow['source_type']) => {
      const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: [{ ...emptyRow(), source_type: type }] } })
      const isDisabled = (col: string) => wrapper.find(`${col} input`).attributes('disabled') !== undefined
      return { device: isDisabled('.col-device'), vm: isDisabled('.col-vm'), container: isDisabled('.col-container') }
    }

    expect(disabledOf('manual')).toEqual({ device: true, vm: true, container: true })
    expect(disabledOf('device')).toEqual({ device: false, vm: true, container: true })
    expect(disabledOf('vm')).toEqual({ device: false, vm: false, container: true })
    expect(disabledOf('container')).toEqual({ device: true, vm: true, container: false })
  })

  it('выбор контейнера записывает его id в owner_id', async () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'container' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    await pickOption(wrapper, '.col-container', 'nginx-container')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ ...emptyRow(), source_type: 'container', owner_id: 'ct-1' }])
  })

  it('ВМ выбранного сервера поднимаются наверх списка ВМ, поиск вводом текста фильтрует список', async () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'vm', vmHostHint: 'dev-2' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    const input = wrapper.find('.col-vm input')
    await input.trigger('focus')
    expect(wrapper.findAll('.col-vm .ss-option').map((o) => o.text())).toEqual(['app-vm-2', 'app-vm-1']) // хост dev-2 — его ВМ первой

    await input.setValue('vm-1')
    expect(wrapper.findAll('.col-vm .ss-option').map((o) => o.text())).toEqual(['app-vm-1'])
  })

  it('очистка (крестик) выбранной ВМ сбрасывает owner_id, как выбор пустого пункта в нативном select', async () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'vm', owner_id: 'vm-1' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    await wrapper.find('.col-vm .ss-clear').trigger('mousedown')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ ...emptyRow(), source_type: 'vm', owner_id: '' }])
  })

  it('для типа не "вручную" показывает подсказку вместо списка IP', () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'device' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    expect(wrapper.find('.ip-hint').exists()).toBe(true)
    expect(wrapper.find('.btn-link').exists()).toBe(false)
    expect(wrapper.find('.manual-ips').exists()).toBe(false)
  })

  it('для типа "вручную" показывает кнопку добавления IP, список IP скрыт, пока он пуст', () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'manual' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    expect(wrapper.find('.btn-link').exists()).toBe(true)
    expect(wrapper.find('.ip-hint').exists()).toBe(false)
    expect(wrapper.find('.manual-ips').exists()).toBe(false)
  })

  it('добавляет пустое поле IP по клику на "+ IP-адрес"', async () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'manual' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    await wrapper.find('.btn-link').trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ ...emptyRow(), source_type: 'manual', ips: [{ ip_address: '' }] }])
  })

  it('несколько полей IP редактируются независимо', async () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'manual', ips: [{ ip_address: '10.0.0.1' }, { ip_address: '10.0.0.2' }] }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    const ipInputs = wrapper.findAll('.manual-ip-row input')
    expect(ipInputs).toHaveLength(2)
    await ipInputs[1].setValue('10.0.0.99')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ ...emptyRow(), source_type: 'manual', ips: [{ ip_address: '10.0.0.1' }, { ip_address: '10.0.0.99' }] }])
  })

  it('удаляет одно поле IP из списка, не трогая остальные', async () => {
    const rows: ISSourceDraftRow[] = [
      {
        ...emptyRow(),
        source_type: 'manual',
        ips: [
          { id: 'ip1', ip_address: '10.0.0.1' },
          { id: 'ip2', ip_address: '10.0.0.2' },
        ],
      },
    ]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    await wrapper.findAll('.manual-ip-row .icon-btn.danger')[0].trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([{ ...emptyRow(), source_type: 'manual', ips: [{ id: 'ip2', ip_address: '10.0.0.2' }] }])
  })

  it('удаляет строку по клику на кнопку удаления', async () => {
    const rows: ISSourceDraftRow[] = [
      { ...emptyRow(), id: 's1' },
      { ...emptyRow(), id: 's2', purpose: 'второй' },
    ]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    await wrapper.findAll('.row-actions .icon-btn.danger')[0].trigger('click')

    const emitted = wrapper.emitted('update:modelValue')!
    expect(emitted[0][0]).toEqual([rows[1]])
  })
  // --- Уже добавленные в ИС ВМ и контейнеры не предлагаются для нового размещения ---

  // Подписи опций SearchableSelect конкретной строки (список раскрывается фокусом на поле).
  async function optionLabelsOfRow(wrapper: Wrapper, rowIndex: number, column: '.col-vm' | '.col-container'): Promise<string[]> {
    const card = wrapper.findAll('.source-card')[rowIndex]
    await card.find(`${column} input`).trigger('focus')
    return card.findAll(`${column} .ss-option`).map((o) => o.text())
  }

  it('ВМ, уже выбранная в другой строке, не предлагается в списке ВМ новой строки', async () => {
    const rows: ISSourceDraftRow[] = [
      { ...emptyRow(), source_type: 'vm', owner_id: 'vm-1' },
      { ...emptyRow(), source_type: 'vm' },
    ]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    expect(await optionLabelsOfRow(wrapper, 1, '.col-vm')).toEqual(['app-vm-2'])
  })

  it('собственная ВМ строки остаётся в её списке и отображается в поле, чужая выбранная — скрыта', async () => {
    const rows: ISSourceDraftRow[] = [
      { ...emptyRow(), source_type: 'vm', owner_id: 'vm-1' },
      { ...emptyRow(), source_type: 'vm', owner_id: 'vm-2' },
    ]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    // Подпись читается до раскрытия списков: фокус на поле очищает строку ввода для поиска.
    const cards = wrapper.findAll('.source-card')
    expect((cards[0].find('.col-vm input').element as HTMLInputElement).value).toBe('app-vm-1')
    expect((cards[1].find('.col-vm input').element as HTMLInputElement).value).toBe('app-vm-2')
    expect(await optionLabelsOfRow(wrapper, 0, '.col-vm')).toEqual(['app-vm-1'])
    expect(await optionLabelsOfRow(wrapper, 1, '.col-vm')).toEqual(['app-vm-2'])
  })

  it('контейнер, уже выбранный в другой строке, не предлагается в списке контейнеров новой строки', async () => {
    const twoContainers: Container[] = [...containers, { ...containers[0], id: 'ct-2', name: 'redis-container' }]
    const rows: ISSourceDraftRow[] = [
      { ...emptyRow(), source_type: 'container', owner_id: 'ct-1' },
      { ...emptyRow(), source_type: 'container' },
    ]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, containerOptions: twoContainers, modelValue: rows } })

    expect(await optionLabelsOfRow(wrapper, 1, '.col-container')).toEqual(['redis-container'])
    // Строке с выбранным контейнером доступны её собственный и свободные (но не чужой).
    expect(await optionLabelsOfRow(wrapper, 0, '.col-container')).toEqual(['nginx-container', 'redis-container'])
  })

  it('занятость учитывается только среди строк того же типа: сервер с таким же id не скрывает ВМ', async () => {
    const rows: ISSourceDraftRow[] = [
      { ...emptyRow(), source_type: 'device', owner_id: 'vm-1' },
      { ...emptyRow(), source_type: 'vm' },
    ]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    expect(await optionLabelsOfRow(wrapper, 1, '.col-vm')).toEqual(['app-vm-1', 'app-vm-2'])
  })

  it('после удаления строки её ВМ снова доступна для выбора', async () => {
    const rows: ISSourceDraftRow[] = [
      { ...emptyRow(), source_type: 'vm', owner_id: 'vm-1' },
      { ...emptyRow(), source_type: 'vm' },
    ]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })
    expect(await optionLabelsOfRow(wrapper, 1, '.col-vm')).toEqual(['app-vm-2'])

    await wrapper.setProps({ modelValue: [rows[1]] })

    expect(await optionLabelsOfRow(wrapper, 0, '.col-vm')).toEqual(['app-vm-1', 'app-vm-2'])
  })

  it('старые данные с дублем (одна ВМ в двух строках) не ломаются: каждая строка показывает свою ВМ', async () => {
    const rows: ISSourceDraftRow[] = [
      { ...emptyRow(), id: 's1', source_type: 'vm', owner_id: 'vm-1' },
      { ...emptyRow(), id: 's2', source_type: 'vm', owner_id: 'vm-1' },
    ]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    const cards = wrapper.findAll('.source-card')
    expect((cards[0].find('.col-vm input').element as HTMLInputElement).value).toBe('app-vm-1')
    expect((cards[1].find('.col-vm input').element as HTMLInputElement).value).toBe('app-vm-1')
  })
  // Текст пустого списка. Подпись читается из .ss-empty раскрытого списка конкретной строки.
  async function emptyTextOfRow(wrapper: Wrapper, rowIndex: number, column: '.col-vm' | '.col-container', query = ''): Promise<string> {
    const card = wrapper.findAll('.source-card')[rowIndex]
    const input = card.find(`${column} input`)
    await input.trigger('focus')
    if (query) await input.setValue(query)
    return card.find(`${column} .ss-empty`).text()
  }

  it('если все ВМ уже добавлены, список ВМ новой строки объясняет, почему он пуст', async () => {
    const rows: ISSourceDraftRow[] = [
      { ...emptyRow(), source_type: 'vm', owner_id: 'vm-1' },
      { ...emptyRow(), source_type: 'vm', owner_id: 'vm-2' },
      { ...emptyRow(), source_type: 'vm' },
    ]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    expect(await emptyTextOfRow(wrapper, 2, '.col-vm')).toBe('Все ВМ уже добавлены в эту ИС')
  })

  it('если все контейнеры уже добавлены, список контейнеров новой строки объясняет, почему он пуст', async () => {
    const rows: ISSourceDraftRow[] = [
      { ...emptyRow(), source_type: 'container', owner_id: 'ct-1' },
      { ...emptyRow(), source_type: 'container' },
    ]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    expect(await emptyTextOfRow(wrapper, 1, '.col-container')).toBe('Все контейнеры уже добавлены в эту ИС')
  })

  it('«Ничего не найдено» остаётся для запроса без совпадений, пока свободные ВМ есть', async () => {
    const rows: ISSourceDraftRow[] = [
      { ...emptyRow(), source_type: 'vm', owner_id: 'vm-1' },
      { ...emptyRow(), source_type: 'vm' },
    ]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, modelValue: rows } })

    expect(await emptyTextOfRow(wrapper, 1, '.col-vm', 'нет такой')).toBe('Ничего не найдено')
  })

  it('если ВМ в системе нет вовсе, подсказки «все добавлены» нет — обычное «Ничего не найдено»', async () => {
    const rows: ISSourceDraftRow[] = [{ ...emptyRow(), source_type: 'vm' }]
    const wrapper = mount(ISSourcesListEditor, { props: { ...baseProps, vmOptions: [], modelValue: rows } })

    expect(await emptyTextOfRow(wrapper, 0, '.col-vm')).toBe('Ничего не найдено')
  })
})
