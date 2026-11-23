import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'
import type { DeviceInterfaceConnection } from '../../api/deviceConnectivity'
import type { Device, VLANDefinition } from '../../api/types'
import { useCatalogsStore } from '../../stores/catalogs'
import { useConnectionsStore } from '../../stores/connections'
import { makeRow } from '../../utils/__tests__/interfaceRowFixture'
import { deviceOf, makeDraft, setVlanDefinitions, setupStores, vlanDef } from './deviceFormTestkit'
import { usePortSyncPlanRequest } from '../usePortSyncPlanRequest'
import { useStaleRecordConflict, type StaleRecordChoice } from '../useStaleRecordConflict'
import { useToast } from '../useToast'
import { useDeviceSave, type DeviceSaveDeps } from '../useDeviceSave'
import type { DeviceDomains } from '../useDeviceDomains'

const calls: string[] = []
const createResource = vi.fn()
const updateResource = vi.fn()
const getResource = vi.fn()
const syncDeviceDeployedSoftware = vi.fn()
const persistDeviceVlans = vi.fn()
const persistDeviceInterfaces = vi.fn()
const fetchDeviceInterfaceConnections = vi.fn()
const findPortSyncNotice = vi.fn()

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  createResource: (...args: unknown[]) => createResource(...args),
  updateResource: (...args: unknown[]) => updateResource(...args),
  getResource: (...args: unknown[]) => getResource(...args),
}))
vi.mock('../../api/deviceDeployedSoftware', () => ({ syncDeviceDeployedSoftware: (...args: unknown[]) => syncDeviceDeployedSoftware(...args) }))
vi.mock('../../api/deviceVlans', () => ({ persistDeviceVlans: (...args: unknown[]) => persistDeviceVlans(...args) }))
vi.mock('../../api/deviceInterfaces', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/deviceInterfaces')>()),
  persistDeviceInterfaces: (...args: unknown[]) => persistDeviceInterfaces(...args),
}))
vi.mock('../../api/deviceConnectivity', () => ({ fetchDeviceInterfaceConnections: (...args: unknown[]) => fetchDeviceInterfaceConnections(...args) }))
vi.mock('../../utils/portSyncNotice', () => ({ findPortSyncNotice: (...args: unknown[]) => findPortSyncNotice(...args) }))

const { ApiError, ErrorCode } = await import('../../api/client')

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))
const savedDevice = { id: 'dev-new', serial_number: 'SN-1' } as Device
const toasts = () => useToast().toasts

let stores: ReturnType<typeof setupStores>
let confirmMock: ReturnType<typeof vi.fn>

function setup(device: Device | null = null, overrides: Partial<DeviceSaveDeps> = {}) {
  const draft = makeDraft(device)
  draft.form.device_type_id = 't-sw'
  draft.form.serial_number = 'SN-1'
  const domains = {
    persistPendingDomainMemberships: vi.fn(async () => void calls.push('domain-members')),
    persistPendingSourceDomains: vi.fn(async () => void calls.push('source-domains')),
  }
  const portVlanOptions = ref<VLANDefinition[]>([])
  const deps: DeviceSaveDeps = {
    device: () => device,
    readOnly: ref(false),
    domains: domains as unknown as DeviceDomains,
    portVlanOptions: computed(() => portVlanOptions.value),
    reviewNeighbors: vi.fn(() => undefined),
    expandVlanEditor: vi.fn(),
    onSaved: vi.fn(),
    close: vi.fn(),
    ...overrides,
  }
  return { draft, domains, deps, save: useDeviceSave(draft, deps), portVlanOptions }
}

beforeEach(() => {
  vi.clearAllMocks()
  calls.length = 0
  stores = setupStores()
  setVlanDefinitions(stores.vlans, [vlanDef('v10', 10), vlanDef('v20', 20)])
  toasts().splice(0)
  usePortSyncPlanRequest().close()

  createResource.mockImplementation(async (_resource: string, payload: Record<string, unknown>) => {
    calls.push('create')
    return { ...savedDevice, ...payload, id: 'dev-new' }
  })
  updateResource.mockImplementation(async (_resource: string, id: string) => {
    calls.push('update')
    return { ...savedDevice, id }
  })
  getResource.mockImplementation(async (_resource: string, id: string) => ({ id }))
  syncDeviceDeployedSoftware.mockImplementation(async () => void calls.push('software'))
  persistDeviceVlans.mockImplementation(async () => void calls.push('vlans'))
  persistDeviceInterfaces.mockImplementation(async () => {
    calls.push('interfaces')
    return { items: [{ id: 'if-saved', name: 'Gi0/1' }], groups: [] }
  })
  fetchDeviceInterfaceConnections.mockResolvedValue([])
  findPortSyncNotice.mockResolvedValue(null)
  confirmMock = vi.fn(() => true)
  vi.stubGlobal('confirm', confirmMock)
  vi.spyOn(useCatalogsStore(), 'replaceDeviceInterfaces').mockImplementation(() => undefined)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('отказ до отправки', () => {
  it('роль без права записи: ничего не происходит', async () => {
    const { save } = setup(null, { readOnly: ref(true) })
    await save.submit()
    expect(createResource).not.toHaveBeenCalled()
    expect(save.saving.value).toBe(false)
  })

  it('ошибка валидации показывается в форме, запросов нет', async () => {
    const { draft, save, deps } = setup()
    draft.form.serial_number = ' '
    await save.submit()
    expect(draft.errorMessage.value).toBe('Укажите серийный номер.')
    expect(createResource).not.toHaveBeenCalled()
    expect(deps.expandVlanEditor).not.toHaveBeenCalled()
    expect(save.saving.value).toBe(false)
  })

  it('ошибка в строке «VLAN устройства» раскрывает блок', async () => {
    const { draft, save, deps } = setup()
    draft.deviceVlans.value = [{ vlan_id: 'v10', ip_address: '999.1.1.1', prefix_length: '', is_management: false, description: '' }]
    await save.submit()
    expect(draft.errorMessage.value).toContain('999.1.1.1')
    expect(deps.expandVlanEditor).toHaveBeenCalledTimes(1)
  })

  it('прошлая ошибка очищается при новой попытке', async () => {
    const { draft, save } = setup()
    draft.errorMessage.value = 'старая'
    await save.submit()
    expect(draft.errorMessage.value).toBeNull()
  })

  it('допустимые VLAN для проверки берутся из portVlanOptions: подинтерфейс на недоступном VLAN не уходит на сервер', async () => {
    const { draft, save } = setup()
    const sub = { key: 's1', name: 'Gi0/1.10', vlan_id: 'v10', is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [] }
    draft.interfaces.value = [makeRow({ name: 'Gi0/1', vlan_mode: 'trunk', vlan_ids: ['v10'], subinterfaces: [sub] })]
    await save.submit()
    expect(draft.errorMessage.value).toContain('не назначен устройству')
    expect(createResource).not.toHaveBeenCalled()
  })
})

describe('допустимые VLAN порта при проверке', () => {
  it('подинтерфейс на VLAN, допустимом устройству (portVlanOptions), проходит проверку и сохраняется', async () => {
    const { draft, save, portVlanOptions, deps } = setup()
    portVlanOptions.value = [vlanDef('v10', 10)]
    const sub = { key: 's1', name: 'Gi0/1.10', vlan_id: 'v10', is_management: false, is_data_transfer: false, description: '', ips: [], open_ports: [] }
    draft.interfaces.value = [makeRow({ name: 'Gi0/1', vlan_mode: 'trunk', vlan_ids: ['v10'], subinterfaces: [sub] })]
    await save.submit()
    expect(draft.errorMessage.value).toBeNull()
    expect(deps.onSaved).toHaveBeenCalledTimes(1)
  })
})

describe('создание', () => {
  it('создаёт устройство, пишет вложенные данные строго по порядку и сообщает о сохранении', async () => {
    const { draft, save, deps } = setup()
    draft.softwareAssets.value = [{ software_asset_id: 'sa-1', version: '' }]
    await save.submit()

    expect(calls).toEqual(['create', 'software', 'domain-members', 'source-domains', 'vlans', 'interfaces'])
    expect(createResource).toHaveBeenCalledWith('devices', expect.objectContaining({ device_type_id: 't-sw', serial_number: 'SN-1', system_name: null }))
    expect(deps.onSaved).toHaveBeenCalledTimes(1)
    expect((deps.onSaved as ReturnType<typeof vi.fn>).mock.calls[0][0].id).toBe('dev-new')
    expect(draft.errorMessage.value).toBeNull()
    expect(save.saving.value).toBe(false)
  })

  it('новому устройству без заполненных строк ПО синхронизировать нечего', async () => {
    const { draft, save } = setup()
    draft.softwareAssets.value = [{ software_asset_id: '', version: '' }]
    await save.submit()
    expect(syncDeviceDeployedSoftware).not.toHaveBeenCalled()
  })

  it('порты, группы и снимок подключений уходят в persistDeviceInterfaces, кэш каталога обновляется ответом сервера', async () => {
    const { draft, save } = setup()
    draft.interfaces.value = [makeRow({ name: 'Gi0/1' })]
    await save.submit()

    expect(persistDeviceInterfaces).toHaveBeenCalledTimes(1)
    const [id, rows, groups, baseline] = persistDeviceInterfaces.mock.calls[0]
    expect(id).toBe('dev-new')
    expect(rows.map((r: { name: string }) => r.name)).toEqual(['Gi0/1'])
    expect(groups).toEqual([])
    expect(baseline).toBe(draft.initialConnections.value)
    expect(useCatalogsStore().replaceDeviceInterfaces).toHaveBeenCalledWith('dev-new', [{ id: 'if-saved', name: 'Gi0/1' }])
  })

  it('стор VLAN перечитывается всегда, стор доменов — только если были отложенные домены', async () => {
    const first = setup()
    await first.save.submit()
    expect(stores.spies.vlansReload).toHaveBeenCalledTimes(1)
    expect(stores.spies.domainsReload).not.toHaveBeenCalled()

    const second = setup()
    second.draft.pendingDomainMemberships.value = new Set(['dom-1'])
    await second.save.submit()
    expect(stores.spies.domainsReload).toHaveBeenCalledTimes(1)

    const third = setup()
    third.draft.pendingSourceDomainIds.value = new Set(['dom-2'])
    await third.save.submit()
    expect(stores.spies.domainsReload).toHaveBeenCalledTimes(2)
  })

  it('во время записи saving = true', async () => {
    let release: () => void = () => undefined
    createResource.mockImplementation(() => new Promise((resolve) => (release = () => resolve(savedDevice))))
    const { save } = setup()
    const pending = save.submit()
    expect(save.saving.value).toBe(true)
    release()
    await pending
    expect(save.saving.value).toBe(false)
  })
})

describe('редактирование', () => {
  it('обновляет устройство (PUT), а не создаёт; пустой список ПО отправляется, чтобы снять убранное', async () => {
    const { save } = setup(deviceOf({ id: 'dev-1' }))
    await save.submit()
    expect(updateResource).toHaveBeenCalledWith('devices', 'dev-1', expect.objectContaining({ serial_number: 'SN-1' }))
    expect(createResource).not.toHaveBeenCalled()
    expect(syncDeviceDeployedSoftware).toHaveBeenCalledWith('dev-1', [])
    expect(calls[0]).toBe('update')
  })

  it('об изменении набора VLAN устройства предлагается проверить согласование портов; без изменения — не проверяется', async () => {
    const unchanged = setup(deviceOf({ id: 'dev-1' }))
    await unchanged.save.submit()
    await settle()
    expect(findPortSyncNotice).not.toHaveBeenCalled()

    const changed = setup(deviceOf({ id: 'dev-1' }))
    changed.draft.snapshot.deviceVlanKey = 'v10'
    changed.draft.deviceVlans.value = [{ vlan_id: 'v20', ip_address: '', prefix_length: '', is_management: false, description: '' }]
    await changed.save.submit()
    await settle()
    expect(findPortSyncNotice).toHaveBeenCalledWith('dev-1')
  })

  it('найдено, что согласовать: предупреждение живёт 30 с и открывает план по подключениям', async () => {
    findPortSyncNotice.mockResolvedValue({ message: 'Согласуйте порты', connectionIds: ['c-1'] })
    const { draft, save } = setup(deviceOf({ id: 'dev-1' }))
    draft.snapshot.deviceVlanKey = 'v10'
    await save.submit()
    await settle()

    const toast = toasts().find((t) => t.message === 'Согласуйте порты')
    expect(toast?.type).toBe('warning')
    toast!.action!.run()
    expect(usePortSyncPlanRequest().request.value).toEqual({ scope: { connection_ids: ['c-1'] }, title: 'Согласование портов после изменения VLAN устройства' })
  })

  it('предупреждение о согласовании портов живёт дольше обычного (30 с): по нему нужно решение', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      findPortSyncNotice.mockResolvedValue({ message: 'Согласуйте порты', connectionIds: ['c-1'] })
      const { draft, save } = setup(deviceOf({ id: 'dev-1' }))
      draft.snapshot.deviceVlanKey = 'v10'
      await save.submit()
      await vi.advanceTimersByTimeAsync(0)
      expect(toasts().some((t) => t.message === 'Согласуйте порты')).toBe(true)

      await vi.advanceTimersByTimeAsync(15000)
      expect(toasts().some((t) => t.message === 'Согласуйте порты')).toBe(true)
      await vi.advanceTimersByTimeAsync(15001)
      expect(toasts().some((t) => t.message === 'Согласуйте порты')).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it('слишком много подключений (ids пуст): план открывается без ограничения подключениями', async () => {
    findPortSyncNotice.mockResolvedValue({ message: 'Много подключений', connectionIds: [] })
    const { draft, save } = setup(deviceOf({ id: 'dev-1' }))
    draft.snapshot.deviceVlanKey = 'v10'
    await save.submit()
    await settle()
    toasts()
      .find((t) => t.message === 'Много подключений')!
      .action!.run()
    expect(usePortSyncPlanRequest().request.value?.scope).toEqual({})
  })

  it('сбой проверки согласования не отменяет сохранение: отдельное предупреждение с причиной', async () => {
    findPortSyncNotice.mockRejectedValue(new Error('сервер занят'))
    const { draft, save, deps } = setup(deviceOf({ id: 'dev-1' }))
    draft.snapshot.deviceVlanKey = 'v10'
    await save.submit()
    await settle()
    expect(deps.onSaved).toHaveBeenCalledTimes(1)
    expect(draft.errorMessage.value).toBeNull()
    expect(toasts().map((t) => [t.type, t.message])).toContainEqual([
      'warning',
      'Устройство сохранено, но проверить, нужно ли согласование портов, не удалось: сервер занят',
    ])
  })

  it('у нового устройства согласование портов не проверяется', async () => {
    const { draft, save } = setup()
    draft.deviceVlans.value = [{ vlan_id: 'v10', ip_address: '', prefix_length: '', is_management: false, description: '' }]
    await save.submit()
    await settle()
    expect(findPortSyncNotice).not.toHaveBeenCalled()
  })
})

// Пункт 3 предложений по улучшению (ревью merge/review-f06-stage2-f05-executors): ПО, VLAN и порты уходят на сервер PUT-ом ЦЕЛИКОМ,
// поэтому пустой черновик из-за незагруженных данных нельзя отправлять — он стёр бы их у устройства.
describe('вложенные данные не загрузились или ещё грузятся', () => {
  it('сбой загрузки: сохраняются основные поля, а ПО, VLAN и порты на сервер не отправляются', async () => {
    const { draft, save, deps } = setup(deviceOf({ id: 'dev-1' }))
    draft.nestedLoadFailed.value = true

    await save.submit()

    expect(updateResource).toHaveBeenCalledWith('devices', 'dev-1', expect.objectContaining({ serial_number: 'SN-1' }))
    expect(syncDeviceDeployedSoftware).not.toHaveBeenCalled()
    expect(persistDeviceVlans).not.toHaveBeenCalled()
    expect(persistDeviceInterfaces).not.toHaveBeenCalled()
    expect(deps.onSaved).toHaveBeenCalledTimes(1)
  })

  it('сбой загрузки: изменение набора VLAN не считается произошедшим — проверка согласования портов не запускается', async () => {
    const { draft, save } = setup(deviceOf({ id: 'dev-1' }))
    draft.nestedLoadFailed.value = true
    draft.deviceVlans.value = [{ vlan_id: 'v10', ip_address: '', prefix_length: '', is_management: false, description: '' }]

    await save.submit()
    await settle()

    expect(findPortSyncNotice).not.toHaveBeenCalled()
  })

  it('данные ещё грузятся: отправка формы ничего не пишет на сервер', async () => {
    const { draft, save } = setup(deviceOf({ id: 'dev-1' }))
    draft.loadingNested.value = true

    await save.submit()

    expect(updateResource).not.toHaveBeenCalled()
    expect(syncDeviceDeployedSoftware).not.toHaveBeenCalled()
    expect(persistDeviceVlans).not.toHaveBeenCalled()
    expect(persistDeviceInterfaces).not.toHaveBeenCalled()
  })

  it('данные загружены: прежний порядок и состав записи (ПО, VLAN, порты) не изменились', async () => {
    const { save } = setup(deviceOf({ id: 'dev-1' }))
    await save.submit()
    expect(calls).toEqual(['update', 'software', 'domain-members', 'source-domains', 'vlans', 'interfaces'])
  })
})

describe('сбой после создания устройства', () => {
  it('устройство уже в БД: форма говорит об этом, список устройств перечитывается, форма не закрывается', async () => {
    persistDeviceVlans.mockRejectedValue(new Error('VLAN не разрешён.'))
    const { draft, save, deps } = setup()
    await save.submit()

    expect(draft.errorMessage.value).toMatch(/^Устройство создано, но остальные данные сохранить не удалось: VLAN не разрешён\. Исправьте данные/)
    expect(draft.errorMessage.value).not.toContain('VLAN не разрешён..')
    expect(draft.createdDevice.value?.id).toBe('dev-new')
    expect(stores.spies.devicesReload).toHaveBeenCalledTimes(1)
    expect(deps.onSaved).not.toHaveBeenCalled()
    expect(save.saving.value).toBe(false)
  })

  it('повторное «Сохранить» обновляет созданное устройство, а не создаёт дубль; ПО синхронизируется как для существующего', async () => {
    persistDeviceVlans.mockRejectedValueOnce(new Error('сбой'))
    const { save, deps } = setup()
    await save.submit()
    expect(createResource).toHaveBeenCalledTimes(1)

    await save.submit()
    expect(createResource).toHaveBeenCalledTimes(1)
    expect(updateResource).toHaveBeenCalledWith('devices', 'dev-new', expect.anything())
    expect(syncDeviceDeployedSoftware).toHaveBeenCalledWith('dev-new', [])
    expect(deps.onSaved).toHaveBeenCalledTimes(1)
  })

  it('сбой самого создания: «устройство создано» не говорится, список не перечитывается', async () => {
    createResource.mockRejectedValue(new Error('Серийный номер занят'))
    const { draft, save } = setup()
    await save.submit()
    expect(draft.errorMessage.value).toBe('Серийный номер занят')
    expect(draft.createdDevice.value).toBeNull()
    expect(stores.spies.devicesReload).not.toHaveBeenCalled()
  })

  it('сбой при редактировании: показывается причина как есть, список не перечитывается', async () => {
    persistDeviceInterfaces.mockRejectedValue(new Error('порт занят'))
    const { draft, save } = setup(deviceOf({ id: 'dev-1' }))
    await save.submit()
    expect(draft.errorMessage.value).toBe('порт занят')
    expect(stores.spies.devicesReload).not.toHaveBeenCalled()
  })

  it('не-Error в отказе заменяется сообщением по умолчанию', async () => {
    updateResource.mockRejectedValue('boom')
    const { draft, save } = setup(deviceOf({ id: 'dev-1' }))
    await save.submit()
    expect(draft.errorMessage.value).toBe('Не удалось сохранить устройство')
  })
})

describe('конфликт версий записи (409 STALE_RECORD)', () => {
  const OPENED = '2026-11-01T10:00:00.000Z'
  const UPDATED = '2026-11-01T10:05:00.000Z'
  const REFRESHED = '2026-11-01T10:07:00.000Z'

  /** Отвечает на вопрос о конфликте так, как это сделало бы окно StaleRecordHost. */
  async function answer(choice: StaleRecordChoice) {
    await settle()
    expect(useStaleRecordConflict().question.value).not.toBeNull()
    useStaleRecordConflict().resolve(choice)
  }

  beforeEach(() => {
    useStaleRecordConflict().resolve('stay')
    updateResource.mockImplementationOnce(async () => {
      throw new ApiError(409, 'Запись изменена другим пользователем', ErrorCode.STALE_RECORD)
    })
  })

  it('updated_at устройства, с которым открыта форма, уходит серверу четвёртым аргументом', async () => {
    updateResource.mockReset()
    updateResource.mockResolvedValue({ ...savedDevice, id: 'dev-1', updated_at: UPDATED })
    const { save } = setup(deviceOf({ id: 'dev-1', updated_at: OPENED }))
    await save.submit()
    expect(updateResource).toHaveBeenCalledWith('devices', 'dev-1', expect.objectContaining({ serial_number: 'SN-1' }), OPENED)
  })

  it('«Остаться в форме»: ничего не пишется, форма не закрывается, ошибки нет', async () => {
    const { draft, save, deps } = setup(deviceOf({ id: 'dev-1', updated_at: OPENED }))
    await Promise.all([save.submit(), answer('stay')])

    expect(updateResource).toHaveBeenCalledTimes(1)
    expect(syncDeviceDeployedSoftware).not.toHaveBeenCalled()
    expect(persistDeviceInterfaces).not.toHaveBeenCalled()
    expect(deps.onSaved).not.toHaveBeenCalled()
    expect(deps.close).not.toHaveBeenCalled()
    expect(draft.errorMessage.value).toBeNull()
    expect(save.saving.value).toBe(false)
  })

  it('«Сохранить мои изменения»: запись отправляется повторно без токена и сохранение доходит до конца', async () => {
    const { save, deps } = setup(deviceOf({ id: 'dev-1', updated_at: OPENED }))
    await Promise.all([save.submit(), answer('overwrite')])

    expect(updateResource).toHaveBeenCalledTimes(2)
    expect(updateResource).toHaveBeenLastCalledWith('devices', 'dev-1', expect.objectContaining({ serial_number: 'SN-1' }))
    expect(syncDeviceDeployedSoftware).toHaveBeenCalledWith('dev-1', [])
    expect(deps.onSaved).toHaveBeenCalledTimes(1)
  })

  it('«Загрузить свежие данные»: список устройств перечитывается, форма закрывается, записи нет', async () => {
    const { save, deps } = setup(deviceOf({ id: 'dev-1', updated_at: OPENED }))
    await Promise.all([save.submit(), answer('reload')])

    expect(stores.spies.devicesReload).toHaveBeenCalledTimes(1)
    expect(deps.close).toHaveBeenCalledTimes(1)
    expect(deps.onSaved).not.toHaveBeenCalled()
    expect(syncDeviceDeployedSoftware).not.toHaveBeenCalled()
  })

  it('новое устройство: после сбоя вложенного шага токен перечитывается у сервера, повторное сохранение обновляет устройство с ним', async () => {
    updateResource.mockReset()
    updateResource.mockResolvedValue({ ...savedDevice, id: 'dev-new', updated_at: UPDATED })
    createResource.mockResolvedValue({ ...savedDevice, id: 'dev-new', updated_at: OPENED })
    getResource.mockResolvedValue({ id: 'dev-new', updated_at: REFRESHED }) // вложенные шаги успели сдвинуть версию
    persistDeviceVlans.mockRejectedValueOnce(new Error('сбой VLAN'))
    const { save } = setup()
    await save.submit() // создано, но следующий шаг упал: форма остаётся открытой
    await save.submit()

    expect(createResource).toHaveBeenCalledTimes(1)
    expect(getResource).toHaveBeenCalledWith('devices', 'dev-new')
    expect(updateResource).toHaveBeenCalledWith('devices', 'dev-new', expect.anything(), REFRESHED)
  })

  it('сбой порта при редактировании: повторное «Сохранить» не конфликтует с собственной правкой формы (токен перечитан)', async () => {
    updateResource.mockReset()
    updateResource.mockResolvedValue({ ...savedDevice, id: 'dev-1', updated_at: UPDATED })
    getResource.mockResolvedValue({ id: 'dev-1', updated_at: REFRESHED })
    persistDeviceInterfaces.mockRejectedValueOnce(new Error('порт занят'))
    const { draft, save, deps } = setup(deviceOf({ id: 'dev-1', updated_at: OPENED }))
    await save.submit()
    expect(draft.errorMessage.value).toBe('порт занят')
    expect(getResource).toHaveBeenCalledWith('devices', 'dev-1')

    await save.submit()
    expect(updateResource).toHaveBeenNthCalledWith(1, 'devices', 'dev-1', expect.anything(), OPENED)
    expect(updateResource).toHaveBeenNthCalledWith(2, 'devices', 'dev-1', expect.anything(), REFRESHED)
    expect(deps.onSaved).toHaveBeenCalledTimes(1)
  })

  it('сбой самой записи устройства: токен не перечитывается — чужую правку нельзя принять за свою', async () => {
    updateResource.mockReset()
    updateResource.mockRejectedValue(new Error('Серийный номер занят'))
    const { save } = setup(deviceOf({ id: 'dev-1', updated_at: OPENED }))
    await save.submit()
    expect(getResource).not.toHaveBeenCalled()
  })

  it('успешное сохранение не делает лишнего запроса за версией: форма закрывается', async () => {
    updateResource.mockReset()
    updateResource.mockResolvedValue({ ...savedDevice, id: 'dev-1', updated_at: UPDATED })
    const { save, deps } = setup(deviceOf({ id: 'dev-1', updated_at: OPENED }))
    await save.submit()
    expect(deps.onSaved).toHaveBeenCalledTimes(1)
    expect(getResource).not.toHaveBeenCalled()
  })

  it('не удалось перечитать версию: исходная причина сбоя остаётся в форме', async () => {
    updateResource.mockReset()
    updateResource.mockResolvedValue({ ...savedDevice, id: 'dev-1', updated_at: UPDATED })
    getResource.mockRejectedValue(new Error('сеть'))
    persistDeviceInterfaces.mockRejectedValueOnce(new Error('порт занят'))
    const { draft, save } = setup(deviceOf({ id: 'dev-1', updated_at: OPENED }))
    await save.submit()
    expect(draft.errorMessage.value).toBe('порт занят')
  })
})

describe('подтверждения конфликтов 409', () => {
  const conflict = (code: string) => new ApiError(409, `конфликт ${code}`, code)

  it('дубликат системного имени: после согласия отправка повторяется с флагом', async () => {
    createResource.mockRejectedValueOnce(conflict(ErrorCode.DUPLICATE_SYSTEM_NAME))
    const { save, deps } = setup()
    await save.submit()

    expect(confirmMock).toHaveBeenCalledTimes(1)
    expect(confirmMock.mock.calls[0][0]).toContain('конфликт DUPLICATE_SYSTEM_NAME')
    expect(createResource).toHaveBeenCalledTimes(2)
    expect(createResource.mock.calls[0][1]).not.toHaveProperty('confirm_system_name_duplicate')
    expect(createResource.mock.calls[1][1]).toMatchObject({ confirm_system_name_duplicate: true })
    expect(deps.onSaved).toHaveBeenCalledTimes(1)
  })

  it('занятая позиция в стойке: повтор с флагом переназначения', async () => {
    updateResource.mockRejectedValueOnce(conflict(ErrorCode.RACK_POSITION_OCCUPIED))
    const { save } = setup(deviceOf({ id: 'dev-1' }))
    await save.submit()
    expect(updateResource.mock.calls[1][2]).toMatchObject({ confirm_rack_position_reassign: true })
  })

  it('оба конфликта подряд: флаги накапливаются, на третьей попытке сохранение проходит', async () => {
    createResource.mockRejectedValueOnce(conflict(ErrorCode.DUPLICATE_SYSTEM_NAME)).mockRejectedValueOnce(conflict(ErrorCode.RACK_POSITION_OCCUPIED))
    const { save, deps } = setup()
    await save.submit()
    expect(createResource).toHaveBeenCalledTimes(3)
    expect(createResource.mock.calls[2][1]).toMatchObject({ confirm_system_name_duplicate: true, confirm_rack_position_reassign: true })
    expect(deps.onSaved).toHaveBeenCalledTimes(1)
  })

  it('обратный порядок конфликтов (стойка, затем имя): флаги тоже накапливаются', async () => {
    createResource.mockRejectedValueOnce(conflict(ErrorCode.RACK_POSITION_OCCUPIED)).mockRejectedValueOnce(conflict(ErrorCode.DUPLICATE_SYSTEM_NAME))
    const { save } = setup()
    await save.submit()
    expect(createResource.mock.calls[2][1]).toMatchObject({ confirm_system_name_duplicate: true, confirm_rack_position_reassign: true })
  })

  it('отказ в диалоге о позиции в стойке: повторной отправки нет, ошибка остаётся в форме', async () => {
    confirmMock.mockReturnValue(false)
    createResource.mockRejectedValue(conflict(ErrorCode.RACK_POSITION_OCCUPIED))
    const { draft, save, deps } = setup()
    await save.submit()
    expect(confirmMock).toHaveBeenCalledTimes(1)
    expect(createResource).toHaveBeenCalledTimes(1)
    expect(draft.errorMessage.value).toBe('конфликт RACK_POSITION_OCCUPIED')
    expect(deps.onSaved).not.toHaveBeenCalled()
  })

  it('отказ в диалоге: повторной отправки нет, ошибка конфликта остаётся в форме', async () => {
    confirmMock.mockReturnValue(false)
    createResource.mockRejectedValue(conflict(ErrorCode.DUPLICATE_SYSTEM_NAME))
    const { draft, save, deps } = setup()
    await save.submit()
    expect(createResource).toHaveBeenCalledTimes(1)
    expect(draft.errorMessage.value).toBe('конфликт DUPLICATE_SYSTEM_NAME')
    expect(deps.onSaved).not.toHaveBeenCalled()
  })

  it('другой код ошибки диалога не вызывает', async () => {
    createResource.mockRejectedValue(new ApiError(409, 'ссылка', ErrorCode.REFERENCED_BY_OTHER_RECORDS))
    const { draft, save } = setup()
    await save.submit()
    expect(confirmMock).not.toHaveBeenCalled()
    expect(draft.errorMessage.value).toBe('ссылка')
  })
})

describe('проверка расхождений с соседями (reviewNeighbors)', () => {
  it('получает снимок конфигурации портов на момент открытия формы', async () => {
    const { draft, save, deps } = setup()
    draft.snapshot.portConfigs = new Map([['if-1', { is_management: false, is_data_transfer: false, vlan_mode: 'access', all_vlans: false }]])
    await save.submit()
    expect(deps.reviewNeighbors).toHaveBeenCalledWith(draft.snapshot.portConfigs)
  })

  it('пользователь отказался сохранять: записи нет, saving сброшен', async () => {
    const { save, deps } = setup(null, { reviewNeighbors: vi.fn(async () => false) })
    await save.submit()
    expect(createResource).not.toHaveBeenCalled()
    expect(deps.onSaved).not.toHaveBeenCalled()
    expect(save.saving.value).toBe(false)
  })

  it('пользователь согласился: сохранение идёт', async () => {
    const { save, deps } = setup(null, { reviewNeighbors: vi.fn(async () => true) })
    await save.submit()
    expect(deps.onSaved).toHaveBeenCalledTimes(1)
  })

  it('редактор портов ещё не смонтирован (undefined): проверять нечего, сохранение идёт', async () => {
    const { save, deps } = setup(null, { reviewNeighbors: vi.fn(() => undefined) })
    await save.submit()
    expect(deps.onSaved).toHaveBeenCalledTimes(1)
  })
})

describe('подключения портов и уведомление о расхождениях', () => {
  const neighbor = (patch: Partial<DeviceInterfaceConnection> = {}): DeviceInterfaceConnection => ({
    interface_id: 'if-1',
    connection_id: 'c-1',
    connection_type_id: 'ct-1',
    description: null,
    peer_interface_id: 'p-1',
    peer_interface_name: 'Gi0/9',
    peer_device_id: 'dev-2',
    peer_device_name: 'sw-02',
    peer_is_management: false,
    peer_is_data_transfer: false,
    peer_vlan_mode: 'access',
    peer_all_vlans: false,
    ...patch,
  })

  it('без изменений подключений соседи с сервера не перечитываются и стор подключений не трогается', async () => {
    const connections = useConnectionsStore()
    connections.loaded = true
    const reload = vi.spyOn(connections, 'reload').mockResolvedValue(undefined)
    const { draft, save } = setup(deviceOf({ id: 'dev-1' }))
    draft.interfaces.value = [makeRow({ id: 'if-1', name: 'Gi0/1' })]
    draft.initialConnections.value = new Map([['if-1', null]])
    await save.submit()
    expect(fetchDeviceInterfaceConnections).not.toHaveBeenCalled()
    expect(reload).not.toHaveBeenCalled()
  })

  it('подключение изменено: соседи перечитываются для сохранённого устройства, загруженный общий список подключений обновляется', async () => {
    const connections = useConnectionsStore()
    connections.loaded = true
    const reload = vi.spyOn(connections, 'reload').mockResolvedValue(undefined)
    const { draft, save } = setup(deviceOf({ id: 'dev-1' }))
    draft.interfaces.value = [
      makeRow({ id: 'if-1', name: 'Gi0/1', connection: { peer_device_id: 'dev-2', peer_interface_id: 'p-1', connection_type_id: 'ct-1', description: '' } }),
    ]
    draft.initialConnections.value = new Map([['if-1', null]])
    await save.submit()
    expect(fetchDeviceInterfaceConnections).toHaveBeenCalledWith('dev-1')
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('общий список подключений не загружен — он и так загрузится свежим, лишней перезагрузки нет', async () => {
    const connections = useConnectionsStore()
    connections.loaded = false
    const reload = vi.spyOn(connections, 'reload').mockResolvedValue(undefined)
    const { draft, save } = setup(deviceOf({ id: 'dev-1' }))
    draft.interfaces.value = [
      makeRow({ id: 'if-1', name: 'Gi0/1', connection: { peer_device_id: 'dev-2', peer_interface_id: 'p-1', connection_type_id: 'ct-1', description: '' } }),
    ]
    draft.initialConnections.value = new Map([['if-1', null]])
    await save.submit()
    expect(reload).not.toHaveBeenCalled()
  })

  it('порт теперь расходится с соседом: после сохранения предупреждение с именами портов; onSaved вызывается после него', async () => {
    const { draft, save, deps } = setup(deviceOf({ id: 'dev-1' }))
    draft.interfaces.value = [makeRow({ id: 'if-1', name: 'Gi0/1', vlan_mode: 'trunk' })]
    draft.initialConnections.value = new Map([['if-1', null]])
    draft.snapshot.portConfigs = new Map([['if-1', { is_management: false, is_data_transfer: false, vlan_mode: 'access', all_vlans: false }]])
    draft.savedConnections.value = [neighbor()]
    await save.submit()

    const warning = toasts().find((t) => t.type === 'warning')
    expect(warning?.message).toContain('Gi0/1')
    expect(warning?.message).toContain('Gi0/9')
    expect(deps.onSaved).toHaveBeenCalledTimes(1)
  })

  it('новый порт с подключением: расхождение считается по сохранённым портам (с id от сервера), а не по черновику без id', async () => {
    persistDeviceInterfaces.mockResolvedValue({
      items: [{ id: 'if-saved', name: 'Gi0/1', is_management: false, is_data_transfer: false, vlan_mode: 'trunk', all_vlans: false }],
      groups: [],
    })
    fetchDeviceInterfaceConnections.mockResolvedValue([neighbor({ interface_id: 'if-saved' })])
    const { draft, save } = setup(deviceOf({ id: 'dev-1' }))
    draft.interfaces.value = [
      makeRow({
        name: 'Gi0/1',
        vlan_mode: 'trunk',
        connection: { peer_device_id: 'dev-2', peer_interface_id: 'p-1', connection_type_id: 'ct-1', description: '' },
      }),
    ]
    await save.submit()

    const warning = toasts().find((t) => t.type === 'warning')
    expect(warning?.message).toContain('Gi0/1')
    expect(warning?.message).toContain('Gi0/9')
  })

  it('конфигурация портов не менялась — предупреждения о расхождениях нет', async () => {
    const { draft, save } = setup(deviceOf({ id: 'dev-1' }))
    draft.interfaces.value = [makeRow({ id: 'if-1', name: 'Gi0/1', vlan_mode: 'trunk' })]
    draft.snapshot.portConfigs = new Map([['if-1', { is_management: false, is_data_transfer: false, vlan_mode: 'trunk', all_vlans: false }]])
    draft.savedConnections.value = [neighbor()]
    await save.submit()
    expect(toasts().filter((t) => t.type === 'warning')).toEqual([])
  })
})
