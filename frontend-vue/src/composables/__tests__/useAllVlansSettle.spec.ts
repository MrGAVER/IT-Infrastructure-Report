import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import type { InterfaceDraftRow } from '../../api/types'
import { useVLANsStore } from '../../stores/vlans'
import { makeConflict, makeRow, makeVlan } from '../../utils/__tests__/interfaceRowFixture'
import { useAllVlansSettle, type VlanSideRef } from '../useAllVlansSettle'
import { useToast } from '../useToast'

const loadPortVlanContext = vi.hoisted(() => vi.fn())
const setPortConfig = vi.hoisted(() => vi.fn())
vi.mock('../../api/portVlans', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../api/portVlans')>()), loadPortVlanContext }))
vi.mock('../../api/portConfig', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../api/portConfig')>()), setPortConfig }))

const vlans = [makeVlan('v10', 10), makeVlan('v20', 20)]
const trunk = (patch: Partial<InterfaceDraftRow>) => makeRow({ vlan_mode: 'trunk', ...patch })

function setup(initial: InterfaceDraftRow[], overrides: { locked?: boolean } = {}) {
  const rows = ref(initial)
  const updateRow = vi.fn((index: number, patch: Partial<InterfaceDraftRow>) => {
    rows.value = rows.value.map((r, i) => (i === index ? { ...r, ...patch } : r))
  })
  const onPeerPortWritten = vi.fn()
  const settle = useAllVlansSettle({
    rows: () => rows.value,
    vlanOptions: () => vlans,
    knownVlans: () => vlans,
    updateRow,
    rowManaged: () => ({ vlan: overrides.locked ?? false, ip: false, openPorts: false, subinterfaces: false }),
    groupLockNote: (_row, what) => `${what} задан группой «G».`,
    onPeerPortWritten,
  })
  return { rows, updateRow, onPeerPortWritten, ...settle }
}

const rowSide = (ref: string, label: string): VlanSideRef => ({ kind: 'row', ref, label })
const lastToast = () => useToast().toasts.at(-1)

describe('useAllVlansSettle', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useVLANsStore().$patch({ loaded: true })
    loadPortVlanContext.mockReset()
    setPortConfig.mockReset()
    useToast().toasts.splice(0)
  })

  it('порты формы расходятся по «Все VLAN»: спрашивает значение и записывает выбранное в черновик', async () => {
    const { rows, updateRow, allVlansPrompt, answerAllVlansPrompt, settleAllVlans } = setup([
      trunk({ id: 'a', name: 'Gi0/1', all_vlans: true, vlan_ids: ['v10', 'v20'] }),
      trunk({ id: 'b', name: 'Gi0/2', vlan_ids: ['v10'] }),
    ])
    const done = settleAllVlans(rowSide('a', '«Gi0/1»'), rowSide('b', '«Gi0/2»'))
    await vi.waitFor(() => expect(allVlansPrompt.value).not.toBeNull())
    expect(allVlansPrompt.value).toMatchObject({ portLabel: '«Gi0/2»', sourceLabel: 'порта «Gi0/1»', sourceValue: { allVlans: true } })
    expect(allVlansPrompt.value?.description).toBe('«Все VLAN»: у порта «Gi0/1» стоит, у порта «Gi0/2» не стоит.')
    answerAllVlansPrompt({ allVlans: true, vlanIds: [] })
    await done
    expect(allVlansPrompt.value).toBeNull()
    expect(updateRow).toHaveBeenCalledWith(1, { all_vlans: true, vlan_ids: ['v10', 'v20'] })
    expect(rows.value[1].all_vlans).toBe(true)
    expect(lastToast()).toMatchObject({ type: 'success' })
    expect(lastToast()?.message).toContain('Порту «Gi0/2» установлено: Все VLAN — сохраните форму')
  })

  it('«другое» значение — набор VLAN — переносится в черновик как есть', async () => {
    const { updateRow, allVlansPrompt, answerAllVlansPrompt, settleAllVlans } = setup([trunk({ id: 'a', all_vlans: true }), trunk({ id: 'b' })])
    const done = settleAllVlans(rowSide('a', 'A'), rowSide('b', 'B'))
    await vi.waitFor(() => expect(allVlansPrompt.value).not.toBeNull())
    answerAllVlansPrompt({ allVlans: false, vlanIds: ['v20'] })
    await done
    expect(updateRow).toHaveBeenCalledWith(1, { all_vlans: false, vlan_ids: ['v20'] })
  })

  it('отказ в окне оставляет порт как есть и сообщает, что расхождение осталось', async () => {
    const { updateRow, allVlansPrompt, answerAllVlansPrompt, settleAllVlans } = setup([trunk({ id: 'a', all_vlans: true }), trunk({ id: 'b', name: 'Gi0/2' })])
    const done = settleAllVlans(rowSide('a', 'A'), rowSide('b', '«Gi0/2»'))
    await vi.waitFor(() => expect(allVlansPrompt.value).not.toBeNull())
    answerAllVlansPrompt(null)
    await done
    expect(updateRow).not.toHaveBeenCalled()
    expect(lastToast()).toMatchObject({ type: 'info', message: '«Все VLAN» порта «Gi0/2» не изменено — расхождение осталось' })
  })

  it('порт в access или одинаковый признак — вопроса нет и запросов нет', async () => {
    const access = setup([trunk({ id: 'a', all_vlans: true }), makeRow({ id: 'b', vlan_mode: 'access' })])
    await access.settleAllVlans(rowSide('a', 'A'), rowSide('b', 'B'))
    expect(access.allVlansPrompt.value).toBeNull()
    const same = setup([trunk({ id: 'a', all_vlans: true }), trunk({ id: 'b', all_vlans: true })])
    await same.settleAllVlans(rowSide('a', 'A'), rowSide('b', 'B'))
    expect(same.allVlansPrompt.value).toBeNull()
    expect(loadPortVlanContext).not.toHaveBeenCalled()
  })

  it('набор целевого порта задан группой — предупреждение вместо вопроса', async () => {
    const { allVlansPrompt, updateRow, settleAllVlans } = setup([trunk({ id: 'a', all_vlans: true }), trunk({ id: 'b' })], { locked: true })
    await settleAllVlans(rowSide('a', 'A'), rowSide('b', '«Gi0/2»'))
    expect(allVlansPrompt.value).toBeNull()
    expect(updateRow).not.toHaveBeenCalled()
    expect(lastToast()).toMatchObject({ type: 'warning' })
    expect(lastToast()?.message).toContain('«Все VLAN» порта «Gi0/2» не изменено')
  })

  it('порт другого устройства: состояние читается с сервера, значение пишется сразу, соседи перечитываются', async () => {
    loadPortVlanContext.mockResolvedValue({ mode: 'trunk', allVlans: false, vlanIds: [], options: vlans })
    setPortConfig.mockResolvedValue({ id: 'p1' })
    const { allVlansPrompt, answerAllVlansPrompt, onPeerPortWritten, updateRow, settleAllVlans } = setup([trunk({ id: 'a', all_vlans: true })])
    const done = settleAllVlans(rowSide('a', 'A'), { kind: 'port', interfaceId: 'p1', label: '«Gi0/9» (sw-02)' })
    await vi.waitFor(() => expect(allVlansPrompt.value).not.toBeNull())
    answerAllVlansPrompt({ allVlans: true, vlanIds: [] })
    await done
    expect(setPortConfig).toHaveBeenCalledWith('p1', { all_vlans: true, mode: 'trunk' })
    expect(onPeerPortWritten).toHaveBeenCalledTimes(1)
    expect(updateRow).not.toHaveBeenCalled()
    expect(lastToast()?.message).not.toContain('сохраните форму')
  })

  it('известное состояние порта-источника экономит запросы: одинаковый признак или access — сверка завершается без обращения к серверу', async () => {
    const { settleAllVlans, peerSide, allVlansPrompt } = setup([trunk({ id: 'a', all_vlans: true }), makeRow({ id: 'b', vlan_mode: 'access' })])
    const known = (vlan_mode: 'access' | 'trunk', all_vlans: boolean) =>
      peerSide({
        ref: 'p1',
        label: 'sw-02',
        isSelf: false,
        interfaceId: 'p1',
        config: { is_management: false, is_data_transfer: false, vlan_mode, all_vlans },
      })!
    expect(known('trunk', true)).toMatchObject({ kind: 'port', known: { all_vlans: true } })
    await settleAllVlans(known('trunk', true), rowSide('a', 'A')) // у обоих «Все VLAN»
    await settleAllVlans(known('access', false), rowSide('a', 'A')) // источник в access
    await settleAllVlans(known('trunk', true), rowSide('b', 'B')) // цель в access
    expect(allVlansPrompt.value).toBeNull()
    expect(loadPortVlanContext).not.toHaveBeenCalled()
  })

  it('порт без признака у источника и с признаком у цели расходятся — сервер читается для порта другого устройства', async () => {
    loadPortVlanContext.mockResolvedValue({ mode: 'trunk', allVlans: false, vlanIds: ['v10'], options: vlans })
    useVLANsStore().$patch({ groups: [{ vlan_id: 10, definitions: [vlans[0]] }] }) // номера VLAN порта соседа берутся из справочника
    const { settleAllVlans, peerSide, allVlansPrompt, answerAllVlansPrompt } = setup([trunk({ id: 'a', all_vlans: true })])
    const source = peerSide({
      ref: 'p1',
      label: 'sw-02',
      isSelf: false,
      interfaceId: 'p1',
      config: { is_management: false, is_data_transfer: false, vlan_mode: 'trunk', all_vlans: false },
    })!
    const done = settleAllVlans(source, rowSide('a', 'A'))
    await vi.waitFor(() => expect(allVlansPrompt.value).not.toBeNull())
    expect(loadPortVlanContext).toHaveBeenCalledWith('p1', [vlans[0]])
    expect(allVlansPrompt.value?.sourceValue).toEqual({ allVlans: false, vlanIds: ['v10'] })
    answerAllVlansPrompt(null)
    await done
  })
})

describe('useAllVlansSettle: стороны сверки', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('ownSide и peerSide: строка формы — по ссылке; сосед без id порта — null', () => {
    const { ownSide, peerSide } = setup([makeRow({ id: 'a', name: '  ' })])
    expect(ownSide(makeRow({ id: 'a', name: '  ' }))).toEqual({ kind: 'row', ref: 'a', label: '«без имени»' })
    expect(peerSide({ ref: 'row:k', label: 'L', isSelf: true, config: { is_management: false, is_data_transfer: false, vlan_mode: 'trunk' } })).toEqual({
      kind: 'row',
      ref: 'row:k',
      label: 'L',
    })
    expect(peerSide({ ref: 'row:k', label: 'L', isSelf: false, config: { is_management: false, is_data_transfer: false, vlan_mode: 'trunk' } })).toBeNull()
  })

  it('conflictPeerSide: сосед из этой же формы — строка, иначе порт другого устройства (с известным состоянием, если не fresh)', () => {
    const { conflictPeerSide } = setup([makeRow({ id: 'if-9' })])
    expect(conflictPeerSide(makeConflict({ otherInterfaceId: 'if-9' }))).toMatchObject({ kind: 'row', ref: 'if-9', label: '«Gi0/9» (это устройство)' })
    const remote = makeConflict({ otherInterfaceId: 'if-77', other: { is_management: false, is_data_transfer: false, vlan_mode: 'trunk', all_vlans: true } })
    expect(conflictPeerSide(remote)).toMatchObject({
      kind: 'port',
      interfaceId: 'if-77',
      label: '«Gi0/9» (sw-02)',
      known: { vlan_mode: 'trunk', all_vlans: true },
    })
    expect('known' in conflictPeerSide(remote, true)).toBe(false)
  })
})
