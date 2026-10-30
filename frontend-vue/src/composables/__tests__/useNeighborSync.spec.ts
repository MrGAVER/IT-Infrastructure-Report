import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import type { InterfaceDraftRow, PortConflictInfo } from '../../api/types'
import type { PeerConfigTarget } from '../../utils/interfaceConnections'
import { makeConflict, makeRow } from '../../utils/__tests__/interfaceRowFixture'
import { useNeighborSync } from '../useNeighborSync'
import { useToast } from '../useToast'

const updateResource = vi.hoisted(() => vi.fn())
vi.mock('../../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../api/client')>()), updateResource }))

function setup(initial: InterfaceDraftRow[], conflicts: Record<string, PortConflictInfo> = {}) {
  const rows = ref(initial)
  const updateRow = vi.fn((index: number, patch: Partial<InterfaceDraftRow>) => {
    rows.value = rows.value.map((r, i) => (i === index ? { ...r, ...patch } : r))
  })
  const emitNeighborsChanged = vi.fn()
  const sync = useNeighborSync({
    rows: () => rows.value,
    groups: () => [],
    deviceId: () => 'dev-1',
    conflicts: () => conflicts,
    vlanOptions: () => [],
    knownVlans: () => [],
    setRows: (next) => {
      rows.value = next
    },
    setGroups: vi.fn(),
    updateRow,
    setVlanMode: vi.fn(),
    rowManaged: () => ({ vlan: false, ip: false, openPorts: false, subinterfaces: false }),
    groupLockNote: () => '',
    emitNeighborsChanged,
  })
  return { rows, updateRow, emitNeighborsChanged, ...sync }
}

const flagsConflict = makeConflict({ flagsDiffer: true, other: { is_management: true, is_data_transfer: true, vlan_mode: 'trunk', all_vlans: false } })
const remotePeer = (patch: Partial<PeerConfigTarget> = {}): PeerConfigTarget => ({
  ref: 'p1',
  label: '«Gi0/9» (sw-02)',
  config: { is_management: true, is_data_transfer: true, vlan_mode: 'trunk', all_vlans: false },
  interfaceId: 'p1',
  isSelf: false,
  ...patch,
})
const lastToast = () => useToast().toasts.at(-1)

describe('useNeighborSync: окно расхождения', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    updateResource.mockReset()
    updateResource.mockResolvedValue({})
    useToast().toasts.splice(0)
  })

  it('rowConflict берёт расхождение только сохранённого порта', () => {
    const { rowConflict } = setup([makeRow({ id: 'a' }), makeRow()], { a: flagsConflict })
    expect(rowConflict(makeRow({ id: 'a' }))).toBe(flagsConflict)
    expect(rowConflict(makeRow())).toBeUndefined()
    expect(rowConflict(makeRow({ id: 'без-расхождения' }))).toBeUndefined()
  })

  it('openConflict / closeConflict управляют активным окном', () => {
    const { activeConflict, openConflict, closeConflict } = setup([makeRow({ id: 'a' })], { a: flagsConflict })
    openConflict(0, 'flags')
    expect(activeConflict.value).toEqual({ index: 0, kind: 'flags' })
    closeConflict()
    expect(activeConflict.value).toBeNull()
  })

  it('«Применить конфигурацию соседа» по назначению правит только черновик строки и закрывает окно', async () => {
    const { rows, activeConflict, openConflict, applyNeighborConfig } = setup([makeRow({ id: 'a' })], { a: flagsConflict })
    openConflict(0, 'flags')
    await applyNeighborConfig()
    expect(rows.value[0]).toMatchObject({ is_management: true, is_data_transfer: true })
    expect(activeConflict.value).toBeNull()
    expect(updateResource).not.toHaveBeenCalled()
  })

  it('без активного окна и без расхождения у строки действия ничего не делают', async () => {
    const { updateRow, openConflict, applyNeighborConfig, applyCurrentConfigToNeighbor } = setup([makeRow({ id: 'a' })])
    await applyNeighborConfig()
    await applyCurrentConfigToNeighbor()
    openConflict(0, 'flags')
    await applyNeighborConfig()
    await applyCurrentConfigToNeighbor()
    expect(updateRow).not.toHaveBeenCalled()
    expect(updateResource).not.toHaveBeenCalled()
  })

  it('«Применить текущую конфигурацию» по назначению: PUT порта соседа, уведомление, перечитывание соседей', async () => {
    const { activeConflict, peersVersion, emitNeighborsChanged, openConflict, applyCurrentConfigToNeighbor } = setup(
      [makeRow({ id: 'a', is_management: false, is_data_transfer: true })],
      { a: flagsConflict },
    )
    openConflict(0, 'flags')
    await applyCurrentConfigToNeighbor()
    expect(updateResource).toHaveBeenCalledWith('interfaces', 'if-9', { is_management: false, is_data_transfer: true })
    expect(lastToast()).toMatchObject({ type: 'success', message: 'Конфигурация применена к соседнему порту' })
    expect(activeConflict.value).toBeNull()
    expect(peersVersion.value).toBe(1)
    expect(emitNeighborsChanged).toHaveBeenCalledTimes(1)
  })

  it('ошибка записи соседу показывается уведомлением, окно остаётся, кнопки снова доступны', async () => {
    updateResource.mockRejectedValue(new Error('нет прав'))
    const { activeConflict, applyingConflict, peersVersion, openConflict, applyCurrentConfigToNeighbor } = setup([makeRow({ id: 'a' })], { a: flagsConflict })
    openConflict(0, 'flags')
    await applyCurrentConfigToNeighbor()
    expect(lastToast()).toMatchObject({ type: 'error', message: 'нет прав' })
    expect(activeConflict.value).not.toBeNull()
    expect(applyingConflict.value).toBe(false)
    expect(peersVersion.value).toBe(0)
  })
})

describe('useNeighborSync: блок «Подключение»', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    updateResource.mockReset()
    updateResource.mockResolvedValue({})
    useToast().toasts.splice(0)
  })

  it('«Применить конфигурацию соседа» по назначению: правится черновик строки, сообщение просит сохранить форму', async () => {
    const { rows, applyPeerConfigToPort, applyingPeerConfig } = setup([makeRow({ id: 'a', name: 'Gi0/1' })])
    await applyPeerConfigToPort(0, remotePeer(), ['flags'])
    expect(rows.value[0]).toMatchObject({ is_management: true, is_data_transfer: true })
    expect(lastToast()).toMatchObject({ type: 'success', message: 'Порту «Gi0/1» применена конфигурация соседа — сохраните форму' })
    expect(applyingPeerConfig.value).toBe(false)
    expect(updateResource).not.toHaveBeenCalled()
  })

  it('«Применить текущую конфигурацию» порту другого устройства: запрос сразу, соседи перечитываются', async () => {
    const { applyPortConfigToPeer, peersVersion, emitNeighborsChanged } = setup([makeRow({ id: 'a', is_management: true })])
    await applyPortConfigToPeer(0, remotePeer(), ['flags'])
    expect(updateResource).toHaveBeenCalledWith('interfaces', 'p1', { is_management: true, is_data_transfer: false })
    expect(lastToast()?.message).toBe('Назначение порта соседа «Gi0/9» (sw-02) изменено сразу (это порт другого устройства)')
    expect(peersVersion.value).toBe(1)
    expect(emitNeighborsChanged).toHaveBeenCalledTimes(1)
  })

  it('соседний порт этого же устройства правится в черновике, запросов нет', async () => {
    const { rows, applyPortConfigToPeer, emitNeighborsChanged } = setup([makeRow({ id: 'a', is_management: true }), makeRow({ id: 'b', name: 'Gi0/2' })])
    await applyPortConfigToPeer(0, remotePeer({ ref: 'b', label: '«Gi0/2» (это устройство, строка 2)', interfaceId: 'b', isSelf: true }), ['flags'])
    expect(rows.value[1]).toMatchObject({ is_management: true, is_data_transfer: false })
    expect(lastToast()?.message).toContain('применена текущая конфигурация — сохраните форму')
    expect(updateResource).not.toHaveBeenCalled()
    expect(emitNeighborsChanged).not.toHaveBeenCalled()
  })

  it('соседа-строку уже убрали из формы — предупреждение, правок нет', async () => {
    const { updateRow, applyPortConfigToPeer } = setup([makeRow({ id: 'a' })])
    await applyPortConfigToPeer(0, remotePeer({ ref: 'zzz', isSelf: true }), ['flags'])
    expect(lastToast()).toMatchObject({ type: 'warning', message: 'Порт соседа уже убран из формы — выберите соседа заново' })
    expect(updateRow).not.toHaveBeenCalled()
  })

  it('пока идёт одно применение, второе не запускается; после ошибки флаг снимается', async () => {
    let release: () => void = () => {}
    updateResource.mockImplementationOnce(() => new Promise<void>((resolve) => (release = resolve)))
    const { applyPortConfigToPeer, applyingPeerConfig } = setup([makeRow({ id: 'a' })])
    const first = applyPortConfigToPeer(0, remotePeer(), ['flags'])
    await vi.waitFor(() => expect(applyingPeerConfig.value).toBe(true))
    await applyPortConfigToPeer(0, remotePeer(), ['flags'])
    expect(updateResource).toHaveBeenCalledTimes(1)
    release()
    await first
    expect(applyingPeerConfig.value).toBe(false)

    updateResource.mockRejectedValueOnce(new Error('сбой'))
    await applyPortConfigToPeer(0, remotePeer(), ['flags'])
    expect(lastToast()).toMatchObject({ type: 'error', message: 'сбой' })
    expect(applyingPeerConfig.value).toBe(false)
  })
})
