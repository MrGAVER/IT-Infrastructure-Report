import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import type { InterfaceDraftRow } from '../../api/types'
import { makeRow } from '../../utils/__tests__/interfaceRowFixture'
import { portConfigOf } from '../../utils/portConflicts'
import { usePreSaveReview } from '../usePreSaveReview'
import { useToast } from '../useToast'

const fetchAllFreeInterfaces = vi.hoisted(() => vi.fn())
vi.mock('../../api/deviceConnectivity', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/deviceConnectivity')>()),
  fetchAllFreeInterfaces,
}))

const link = {
  peer_device_id: 'dev-2',
  peer_interface_id: 'p1',
  connection_type_id: '',
  description: '',
  peer_device_name: 'sw-02',
  peer_interface_name: 'Gi0/9',
}
const freePort = (patch: Record<string, unknown> = {}) => ({
  id: 'p1',
  name: 'Gi0/9',
  is_management: false,
  is_data_transfer: false,
  vlan_mode: 'access',
  all_vlans: false,
  ...patch,
})

function setup(rows: InterfaceDraftRow[], overrides: { editConnections?: boolean } = {}) {
  const current = ref(rows)
  const applyPeerConfigToPort = vi.fn(async () => {})
  const applyPortConfigToPeer = vi.fn(async () => {})
  const review = usePreSaveReview({
    rows: () => current.value,
    deviceId: () => 'dev-1',
    editConnections: () => overrides.editConnections ?? true,
    connectionBaseline: () => new Map(),
    applyPeerConfigToPort,
    applyPortConfigToPeer,
  })
  return { current, review, applyPeerConfigToPort, applyPortConfigToPeer }
}

describe('usePreSaveReview', () => {
  beforeEach(() => {
    fetchAllFreeInterfaces.mockReset()
    useToast().toasts.splice(0)
  })

  it('без блока «Подключение» проверка пропускается и ничего не запрашивает', async () => {
    const { review } = setup([makeRow({ key: 'k', connection: link })], { editConnections: false })
    expect(await review.reviewNeighborMismatches()).toBe(true)
    expect(fetchAllFreeInterfaces).not.toHaveBeenCalled()
  })

  it('нечего проверять (нет подключений) — сразу true', async () => {
    const { review } = setup([makeRow({ id: 'a' })])
    expect(await review.reviewNeighborMismatches()).toBe(true)
    expect(review.reviewOpen.value).toBe(false)
  })

  it('конфигурации совпали — диалог не открывается', async () => {
    fetchAllFreeInterfaces.mockResolvedValue([freePort()])
    const { review } = setup([makeRow({ key: 'k', connection: link })])
    expect(await review.reviewNeighborMismatches()).toBe(true)
    expect(review.reviewOpen.value).toBe(false)
    expect(fetchAllFreeInterfaces).toHaveBeenCalledWith('dev-2', ['p1'])
  })

  it('расхождение открывает диалог и ждёт решения: «Сохранить как есть» → true, «Вернуться к форме» → false', async () => {
    fetchAllFreeInterfaces.mockResolvedValue([freePort({ is_management: true })])
    const { review } = setup([makeRow({ key: 'k', connection: link })])
    const asIs = review.reviewNeighborMismatches()
    await vi.waitFor(() => expect(review.reviewOpen.value).toBe(true))
    expect(review.reviewItems.value).toHaveLength(1)
    review.finishReview(true)
    expect(await asIs).toBe(true)
    expect(review.reviewOpen.value).toBe(false)
    expect(review.reviewItems.value).toEqual([])

    const back = review.reviewNeighborMismatches()
    await vi.waitFor(() => expect(review.reviewOpen.value).toBe(true))
    review.finishReview(false)
    expect(await back).toBe(false)
  })

  it('пока диалог открыт, повторный вызов не открывает второй и не блокирует сохранение', async () => {
    fetchAllFreeInterfaces.mockResolvedValue([freePort({ is_management: true })])
    const { review } = setup([makeRow({ key: 'k', connection: link })])
    const first = review.reviewNeighborMismatches()
    await vi.waitFor(() => expect(review.reviewOpen.value).toBe(true))
    expect(await review.reviewNeighborMismatches()).toBe(true)
    review.finishReview(false)
    await first
  })

  it('сбой чтения соседей не блокирует сохранение, но показывается уведомлением', async () => {
    fetchAllFreeInterfaces.mockRejectedValue(new Error('сервер недоступен'))
    const { review } = setup([makeRow({ key: 'k', connection: link })])
    expect(await review.reviewNeighborMismatches()).toBe(true)
    expect(review.reviewOpen.value).toBe(false)
    expect(useToast().toasts.at(-1)).toMatchObject({ type: 'error', message: 'сервер недоступен' })
  })

  it('действие из диалога применяется к строке и перечитывает соседей; устранённое расхождение пропадает из списка', async () => {
    fetchAllFreeInterfaces.mockResolvedValue([freePort({ is_management: true })])
    const { current, review, applyPeerConfigToPort } = setup([makeRow({ key: 'k', connection: link })])
    const pending = review.reviewNeighborMismatches()
    await vi.waitFor(() => expect(review.reviewItems.value).toHaveLength(1))
    const [item] = review.reviewItems.value
    applyPeerConfigToPort.mockImplementation(async () => {
      current.value = [{ ...current.value[0], is_management: true }]
    })
    await review.reviewApplyNeighbor(item)
    await nextTick()
    expect(applyPeerConfigToPort).toHaveBeenCalledWith(0, item.peer, ['flags'])
    expect(fetchAllFreeInterfaces).toHaveBeenCalledTimes(2)
    expect(review.reviewItems.value).toEqual([])
    expect(portConfigOf(current.value[0]).is_management).toBe(true)
    review.finishReview(true)
    await pending
  })
})
