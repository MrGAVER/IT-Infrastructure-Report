// Окно редактирования объекта проблемы: открывается по нажатию на имя в находке (устройство, ВМ, контейнер, ИС, подключение).
// Объект берётся из стора раздела (тот же приём, что у списка устаревших подинтерфейсов на экране VLAN); после сохранения стор
// перечитывается, и вызывающий экран заново запускает проверку — исправленная проблема исчезает из списка.
import { ref } from 'vue'
import type { EntityTarget } from '../api/consistency'
import { isEditableEntity } from '../api/consistency'
import type { Connection, Container, Device, InformationSystem, VirtualMachine } from '../api/types'
import { useConnectionsStore } from '../stores/connections'
import { useContainersStore } from '../stores/containers'
import { useDevicesStore } from '../stores/devices'
import { useInformationSystemsStore } from '../stores/informationSystems'
import { useVMsStore } from '../stores/vms'
import { useToast } from './useToast'

export function useFindingEditor(onSaved: () => Promise<void> | void) {
  const { notify, notifyError } = useToast()
  const devices = useDevicesStore()
  const vms = useVMsStore()
  const containers = useContainersStore()
  const systems = useInformationSystemsStore()
  const connections = useConnectionsStore()

  // Открыто не больше одного окна: у каждого типа своя форма, поэтому и ссылка своя.
  const device = ref<Device | null>(null)
  const vm = ref<VirtualMachine | null>(null)
  const container = ref<Container | null>(null)
  const system = ref<InformationSystem | null>(null)
  const connection = ref<Connection | null>(null)
  // Пока объект подгружается, повторное нажатие не должно открыть второе окно.
  const opening = ref(false)

  /** Раздел объекта: сам стор для поиска записи и перечитывания после сохранения. */
  function sectionOf(type: string) {
    if (type === 'physical_device') return devices
    if (type === 'virtual_machine') return vms
    if (type === 'container') return containers
    if (type === 'information_system') return systems
    if (type === 'connection') return connections
    return null
  }

  function close(): void {
    device.value = vm.value = container.value = system.value = connection.value = null
  }

  async function open(target: EntityTarget): Promise<void> {
    const section = isEditableEntity(target.type) ? sectionOf(target.type) : null
    if (!section || opening.value) return
    opening.value = true
    try {
      await section.ensureLoaded()
      const record = (section.all as { id: string }[]).find((item) => item.id === target.id)
      if (!record) {
        // Объект удалили или переименовали после проверки: окно открывать не на чем.
        notify(`«${target.name}» не найден — запустите проверку заново`, 'error')
        return
      }
      close()
      if (target.type === 'physical_device') device.value = record as Device
      else if (target.type === 'virtual_machine') vm.value = record as VirtualMachine
      else if (target.type === 'container') container.value = record as Container
      else if (target.type === 'information_system') system.value = record as InformationSystem
      else connection.value = record as Connection
    } catch (err) {
      notifyError(err)
    } finally {
      opening.value = false
    }
  }

  async function saved(type: EntityTarget['type']): Promise<void> {
    close()
    try {
      await sectionOf(type)?.reload()
      await onSaved()
      notify('Сохранено. Проверка обновлена', 'success')
    } catch (err) {
      notifyError(err)
    }
  }

  return { device, vm, container, system, connection, opening, open, close, saved }
}
