import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useFindingEditor } from '../useFindingEditor'
import { useToast } from '../useToast'
import { useConnectionsStore } from '../../stores/connections'
import { useDevicesStore } from '../../stores/devices'
import { useVMsStore } from '../../stores/vms'

beforeEach(() => {
  setActivePinia(createPinia())
  useToast().toasts.splice(0)
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
