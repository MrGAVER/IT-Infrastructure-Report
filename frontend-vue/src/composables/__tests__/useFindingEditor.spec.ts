import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useFindingEditor } from '../useFindingEditor'
import { useToast } from '../useToast'
import { useCatalogsStore } from '../../stores/catalogs'
import { useConnectionsStore } from '../../stores/connections'
import { useContainersStore } from '../../stores/containers'
import { useDevicesStore } from '../../stores/devices'
import { useInformationSystemsStore } from '../../stores/informationSystems'
import { useVLANsStore } from '../../stores/vlans'
import { useVMsStore } from '../../stores/vms'

beforeEach(() => {
  setActivePinia(createPinia())
  useToast().toasts.splice(0)
  // Справочники и связанные списки, которые форма читает попутно, в этих тестах не грузятся по сети: их загрузку проверяет отдельный блок ниже.
  for (const store of [useCatalogsStore(), useVLANsStore(), useDevicesStore(), useVMsStore(), useContainersStore(), useInformationSystemsStore(), useConnectionsStore()]) {
    vi.spyOn(store, 'ensureLoaded').mockResolvedValue(undefined as never)
  }
})

function loadedDevices() {
  const devices = useDevicesStore()
  devices.all = [{ id: 'dev-1', system_name: 'srv-1' }] as never
  devices.loaded = true
  return devices
}

describe('useFindingEditor', () => {
  it('открывает запись из справочника своего раздела и закрывает её', async () => {
    loadedDevices()
    const editor = useFindingEditor(vi.fn())

    await editor.open({ type: 'physical_device', id: 'dev-1', name: 'srv-1' })
    expect(editor.device.value).toMatchObject({ id: 'dev-1' })

    editor.close()
    expect(editor.device.value).toBeNull()
  })

  it('тип без окна редактирования (IP-адрес) и неизвестный тип ничего не открывают и не грузят', async () => {
    const devices = loadedDevices()
    const ensure = vi.spyOn(devices, 'ensureLoaded')
    const editor = useFindingEditor(vi.fn())

    await editor.open({ type: 'ip_address', id: '10.0.0.5', name: '10.0.0.5' })
    await editor.open({ type: 'что-то-новое', id: 'x', name: 'x' })

    expect(editor.device.value).toBeNull()
    expect(ensure).not.toHaveBeenCalled()
  })

  it('пока запись подгружается, повторное нажатие не открывает второе окно', async () => {
    const devices = loadedDevices()
    let release!: () => void
    vi.spyOn(devices, 'ensureLoaded').mockReturnValue(new Promise<void>((done) => (release = done)))
    const editor = useFindingEditor(vi.fn())

    const first = editor.open({ type: 'physical_device', id: 'dev-1', name: 'srv-1' })
    const second = editor.open({ type: 'physical_device', id: 'dev-1', name: 'srv-1' })
    expect(editor.opening.value).toBe(true)
    release()
    await Promise.all([first, second])

    expect(editor.opening.value).toBe(false)
    expect(devices.ensureLoaded).toHaveBeenCalledOnce()
  })

  it('записи нет в справочнике — сообщение с именем объекта, окно не открывается', async () => {
    loadedDevices()
    const editor = useFindingEditor(vi.fn())

    await editor.open({ type: 'physical_device', id: 'gone', name: 'удалённый' })

    expect(editor.device.value).toBeNull()
    expect(useToast().toasts.map((toast) => toast.message)).toEqual(['«удалённый» не найден — запустите проверку заново'])
  })

  it('ошибка загрузки справочника показывается, а не теряется; повторное нажатие после неё снова возможно', async () => {
    const vms = useVMsStore()
    vi.spyOn(vms, 'ensureLoaded').mockRejectedValue(new Error('Сервер недоступен'))
    const editor = useFindingEditor(vi.fn())

    await editor.open({ type: 'virtual_machine', id: 'vm-1', name: 'vm-1' })

    expect(useToast().toasts.some((toast) => toast.message.includes('Сервер недоступен'))).toBe(true)
    expect(editor.opening.value).toBe(false)
  })

  it('после сохранения окно закрыто, справочник перечитан и проверка запущена заново', async () => {
    const devices = loadedDevices()
    const reload = vi.spyOn(devices, 'reload').mockResolvedValue(undefined as never)
    const rerun = vi.fn(async () => {})
    const editor = useFindingEditor(rerun)
    await editor.open({ type: 'physical_device', id: 'dev-1', name: 'srv-1' })

    await editor.saved('physical_device')

    expect(editor.device.value).toBeNull()
    expect(reload).toHaveBeenCalledOnce()
    expect(rerun).toHaveBeenCalledOnce()
  })

  it('подключение открывается из справочника подключений', async () => {
    const connections = useConnectionsStore()
    connections.all = [{ id: 'conn-1' }] as never
    connections.loaded = true
    const editor = useFindingEditor(vi.fn())

    await editor.open({ type: 'connection', id: 'conn-1', name: 'sw-a (Gi0/1) ↔ sw-b (Gi0/2)' })

    expect(editor.connection.value).toMatchObject({ id: 'conn-1' })
    expect(editor.device.value).toBeNull()
    editor.close()
    expect(editor.connection.value).toBeNull()
  })
})

// Форма объекта читает не только саму запись, но и справочники/списки (типы, модели, здания, VLAN, устройства, ВМ…). Обычные разделы
// подгружают их при открытии; здесь раздела нет, поэтому без явной загрузки форма открывалась с пустыми выпадающими списками.
describe('useFindingEditor: данные для формы', () => {
  const CASES = [
    { type: 'physical_device', field: 'device', related: ['catalogs', 'vlans'] },
    { type: 'virtual_machine', field: 'vm', related: ['catalogs', 'devices'] },
    { type: 'container', field: 'container', related: ['catalogs', 'devices', 'vms'] },
    { type: 'information_system', field: 'system', related: ['catalogs', 'devices', 'vms', 'containers'] },
    { type: 'connection', field: 'connection', related: ['catalogs', 'devices'] },
  ] as const

  function stores() {
    return {
      catalogs: useCatalogsStore(),
      vlans: useVLANsStore(),
      devices: useDevicesStore(),
      vms: useVMsStore(),
      containers: useContainersStore(),
      systems: useInformationSystemsStore(),
      connections: useConnectionsStore(),
    }
  }

  it.each(CASES)('$type: окно открывается только после загрузки справочников и связанных списков', async ({ type, field, related }) => {
    const all = stores()
    const own = { physical_device: all.devices, virtual_machine: all.vms, container: all.containers, information_system: all.systems, connection: all.connections }[type]
    ;(own as { all: unknown[] }).all = [{ id: 'rec-1' }]

    // Каждая загрузка «висит», пока тест её не завершит: так видно, дождалось ли окно всех нужных данных.
    const pending = new Map<string, () => void>()
    for (const [name, store] of Object.entries(all)) {
      vi.mocked(store.ensureLoaded).mockImplementation(() => new Promise<void>((done) => pending.set(name, done)))
    }
    const editor = useFindingEditor(vi.fn())

    const opening = editor.open({ type, id: 'rec-1', name: 'rec-1' })
    await Promise.resolve()

    // Загружены собственный список раздела и всё, что нужно форме; лишнего не грузится.
    const ownName = Object.entries(all).find(([, store]) => store === own)![0]
    expect([...pending.keys()].sort()).toEqual([ownName, ...related].sort())
    expect(editor[field].value).toBeNull()

    for (const [name, done] of pending) {
      if (name !== 'catalogs') done()
    }
    await Promise.resolve()
    await Promise.resolve()
    expect(editor[field].value).toBeNull() // справочники ещё грузятся — окно рано открывать

    pending.get('catalogs')!()
    await opening
    expect(editor[field].value).toMatchObject({ id: 'rec-1' })
  })
})
