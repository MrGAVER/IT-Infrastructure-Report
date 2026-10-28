import { beforeEach, describe, expect, it } from 'vitest'
import { nextTick, ref } from 'vue'
import type { Connection } from '../../api/types'
import type { ConnectionPrefill } from '../../utils/connectionForm'
import { useConnectionDraft } from '../useConnectionDraft'
import { connection, device, iface, setupConnectionStores } from './connectionFormTestkit'

const interfaces = [iface('if-a', 'dev-1'), iface('if-a2', 'dev-1'), iface('if-b', 'dev-2'), iface('if-c', 'dev-2')]
const devices = [device('dev-2', 'Zeta'), device('dev-1', 'alpha'), device('dev-3', null, 'SN-3')]

function makeDraft(initial: { connection?: Connection | null; prefill?: ConnectionPrefill | null } = {}) {
  const current = ref<Connection | null>(initial.connection ?? null)
  const prefill = ref<ConnectionPrefill | null>(initial.prefill ?? null)
  const draft = useConnectionDraft({ connection: () => current.value, prefill: () => prefill.value })
  return { draft, current, prefill }
}

beforeEach(() => {
  setupConnectionStores({ devices, interfaces })
})

describe('useConnectionDraft — начальное состояние', () => {
  it('создание: пустая форма, isEdit = false', () => {
    const { draft } = makeDraft()
    expect(draft.isEdit.value).toBe(false)
    expect(draft.form.source_interface_id).toBe('')
    expect(draft.form.is_active).toBe(true)
    expect(draft.resolving.value).toBe(false)
    expect(draft.errorMessage.value).toBeNull()
    expect(draft.saving.value).toBe(false)
  })

  it('редактирование: форма из подключения, устройства — по каталогу портов', () => {
    const { draft } = makeDraft({ connection: connection({ description: 'линк' }) })
    expect(draft.isEdit.value).toBe(true)
    expect(draft.form).toMatchObject({ sourceDeviceId: 'dev-1', source_interface_id: 'if-a', destinationDeviceId: 'dev-2', destination_interface_id: 'if-b', description: 'линк' })
  })

  it('подсказка схемы подставляет оба порта при создании', () => {
    const { draft } = makeDraft({ prefill: { sourceInterfaceId: 'if-a', destinationInterfaceId: 'if-c' } })
    expect(draft.form).toMatchObject({ sourceDeviceId: 'dev-1', source_interface_id: 'if-a', destinationDeviceId: 'dev-2', destination_interface_id: 'if-c' })
  })
})

describe('useConnectionDraft — смена редактируемого подключения', () => {
  it('форма перезаполняется, а показанный выбор решения по расхождению сбрасывается', async () => {
    const { draft, current } = makeDraft({ connection: connection() })
    draft.resolving.value = true
    draft.form.description = 'правка'

    current.value = connection({ id: 'c-2', source_interface_id: 'if-a2', destination_interface_id: 'if-c', description: 'другое' })
    await nextTick()

    expect(draft.resolving.value).toBe(false)
    expect(draft.form).toMatchObject({ source_interface_id: 'if-a2', destination_interface_id: 'if-c', description: 'другое' })
  })

  it('переход к созданию очищает форму', async () => {
    const { draft, current } = makeDraft({ connection: connection() })
    current.value = null
    await nextTick()
    expect(draft.form.source_interface_id).toBe('')
    expect(draft.form.connection_type_id).toBe('')
  })
})

describe('useConnectionDraft — выбор портов', () => {
  it('порты стороны — только выбранного устройства', () => {
    const { draft } = makeDraft()
    draft.form.sourceDeviceId = 'dev-2'
    expect(draft.sourcePortOptions.value).toEqual([
      { value: 'if-b', label: 'if-b' },
      { value: 'if-c', label: 'if-c' },
    ])
    expect(draft.destinationPortOptions.value).toEqual([])
  })

  it('порты, занятые активным подключением, не предлагаются; неактивное подключение порт не занимает', () => {
    setupConnectionStores({
      devices,
      interfaces,
      connections: [connection({ id: 'c-x', source_interface_id: 'if-b', destination_interface_id: 'if-a2' }), connection({ id: 'c-y', source_interface_id: 'if-c', destination_interface_id: 'if-a', is_active: false })],
    })
    const { draft } = makeDraft()
    draft.form.destinationDeviceId = 'dev-2'
    expect(draft.destinationPortOptions.value.map((o) => o.value)).toEqual(['if-c'])
  })

  it('при редактировании собственный занятый порт подключения остаётся в списке', () => {
    setupConnectionStores({ devices, interfaces, connections: [connection()] })
    const { draft } = makeDraft({ connection: connection() })
    expect(draft.sourcePortOptions.value.map((o) => o.value)).toEqual(['if-a', 'if-a2'])
    expect(draft.destinationPortOptions.value.map((o) => o.value)).toEqual(['if-b', 'if-c'])
  })

  it('выбранные порты находятся в каталоге интерфейсов', () => {
    const { draft } = makeDraft({ connection: connection() })
    expect(draft.selectedSourceInterface.value?.id).toBe('if-a')
    expect(draft.selectedDestinationInterface.value?.id).toBe('if-b')
  })

  it('выбранный порт, которого нет в каталоге, — null', () => {
    const { draft } = makeDraft({ connection: connection({ source_interface_id: 'if-gone' }) })
    expect(draft.selectedSourceInterface.value).toBeNull()
  })
})

describe('useConnectionDraft — смена устройства', () => {
  it('сбрасывает порт, которого нет у нового устройства', async () => {
    const { draft } = makeDraft({ connection: connection() })
    draft.form.sourceDeviceId = 'dev-2'
    await nextTick()
    expect(draft.form.source_interface_id).toBe('')
    expect(draft.form.destination_interface_id).toBe('if-b')
  })

  it('то же для конечной стороны', async () => {
    const { draft } = makeDraft({ connection: connection() })
    draft.form.destinationDeviceId = 'dev-1'
    await nextTick()
    expect(draft.form.destination_interface_id).toBe('')
    expect(draft.form.source_interface_id).toBe('if-a')
  })

  it('оставляет порт, если он по-прежнему доступен', async () => {
    const { draft } = makeDraft({ connection: connection() })
    draft.form.sourceDeviceId = 'dev-1' // то же устройство — порт на месте
    await nextTick()
    expect(draft.form.source_interface_id).toBe('if-a')
  })
})

describe('useConnectionDraft — подсказки «нет портов»', () => {
  it('у устройства без единого порта — признак «нет портов вообще»', () => {
    const { draft } = makeDraft()
    draft.form.sourceDeviceId = 'dev-3'
    expect(draft.sourceHasNoInterfacesAtAll.value).toBe(true)
    expect(draft.destinationHasNoInterfacesAtAll.value).toBe(false)
  })

  it('устройство не выбрано — признака нет', () => {
    expect(makeDraft().draft.sourceHasNoInterfacesAtAll.value).toBe(false)
  })

  it('все порты заняты — это не «нет портов вообще»', () => {
    setupConnectionStores({
      devices,
      interfaces,
      connections: [connection({ id: 'c-x', source_interface_id: 'if-b', destination_interface_id: 'if-a' }), connection({ id: 'c-y', source_interface_id: 'if-c', destination_interface_id: 'if-a2' })],
    })
    const { draft } = makeDraft()
    draft.form.destinationDeviceId = 'dev-2'
    expect(draft.destinationHasNoInterfacesAtAll.value).toBe(false)
    expect(draft.destinationInterfaces.value).toEqual([])
  })
})

describe('useConnectionDraft — опции и подписи', () => {
  it('устройства отсортированы по подписи; без системного имени — серийный номер', () => {
    const { draft } = makeDraft()
    expect(draft.deviceOptions.value.map((o) => o.label)).toEqual(['alpha', 'SN-3', 'Zeta'])
  })

  it('endpointDeviceLabel: подпись выбранного устройства стороны, пусто — если не выбрано или нет в списке', () => {
    const { draft } = makeDraft({ connection: connection() })
    expect(draft.endpointDeviceLabel('source')).toBe('alpha')
    expect(draft.endpointDeviceLabel('destination')).toBe('Zeta')
    draft.form.destinationDeviceId = 'dev-gone'
    expect(draft.endpointDeviceLabel('destination')).toBe('')
  })
})
