import { beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref, type ComputedRef } from 'vue'
import { createResource, updateResource } from '../../api/client'
import { approvePortConfig, setPortRole } from '../../api/portConfig'
import type { Connection } from '../../api/types'
import type { ConfigView } from '../../utils/connectionPortView'
import { useToast } from '../useToast'
import { useConnectionDraft } from '../useConnectionDraft'
import type { ConnectionPortConfig } from '../useConnectionPortConfig'
import { useConnectionSave } from '../useConnectionSave'
import { connection, device, iface, setupConnectionStores } from './connectionFormTestkit'

vi.mock('../../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../api/client')>()), createResource: vi.fn(), updateResource: vi.fn() }))
vi.mock('../../api/portConfig', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../api/portConfig')>()), setPortRole: vi.fn(), approvePortConfig: vi.fn() }))

// Каскад смены режима — отдельный композабл со своим спеком: здесь подменяем его и проверяем только стыковку.
const cascadeFake = vi.hoisted(() => ({
  start: vi.fn(),
  cancel: vi.fn(),
  confirm: vi.fn(),
  onFinished: undefined as undefined | (() => Promise<void>),
}))
vi.mock('../useVlanModeCascade', async () => {
  const { ref } = await import('vue')
  return {
    useVlanModeCascade: (host: { onFinished: () => Promise<void> }) => {
      cascadeFake.onFinished = host.onFinished
      return { pending: ref(null), applying: ref(false), start: cascadeFake.start, cancel: cascadeFake.cancel, confirm: cascadeFake.confirm }
    },
  }
})

const created = connection({ id: 'c-new' })
const mismatch = (diff: ConfigView['diff'] = ['role']): ConfigView => ({
  status: 'mismatch',
  diff,
  source: { id: 'if-a', name: 'if-a', role: 'management', mode: 'trunk', vlans: null },
  destination: { id: 'if-b', name: 'if-b', role: 'data', mode: 'access', vlans: null },
})

/** Подменная сверка портов: тест задаёт, есть ли расхождение, и что вернёт перезапрос. */
function fakePortConfig(initial: ConfigView | null = null) {
  const view = ref<ConfigView | null>(initial)
  const approved = ref(false)
  const portMismatch = computed(() => view.value) as ComputedRef<ConfigView | null>
  const fake = {
    settle: vi.fn(async () => {}),
    refresh: vi.fn(async () => {}),
    portMismatch,
    needsResolution: computed(() => !!view.value && !approved.value),
  }
  return { fake: fake as unknown as ConnectionPortConfig, spies: fake, view, approved }
}

function setup(options: { connection?: Connection | null; readOnly?: boolean; view?: ConfigView | null; filled?: boolean } = {}) {
  const stores = setupConnectionStores({ devices: [device('dev-1', 'alpha'), device('dev-2', 'beta')], interfaces: [iface('if-a', 'dev-1'), iface('if-b', 'dev-2')] })
  const conn = options.connection ?? null
  const draft = useConnectionDraft({ connection: () => conn, prefill: () => null })
  if (options.filled !== false) {
    Object.assign(draft.form, { sourceDeviceId: 'dev-1', source_interface_id: 'if-a', destinationDeviceId: 'dev-2', destination_interface_id: 'if-b', connection_type_id: 'ct-1', description: '' })
  }
  const port = fakePortConfig(options.view ?? null)
  const onSaved = vi.fn()
  const save = useConnectionSave(draft, port.fake, { connection: () => conn, readOnly: ref(options.readOnly ?? false), onSaved })
  return { stores, draft, port, onSaved, save }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(createResource).mockResolvedValue(created as never)
  vi.mocked(updateResource).mockResolvedValue(created as never)
  vi.mocked(setPortRole).mockResolvedValue(iface('if-b', 'dev-2', { is_management: true }) as never)
  vi.mocked(approvePortConfig).mockResolvedValue({} as never)
  useToast().toasts.splice(0)
})

describe('useConnectionSave — submit', () => {
  it('режим просмотра: ничего не отправляется и не проверяется', async () => {
    const { save, draft, onSaved } = setup({ readOnly: true, filled: false })
    await save.submit()
    expect(draft.errorMessage.value).toBeNull()
    expect(createResource).not.toHaveBeenCalled()
    expect(onSaved).not.toHaveBeenCalled()
  })

  it('ошибка проверки формы: сообщение, запроса нет, сверку не ждём', async () => {
    const { save, draft, port } = setup({ filled: false })
    await save.submit()
    expect(draft.errorMessage.value).toBe('Выберите исходное устройство и его порт.')
    expect(createResource).not.toHaveBeenCalled()
    expect(port.spies.settle).not.toHaveBeenCalled()
  })

  it('прежнее сообщение об ошибке очищается перед повторной отправкой', async () => {
    const { save, draft } = setup()
    draft.errorMessage.value = 'старая ошибка'
    await save.submit()
    expect(draft.errorMessage.value).toBeNull()
  })

  it('создание: сначала дожидается сверки, затем POST с телом запроса и сообщает родителю', async () => {
    const { save, port, onSaved, draft } = setup()
    await save.submit()
    expect(port.spies.settle).toHaveBeenCalledTimes(1)
    expect(createResource).toHaveBeenCalledWith('connections', { source_interface_id: 'if-a', destination_interface_id: 'if-b', connection_type_id: 'ct-1', is_active: true, description: null })
    expect(updateResource).not.toHaveBeenCalled()
    expect(approvePortConfig).not.toHaveBeenCalled()
    expect(onSaved).toHaveBeenCalledWith(created)
    expect(draft.saving.value).toBe(false)
  })

  it('редактирование: PUT по id подключения', async () => {
    const { save, onSaved } = setup({ connection: connection({ id: 'c-9' }) })
    await save.submit()
    expect(updateResource).toHaveBeenCalledWith('connections', 'c-9', expect.objectContaining({ source_interface_id: 'if-a' }))
    expect(createResource).not.toHaveBeenCalled()
    expect(onSaved).toHaveBeenCalledWith(created)
  })

  it('расхождение: подключение не сохраняется, показывается выбор решения', async () => {
    const { save, draft, onSaved } = setup({ view: mismatch() })
    await save.submit()
    expect(draft.resolving.value).toBe(true)
    expect(createResource).not.toHaveBeenCalled()
    expect(onSaved).not.toHaveBeenCalled()
  })

  it('расхождение уже одобрено — сохраняется без вопросов', async () => {
    const { save, draft, port, onSaved } = setup({ view: mismatch() })
    port.approved.value = true
    await save.submit()
    expect(draft.resolving.value).toBe(false)
    expect(onSaved).toHaveBeenCalled()
  })

  it('ошибка сервера при сохранении: текст ошибки в форме, родителю не сообщается, saving снят', async () => {
    vi.mocked(createResource).mockRejectedValue(new Error('порт уже занят'))
    const { save, draft, onSaved } = setup()
    await save.submit()
    expect(draft.errorMessage.value).toBe('порт уже занят')
    expect(onSaved).not.toHaveBeenCalled()
    expect(draft.saving.value).toBe(false)
  })

  it('ошибка не Error — общий текст', async () => {
    vi.mocked(createResource).mockRejectedValue('boom')
    const { save, draft } = setup()
    await save.submit()
    expect(draft.errorMessage.value).toBe('Не удалось сохранить подключение')
  })

  it('во время запроса saving = true', async () => {
    let release!: (c: Connection) => void
    vi.mocked(createResource).mockReturnValue(new Promise<Connection>((r) => (release = r)) as never)
    const { save, draft } = setup()
    const submitting = save.submit()
    await vi.waitFor(() => expect(draft.saving.value).toBe(true))
    release(created)
    await submitting
    expect(draft.saving.value).toBe(false)
  })
})

describe('useConnectionSave — решение по расхождению', () => {
  it('режим просмотра: решение не выполняется', async () => {
    const { save, draft } = setup({ readOnly: true, view: mismatch() })
    draft.resolving.value = true
    await save.resolveAndSave('approve')
    expect(draft.resolving.value).toBe(true)
    expect(createResource).not.toHaveBeenCalled()
  })

  it('«одобрить»: сохраняет и одобряет расхождение по id сохранённого подключения', async () => {
    const { save, draft, onSaved } = setup({ view: mismatch() })
    draft.resolving.value = true
    await save.resolveAndSave('approve')
    expect(draft.resolving.value).toBe(false)
    expect(createResource).toHaveBeenCalledTimes(1)
    expect(approvePortConfig).toHaveBeenCalledWith(['c-new'])
    expect(onSaved).toHaveBeenCalledWith(created)
  })

  it('«одобрить»: сбой одобрения не мешает сохранению — предупреждение, форма закрывается', async () => {
    vi.mocked(approvePortConfig).mockRejectedValue(new Error('нет прав'))
    const { save, onSaved, draft } = setup({ view: mismatch() })
    await save.resolveAndSave('approve')
    expect(onSaved).toHaveBeenCalledWith(created)
    expect(draft.errorMessage.value).toBeNull()
    const toasts = useToast().toasts
    expect(toasts).toHaveLength(1)
    expect(toasts[0]).toMatchObject({ type: 'warning', message: 'Подключение сохранено, но расхождение не одобрено: нет прав' })
  })

  it('«роль как у источника»: роль меняется у конечного порта, каталог обновляется, затем сверка и сохранение', async () => {
    const { save, stores, port, onSaved } = setup({ view: mismatch() })
    const replaced = iface('if-b', 'dev-2', { is_management: true })
    vi.mocked(setPortRole).mockResolvedValue(replaced as never)
    // после выравнивания роли расхождения не осталось
    port.spies.refresh.mockImplementation(async () => {
      port.view.value = null
    })
    await save.resolveAndSave('keep-source')
    expect(setPortRole).toHaveBeenCalledWith('if-b', 'management')
    expect((stores.catalogs.items['interfaces'] ?? []).find((i) => i.id === 'if-b')).toEqual(replaced)
    expect(port.spies.refresh).toHaveBeenCalledTimes(1)
    expect(createResource).toHaveBeenCalledTimes(1)
    expect(onSaved).toHaveBeenCalled()
  })

  it('«роль как у назначения»: меняется роль исходного порта', async () => {
    const { save, port } = setup({ view: mismatch() })
    port.spies.refresh.mockImplementation(async () => {
      port.view.value = null
    })
    await save.resolveAndSave('keep-destination')
    expect(setPortRole).toHaveBeenCalledWith('if-a', 'data')
  })

  it('после выравнивания роли осталось другое расхождение (режим) — снова выбор решения, без сохранения', async () => {
    const { save, draft, onSaved } = setup({ view: mismatch(['role', 'mode']) })
    await save.resolveAndSave('keep-source')
    expect(draft.resolving.value).toBe(true)
    expect(createResource).not.toHaveBeenCalled()
    expect(onSaved).not.toHaveBeenCalled()
    expect(draft.saving.value).toBe(false)
  })

  it('сбой смены роли: сообщение об ошибке, сохранения нет, saving снят', async () => {
    vi.mocked(setPortRole).mockRejectedValue(new Error('порт не найден'))
    const { save, draft, port } = setup({ view: mismatch() })
    await save.resolveAndSave('keep-source')
    expect(draft.errorMessage.value).toBe('порт не найден')
    expect(port.spies.refresh).not.toHaveBeenCalled()
    expect(createResource).not.toHaveBeenCalled()
    expect(draft.saving.value).toBe(false)
  })

  it('сбой смены роли не Error — общий текст', async () => {
    vi.mocked(setPortRole).mockRejectedValue('x')
    const { save, draft } = setup({ view: mismatch() })
    await save.resolveAndSave('keep-source')
    expect(draft.errorMessage.value).toBe('Не удалось изменить роль порта')
  })

  it('нет расхождения: выравнивать нечего — запрос роли не уходит', async () => {
    const { save } = setup({ view: null })
    await save.resolveAndSave('keep-source')
    expect(setPortRole).not.toHaveBeenCalled()
  })
})

describe('useConnectionSave — выравнивание режима каскадом', () => {
  it('«режим как у источника»: каскад запускается для конечного порта с подписью порта и устройства', async () => {
    const { save, draft } = setup({ view: mismatch(['mode']) })
    await save.resolveAndSave('mode-keep-source')
    expect(cascadeFake.start).toHaveBeenCalledWith('if-b', 'trunk', '«if-b» (beta)')
    expect(draft.saving.value).toBe(false)
    expect(createResource).not.toHaveBeenCalled() // сохранение продолжится из onFinished каскада
  })

  it('«режим как у назначения»: каскад для исходного порта', async () => {
    const { save } = setup({ view: mismatch(['mode']) })
    await save.resolveAndSave('mode-keep-destination')
    expect(cascadeFake.start).toHaveBeenCalledWith('if-a', 'access', '«if-a» (alpha)')
  })

  it('режим победителя неизвестен — каскад не запускается', async () => {
    const view = mismatch(['mode'])
    view.source.mode = null
    const { save } = setup({ view })
    await save.resolveAndSave('mode-keep-source')
    expect(cascadeFake.start).not.toHaveBeenCalled()
  })

  it('сбой каскада: сообщение в форме, saving снят', async () => {
    cascadeFake.start.mockRejectedValueOnce(new Error('область слишком большая'))
    const { save, draft } = setup({ view: mismatch(['mode']) })
    await save.resolveAndSave('mode-keep-source')
    expect(draft.errorMessage.value).toBe('область слишком большая')
    expect(draft.saving.value).toBe(false)
  })

  it('сбой каскада не Error — общий текст', async () => {
    cascadeFake.start.mockRejectedValueOnce('x')
    const { save, draft } = setup({ view: mismatch(['mode']) })
    await save.resolveAndSave('mode-keep-source')
    expect(draft.errorMessage.value).toBe('Не удалось изменить режим порта')
  })

  it('каскад завершён, расхождения нет: сверка пересчитывается и подключение сохраняется', async () => {
    const { port, onSaved } = setup({ view: mismatch(['mode']) })
    port.spies.refresh.mockImplementation(async () => {
      port.view.value = null
    })
    await cascadeFake.onFinished!()
    expect(port.spies.refresh).toHaveBeenCalledTimes(1)
    expect(createResource).toHaveBeenCalledTimes(1)
    expect(onSaved).toHaveBeenCalled()
  })

  it('каскад завершён, остались VLAN: снова выбор решения', async () => {
    const { port, draft } = setup({ view: mismatch(['vlans']) })
    await cascadeFake.onFinished!()
    expect(port.spies.refresh).toHaveBeenCalledTimes(1)
    expect(draft.resolving.value).toBe(true)
    expect(createResource).not.toHaveBeenCalled()
  })

  it('cancelCascade: окно последствий закрыто, ничего не записано — возврат к выбору решения', () => {
    const { save, draft } = setup({ view: mismatch(['mode']) })
    save.cancelCascade()
    expect(cascadeFake.cancel).toHaveBeenCalledTimes(1)
    expect(draft.resolving.value).toBe(true)
  })

  it('состояние окна последствий пробрасывается наружу', () => {
    const { save } = setup()
    expect(save.cascadePending.value).toBeNull()
    expect(save.cascadeApplying.value).toBe(false)
    expect(save.cascadeConfirm).toBe(cascadeFake.confirm)
  })
})
