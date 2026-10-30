import { beforeEach, describe, expect, it } from 'vitest'
import { nextTick, ref } from 'vue'
import type { InterfaceDraftRow, InterfaceGroupDraft, ProtocolPortCatalogEntry, SubinterfaceDraftRow } from '../../api/types'
import { emptyGroup } from '../../utils/interfaceGroups'
import { makeRow, makeVlan } from '../../utils/__tests__/interfaceRowFixture'
import { useGroupCopy } from '../useGroupCopy'
import { useToast } from '../useToast'

const vlans = [makeVlan('v10', 10), makeVlan('v20', 20)]
const catalog: ProtocolPortCatalogEntry[] = [{ id: 'c22', port: 22, protocol_type: 'SSH', description: null }]

function sub(key: string, vlanId: string, name = ''): SubinterfaceDraftRow {
  return { key, name, vlan_id: vlanId, is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [] }
}

// controlled=true — как в окне группы: черновик приходит пропом и обновляется только после перерисовки родителя, поэтому сразу
// после apply deps.draft() ещё возвращает СТАРЫЙ черновик.
function setup(rows: InterfaceDraftRow[], initial: Partial<InterfaceGroupDraft> = {}, controlled = false) {
  const draft = ref<InterfaceGroupDraft>({ ...emptyGroup('Группа'), key: 'g1', ...initial })
  const applied: InterfaceGroupDraft[] = []
  const copy = useGroupCopy({
    rows: () => rows,
    vlanOptions: () => vlans,
    protocolPortCatalog: () => catalog,
    draft: () => draft.value,
    apply: (group) => {
      applied.push(group)
      if (!controlled) draft.value = group
    },
  })
  return { draft, applied, copy }
}

const rich = () =>
  makeRow({
    name: 'Gi0/1',
    vlan_mode: 'access',
    vlan_ids: ['v10'],
    ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'mgmt' }],
    open_ports: [{ protocol_catalog_id: 'c22', transport_protocol: 'TCP', description: '' }],
  })

const lastToast = () => useToast().toasts.at(-1)

describe('useGroupCopy', () => {
  beforeEach(() => {
    useToast().toasts.splice(0)
  })

  it('варианты порта — имена строк, у безымянной — «#номер»', () => {
    const { copy } = setup([makeRow({ name: 'Gi0/1' }), makeRow({ name: '' })])
    expect(copy.copyPortOptions.value).toEqual([
      { value: '0', label: 'Gi0/1' },
      { value: '1', label: '#2' },
    ])
  })

  it('пока порт не выбран, копировать нечего: параметров нет, копирование недоступно', () => {
    const { copy } = setup([rich()])
    expect(copy.copyRow.value).toBeUndefined()
    expect(copy.copyAvailable.value).toEqual({ vlan: false, ip: false, openPorts: false, subinterfaces: false })
    expect(copy.canCopy.value).toBe(false)
    expect(copy.copyNothingAvailable.value).toBe(false)
  })

  it('выбор порта сразу отмечает всё, что с него можно скопировать, и только это', async () => {
    const { copy } = setup([makeRow({ vlan_ids: ['v10'], ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: '' }] })])
    copy.copySource.value = '0'
    await nextTick()

    expect(copy.copyWhat.value).toEqual({ vlan: true, ip: true, openPorts: false, subinterfaces: false })
    expect(copy.canCopy.value).toBe(true)
  })

  it('порт без значений: copyNothingAvailable, копировать нельзя', async () => {
    const { copy, applied } = setup([makeRow({ vlan_ids: [] })])
    copy.copySource.value = '0'
    await nextTick()

    expect(copy.copyNothingAvailable.value).toBe(true)
    expect(copy.canCopy.value).toBe(false)
    copy.copyFromPort()
    expect(applied).toEqual([])
  })

  it('отметка недоступного параметра не включает копирование: canCopy смотрит и на отметку, и на наличие значения', async () => {
    const { copy } = setup([makeRow({ vlan_ids: ['v10'] })])
    copy.copySource.value = '0'
    await nextTick()

    copy.copyWhat.value = { vlan: false, ip: true, openPorts: false, subinterfaces: false } // IP на порту нет
    expect(copy.canCopy.value).toBe(false)
    copy.copyWhat.value = { vlan: true, ip: false, openPorts: false, subinterfaces: false }
    expect(copy.canCopy.value).toBe(true)
  })

  it('copyFromPort отдаёт новый черновик со значениями порта и сообщает об успехе', async () => {
    const { copy, applied, draft } = setup([rich()])
    copy.copySource.value = '0'
    await nextTick()
    copy.copyFromPort()

    expect(applied).toHaveLength(1)
    expect(draft.value).toMatchObject({
      vlan_mode: 'access',
      vlan_ids: ['v10'],
      ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'mgmt' }],
      manage_open_ports: true,
      open_ports: [{ protocol_catalog_id: 'c22', transport_protocol: 'TCP' }],
    })
    expect(lastToast()).toMatchObject({ type: 'success', message: 'Значения скопированы с порта «Gi0/1».' })
  })

  it('копируются только отмеченные параметры', async () => {
    const { copy, draft } = setup([rich()])
    copy.copySource.value = '0'
    await nextTick()
    copy.copyWhat.value = { vlan: false, ip: true, openPorts: false, subinterfaces: false }
    copy.copyFromPort()

    expect(draft.value).toMatchObject({
      ips: [{ ip_address: '10.0.0.5', prefix_length: '24', purpose: 'mgmt' }],
      vlan_mode: '',
      vlan_ids: [],
      manage_open_ports: false,
      open_ports: [],
    })
  })

  it('после копирования выбор сбрасывается: порт не выбран, отметок нет', async () => {
    const { copy } = setup([rich()])
    copy.copySource.value = '0'
    await nextTick()
    copy.copyFromPort()
    await nextTick()

    expect(copy.copySource.value).toBe('')
    expect(copy.copyWhat.value).toEqual({ vlan: false, ip: false, openPorts: false, subinterfaces: false })
    expect(copy.canCopy.value).toBe(false)
  })

  it('у порта несколько IP-адресов — копируются все, предупреждения нет', async () => {
    const row = makeRow({
      name: 'Gi0/2',
      ips: [
        { ip_address: '10.0.0.1', prefix_length: '24', purpose: '' },
        { ip_address: '10.0.0.2', prefix_length: '24', purpose: '' },
      ],
    })
    const { copy, draft } = setup([row])
    copy.copySource.value = '0'
    await nextTick()
    copy.copyFromPort()

    expect(draft.value.ips.map((ip) => ip.ip_address)).toEqual(['10.0.0.1', '10.0.0.2'])
    expect(lastToast()?.message).toBe('Значения скопированы с порта «Gi0/2».')
  })

  it('у безымянного порта в сообщении его номер', async () => {
    const { copy } = setup([makeRow({ name: '' }), makeRow({ name: '', vlan_ids: ['v10'] })])
    copy.copySource.value = '1'
    await nextTick()
    copy.copyFromPort()

    expect(useToast().toasts[0].message).toBe('Значения скопированы с порта «#2».')
  })

  it('подинтерфейсы на VLAN, которых нет в VLAN группы, — предупреждение, а подходящие всё равно копируются', async () => {
    const row = makeRow({ name: 'Gi0/3', vlan_mode: 'trunk', vlan_ids: ['v10'], subinterfaces: [sub('s1', 'v10'), sub('s2', 'v20', 'Gi0/3.20')] })
    const { copy, draft } = setup([row], { vlan_mode: 'trunk', vlan_ids: ['v10'] })
    copy.copySource.value = '0'
    await nextTick()
    copy.copyWhat.value = { vlan: false, ip: false, openPorts: false, subinterfaces: true }
    copy.copyFromPort()

    expect(draft.value.manage_subinterfaces).toBe(true)
    expect(draft.value.subinterfaces?.map((s) => s.vlan_id)).toEqual(['v10'])
    const toasts = useToast().toasts
    expect(toasts.map((t) => t.type)).toEqual(['success', 'warning'])
    expect(toasts[1].message).toBe('Не скопированы подинтерфейсы на VLAN, которых нет в VLAN группы: «Gi0/3.20».')
  })

  it('ни один подинтерфейс не подошёл группе — список группы не меняется, предупреждение объясняет, что делать', async () => {
    const row = makeRow({ name: 'Gi0/3', subinterfaces: [sub('s1', 'v20')] })
    const { copy, draft } = setup([row], { vlan_mode: 'access', vlan_ids: ['v10'] })
    copy.copySource.value = '0'
    await nextTick()
    copy.copyWhat.value = { vlan: false, ip: false, openPorts: false, subinterfaces: true }
    copy.copyFromPort()

    expect(draft.value.manage_subinterfaces).toBeFalsy()
    expect(draft.value.subinterfaces).toEqual([])
    expect(lastToast()?.type).toBe('warning')
    expect(lastToast()?.message).toContain('Подинтерфейсы не скопированы: их VLAN нет в VLAN группы («без имени»).')
  })

  it('подинтерфейсы, скопированные вместе с VLAN порта, проверяются по НОВОМУ черновику — предупреждения нет', async () => {
    // Исходная группа без режима и VLAN: по старому черновику подинтерфейс на v10 выглядел бы лишним. Черновик «controlled» —
    // как в окне группы, где он обновляется только после перерисовки: deps.draft() сразу после apply ещё старый.
    const row = makeRow({ name: 'Gi0/3', vlan_mode: 'access', vlan_ids: ['v10'], subinterfaces: [sub('s1', 'v10')] })
    const { copy, applied, draft } = setup([row], {}, true)
    copy.copySource.value = '0'
    await nextTick()
    copy.copyFromPort()

    expect(draft.value.vlan_mode).toBe('') // черновик ещё не обновлён родителем
    expect(applied[0]).toMatchObject({ vlan_mode: 'access', vlan_ids: ['v10'], manage_subinterfaces: true })
    expect(applied[0].subinterfaces).toHaveLength(1)
    expect(useToast().toasts.map((t) => t.type)).toEqual(['success'])
  })
})
