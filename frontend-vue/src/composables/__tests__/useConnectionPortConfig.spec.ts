import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import { flushPromises } from '@vue/test-utils'
import type { DeviceInterface, PortConfigPreview } from '../../api/types'
import { previewPortConfig } from '../../api/portConfig'
import { useConnectionPortConfig } from '../useConnectionPortConfig'
import { iface, preview, previewSide } from './connectionFormTestkit'

vi.mock('../../api/portConfig', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../api/portConfig')>()), previewPortConfig: vi.fn() }))
const previewMock = vi.mocked(previewPortConfig)

const a = iface('if-a', 'dev-1', { is_management: true })
const b = iface('if-b', 'dev-2', { is_data_transfer: true })

function setup(initial: { source?: DeviceInterface | null; destination?: DeviceInterface | null; connectionId?: string; isActive?: boolean } = {}) {
  const source = ref<DeviceInterface | null>(initial.source ?? null)
  const destination = ref<DeviceInterface | null>(initial.destination ?? null)
  const connectionId = ref<string | undefined>(initial.connectionId)
  const isActive = ref(initial.isActive ?? true)
  const config = useConnectionPortConfig({ source: () => source.value, destination: () => destination.value, connectionId: () => connectionId.value, isActive: () => isActive.value })
  return { config, source, destination, connectionId, isActive }
}

const mismatchPreview = () => preview(previewSide('if-a', { role: 'management', mode: 'trunk' }), previewSide('if-b', { role: 'data', mode: 'access' }), 'mismatch', ['role', 'mode'])

beforeEach(() => {
  previewMock.mockReset()
  previewMock.mockResolvedValue(preview(previewSide('if-a'), previewSide('if-b')))
})

describe('useConnectionPortConfig — запрос сверки', () => {
  it('пара не выбрана: запроса нет, вида сверки нет', async () => {
    const { config } = setup()
    await config.settle()
    expect(previewMock).not.toHaveBeenCalled()
    expect(config.configView.value).toBeNull()
    expect(config.needsResolution.value).toBe(false)
  })

  it('выбор пары запрашивает сверку с id подключения и признаком активности', async () => {
    const { config } = setup({ source: a, destination: b, connectionId: 'c-7', isActive: false })
    await config.settle()
    expect(previewMock).toHaveBeenCalledTimes(1)
    expect(previewMock).toHaveBeenCalledWith({ source_interface_id: 'if-a', destination_interface_id: 'if-b', connection_id: 'c-7', is_active: false })
  })

  it('новое подключение: connection_id не передаётся', async () => {
    const { config } = setup({ source: a, destination: b })
    await config.settle()
    expect(previewMock.mock.calls[0][0].connection_id).toBeUndefined()
  })

  it('смена активности перезапрашивает сверку', async () => {
    const { isActive, config } = setup({ source: a, destination: b })
    await config.settle()
    isActive.value = false
    await nextTick()
    await config.settle()
    expect(previewMock).toHaveBeenCalledTimes(2)
    expect(previewMock.mock.calls[1][0].is_active).toBe(false)
  })

  it('смена роли или режима порта (после «Управлять портами» или выравнивания) перезапрашивает сверку', async () => {
    const { source, config } = setup({ source: a, destination: b })
    await config.settle()
    source.value = iface('if-a', 'dev-1', { is_management: true, is_data_transfer: true })
    await nextTick()
    source.value = iface('if-a', 'dev-1', { is_management: true, is_data_transfer: true, vlan_mode: 'trunk' })
    await nextTick()
    await config.settle()
    expect(previewMock).toHaveBeenCalledTimes(3)
  })

  it('смена несущественных полей порта (описание) сверку не перезапрашивает', async () => {
    const { source, config } = setup({ source: a, destination: b })
    await config.settle()
    source.value = iface('if-a', 'dev-1', { is_management: true, description: 'новое' })
    await nextTick()
    await config.settle()
    expect(previewMock).toHaveBeenCalledTimes(1)
  })

  it('снятие выбора порта сбрасывает ответ сервера', async () => {
    previewMock.mockResolvedValue(mismatchPreview())
    const { source, config } = setup({ source: a, destination: b })
    await config.settle()
    expect(config.preview.value).not.toBeNull()
    source.value = null
    await nextTick()
    await config.settle()
    expect(config.preview.value).toBeNull()
    expect(config.configView.value).toBeNull()
  })
})

describe('useConnectionPortConfig — расхождение', () => {
  it('расхождение по ответу сервера требует решения', async () => {
    previewMock.mockResolvedValue(mismatchPreview())
    const { config } = setup({ source: a, destination: b })
    await config.settle()
    expect(config.portMismatch.value?.diff).toEqual(['role', 'mode'])
    expect(config.mismatchAlreadyApproved.value).toBe(false)
    expect(config.needsResolution.value).toBe(true)
  })

  it('ранее одобренное расхождение остаётся в виде, но решения не требует', async () => {
    previewMock.mockResolvedValue(preview(previewSide('if-a'), previewSide('if-b', { mode: 'trunk' }), 'approved', ['mode']))
    const { config } = setup({ source: a, destination: b })
    await config.settle()
    expect(config.portMismatch.value).not.toBeNull()
    expect(config.mismatchAlreadyApproved.value).toBe(true)
    expect(config.needsResolution.value).toBe(false)
  })

  it('статус ok — расхождения нет', async () => {
    const { config } = setup({ source: a, destination: b })
    await config.settle()
    expect(config.portMismatch.value).toBeNull()
    expect(config.needsResolution.value).toBe(false)
  })
})

describe('useConnectionPortConfig — сбой и устаревшие ответы', () => {
  it('запрос не удался: сверка ролей по каталогу, режим и VLAN неизвестны', async () => {
    previewMock.mockRejectedValue(new Error('сеть'))
    const { config } = setup({ source: a, destination: b })
    await config.settle()
    expect(config.preview.value).toBeNull()
    expect(config.portMismatch.value?.diff).toEqual(['role'])
    expect(config.configView.value?.source.mode).toBeNull()
    expect(config.needsResolution.value).toBe(true)
  })

  it('ответ без одной из сторон приравнивается к неудаче', async () => {
    previewMock.mockResolvedValue({ status: 'ok', diff: [] } as unknown as PortConfigPreview)
    const { config } = setup({ source: a, destination: b })
    await config.settle()
    expect(config.preview.value).toBeNull()
    expect(config.portMismatch.value?.diff).toEqual(['role'])
  })

  it('пустой ответ (null) приравнивается к неудаче', async () => {
    previewMock.mockResolvedValue(null as unknown as PortConfigPreview)
    const { config } = setup({ source: a, destination: b })
    await config.settle()
    expect(config.preview.value).toBeNull()
  })

  it('поздний ответ на устаревший запрос не затирает свежий', async () => {
    let resolveFirst!: (p: PortConfigPreview) => void
    previewMock.mockReturnValueOnce(new Promise<PortConfigPreview>((r) => (resolveFirst = r)))
    const { config } = setup({ source: a, destination: b })
    const first = config.settle()
    previewMock.mockResolvedValueOnce(mismatchPreview())
    const second = config.refresh()
    await second
    expect(config.preview.value?.status).toBe('mismatch')

    resolveFirst(preview(previewSide('if-a'), previewSide('if-b')))
    await first
    expect(config.preview.value?.status).toBe('mismatch')
  })

  it('поздний сбой устаревшего запроса не сбрасывает свежий ответ', async () => {
    let rejectFirst!: (e: Error) => void
    previewMock.mockReturnValueOnce(new Promise<PortConfigPreview>((_, rej) => (rejectFirst = rej)))
    const { config } = setup({ source: a, destination: b })
    const first = config.settle()
    previewMock.mockResolvedValueOnce(mismatchPreview())
    await config.refresh()
    rejectFirst(new Error('поздно'))
    await first
    expect(config.preview.value?.status).toBe('mismatch')
  })
})

describe('useConnectionPortConfig — refresh и settle', () => {
  it('refresh перезапрашивает сверку, settle дожидается последнего запроса', async () => {
    const { config } = setup({ source: a, destination: b })
    await config.settle()
    previewMock.mockResolvedValueOnce(mismatchPreview())
    const refreshing = config.refresh()
    await flushPromises()
    await refreshing
    await config.settle()
    expect(previewMock).toHaveBeenCalledTimes(2)
    expect(config.preview.value?.status).toBe('mismatch')
  })

  it('settle без запросов завершается сразу', async () => {
    const { config } = setup()
    await expect(config.settle()).resolves.toBeUndefined()
  })
})
