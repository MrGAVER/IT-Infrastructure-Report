import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useContainersStore } from '../../stores/containers'
import { useDevicesStore } from '../../stores/devices'
import { useInformationSystemsStore } from '../../stores/informationSystems'
import { useVMsStore } from '../../stores/vms'
import { useStaleRecordConflict, type StaleRecordChoice } from '../useStaleRecordConflict'

const updateResource = vi.fn()
vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  updateResource: (...args: unknown[]) => updateResource(...args),
}))

const { ApiError, ErrorCode } = await import('../../api/client')
const { useStaleRecordGuard } = await import('../useStaleRecordGuard')

const T1 = '2026-11-01T10:00:00.000Z'
const T2 = '2026-11-01T10:05:00.000Z'
const staleError = () => new ApiError(409, 'Запись изменена другим пользователем', ErrorCode.STALE_RECORD)

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

/** Отвечает на вопрос о конфликте так, как это сделало бы окно StaleRecordHost. */
function answerConflict(choice: StaleRecordChoice) {
  const conflict = useStaleRecordConflict()
  return settle().then(() => {
    expect(conflict.question.value).not.toBeNull()
    conflict.resolve(choice)
  })
}

function setup(record: { updated_at?: string | null } | null = { updated_at: T1 }) {
  const close = vi.fn()
  const guard = useStaleRecordGuard({ resource: 'vms', record: () => record, close })
  return { guard, close }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  useStaleRecordConflict().resolve('stay')
  updateResource.mockImplementation(async (_resource: string, id: string) => ({ id, updated_at: T2 }))
})

describe('передача токена серверу', () => {
  it('updated_at записи, с которой открыта форма, уходит как expected_updated_at', async () => {
    const { guard } = setup()
    await guard.update('vm-1', { name: 'vm' })
    expect(updateResource).toHaveBeenCalledWith('vms', 'vm-1', { name: 'vm' }, T1)
  })

  it('токен обновляется из ответа: повторное сохранение формы после сбоя следующих шагов не считается конфликтом', async () => {
    const { guard } = setup()
    await guard.update('vm-1', { name: 'a' })
    await guard.update('vm-1', { name: 'b' })
    expect(updateResource).toHaveBeenNthCalledWith(1, 'vms', 'vm-1', { name: 'a' }, T1)
    expect(updateResource).toHaveBeenNthCalledWith(2, 'vms', 'vm-1', { name: 'b' }, T2)
  })

  it('у записи нет updated_at (или записи нет): проверки версии нет, запрос прежний, без токена', async () => {
    await setup({}).guard.update('vm-1', { name: 'a' })
    await setup(null).guard.update('vm-1', { name: 'b' })
    expect(updateResource).toHaveBeenNthCalledWith(1, 'vms', 'vm-1', { name: 'a' })
    expect(updateResource).toHaveBeenNthCalledWith(2, 'vms', 'vm-1', { name: 'b' })
  })

  it('токен читается при первой отправке, а не при создании guard: запись формы могла прийти позже', async () => {
    let record: { updated_at: string } = { updated_at: T1 }
    const guard = useStaleRecordGuard({ resource: 'vms', record: () => record, close: vi.fn() })
    record = { updated_at: T2 }
    await guard.update('vm-1', {})
    expect(updateResource).toHaveBeenCalledWith('vms', 'vm-1', {}, T2)
  })

  it('remember: токен созданной записи используется при следующем сохранении той же формы', async () => {
    const { guard } = setup(null)
    guard.remember({ updated_at: T1 })
    await guard.update('vm-new', {})
    expect(updateResource).toHaveBeenCalledWith('vms', 'vm-new', {}, T1)
  })
})

describe('конфликт версий (409 STALE_RECORD)', () => {
  beforeEach(() => {
    updateResource.mockImplementationOnce(async () => {
      throw staleError()
    })
  })

  it('«Сохранить мои изменения»: запись отправляется повторно без токена и возвращается как сохранённая', async () => {
    const { guard, close } = setup()
    const [saved] = await Promise.all([guard.update<{ id: string; updated_at?: string }>('vm-1', { name: 'мой' }), answerConflict('overwrite')])

    expect(saved).toEqual({ id: 'vm-1', updated_at: T2 })
    expect(updateResource).toHaveBeenCalledTimes(2)
    expect(updateResource).toHaveBeenLastCalledWith('vms', 'vm-1', { name: 'мой' })
    expect(close).not.toHaveBeenCalled()
  })

  it('вопросу передаётся текст сервера', async () => {
    const { guard } = setup()
    const pending = guard.update('vm-1', {})
    await settle()
    expect(useStaleRecordConflict().question.value?.message).toBe('Запись изменена другим пользователем')
    useStaleRecordConflict().resolve('stay')
    await pending
  })

  it('«Остаться в форме»: ничего не сохраняется и не закрывается, результат — null', async () => {
    const { guard, close } = setup()
    const reload = vi.spyOn(useVMsStore(), 'reload').mockResolvedValue(undefined)
    const [saved] = await Promise.all([guard.update('vm-1', {}), answerConflict('stay')])

    expect(saved).toBeNull()
    expect(updateResource).toHaveBeenCalledTimes(1)
    expect(reload).not.toHaveBeenCalled()
    expect(close).not.toHaveBeenCalled()
  })

  it('«Загрузить свежие данные»: список ресурса перечитывается до закрытия формы, результат — null', async () => {
    const { guard, close } = setup()
    const order: string[] = []
    vi.spyOn(useVMsStore(), 'reload').mockImplementation(async () => void order.push('reload'))
    close.mockImplementation(() => order.push('close'))
    const [saved] = await Promise.all([guard.update('vm-1', {}), answerConflict('reload')])

    expect(saved).toBeNull()
    expect(order).toEqual(['reload', 'close'])
    expect(updateResource).toHaveBeenCalledTimes(1)
  })

  it('токен после отказа не меняется: повторное сохранение снова сверяется с исходной версией', async () => {
    const { guard } = setup()
    await Promise.all([guard.update('vm-1', {}), answerConflict('stay')])
    await guard.update('vm-1', {})
    expect(updateResource).toHaveBeenLastCalledWith('vms', 'vm-1', {}, T1)
  })
})

describe('остальные ошибки', () => {
  it('другой 409 и прочие сбои пробрасываются как есть, окно конфликта не открывается', async () => {
    const { guard } = setup()
    updateResource.mockRejectedValueOnce(new ApiError(409, 'Дубликат', ErrorCode.DUPLICATE_SYSTEM_NAME))
    await expect(guard.update('vm-1', {})).rejects.toMatchObject({ code: ErrorCode.DUPLICATE_SYSTEM_NAME })
    updateResource.mockRejectedValueOnce(new Error('сеть'))
    await expect(guard.update('vm-1', {})).rejects.toThrow('сеть')
    expect(useStaleRecordConflict().question.value).toBeNull()
  })

  it('повторный конфликт при «Сохранить мои изменения» не зацикливается: ошибка пробрасывается', async () => {
    const { guard } = setup()
    updateResource.mockRejectedValueOnce(staleError()).mockRejectedValueOnce(new ApiError(500, 'сбой'))
    const [outcome] = await Promise.allSettled([guard.update('vm-1', {}), answerConflict('overwrite')])
    expect(outcome.status).toBe('rejected')
    expect(updateResource).toHaveBeenCalledTimes(2)
  })
})

describe('какой список перечитывается', () => {
  it.each([
    ['devices', useDevicesStore],
    ['vms', useVMsStore],
    ['containers', useContainersStore],
    ['information-systems', useInformationSystemsStore],
  ] as const)('%s: reload стора этого ресурса', async (resource, useStore) => {
    const reload = vi.spyOn(useStore(), 'reload').mockResolvedValue(undefined)
    const guard = useStaleRecordGuard({ resource, record: () => ({ updated_at: T1 }), close: vi.fn() })
    updateResource.mockRejectedValueOnce(staleError())
    await Promise.all([guard.update('id-1', {}), answerConflict('reload')])
    expect(reload).toHaveBeenCalledTimes(1)
    expect(updateResource).toHaveBeenCalledWith(resource, 'id-1', {}, T1)
  })
})
