// Модель формы подключения (ConnectionFormModal.vue): пустая форма, заполнение из подключения или подсказки схемы, тело запроса,
// проверка и выбор портов устройства. Чистые функции без Vue и без обращений к API.
import type { Connection, Device, DeviceInterface } from '../api/types'

/** Порты, уже выбранные курсором на схеме (ConnectionCanvasModal.vue): форма подставляет оба. */
export interface ConnectionPrefill {
  sourceInterfaceId: string
  destinationInterfaceId: string
}

export function emptyConnectionForm() {
  return {
    sourceDeviceId: '',
    source_interface_id: '',
    destinationDeviceId: '',
    destination_interface_id: '',
    connection_type_id: '',
    is_active: true,
    description: '',
  }
}

export type ConnectionForm = ReturnType<typeof emptyConnectionForm>

/**
 * Значения формы: из редактируемого подключения; для нового — из подсказки схемы (только порты и их устройства); иначе пустые.
 * Устройство порта берётся из каталога интерфейсов (в подключении хранятся только порты). Редактирование важнее подсказки.
 */
export function connectionFormFromSource(
  connection: Connection | null,
  prefill: ConnectionPrefill | null | undefined,
  interfaces: readonly DeviceInterface[],
): ConnectionForm {
  const next = emptyConnectionForm()
  const deviceOf = (interfaceId: string) => interfaces.find((i) => i.id === interfaceId)?.physical_device_id ?? ''
  if (connection) {
    next.sourceDeviceId = deviceOf(connection.source_interface_id)
    next.source_interface_id = connection.source_interface_id
    next.destinationDeviceId = deviceOf(connection.destination_interface_id)
    next.destination_interface_id = connection.destination_interface_id
    next.connection_type_id = connection.connection_type_id
    next.is_active = connection.is_active
    next.description = connection.description ?? ''
  } else if (prefill) {
    next.sourceDeviceId = deviceOf(prefill.sourceInterfaceId)
    next.source_interface_id = prefill.sourceInterfaceId
    next.destinationDeviceId = deviceOf(prefill.destinationInterfaceId)
    next.destination_interface_id = prefill.destinationInterfaceId
  }
  return next
}

/** Тело запроса создания/обновления подключения (пустое описание уходит как null). */
export function connectionPayload(form: ConnectionForm) {
  return {
    source_interface_id: form.source_interface_id,
    destination_interface_id: form.destination_interface_id,
    connection_type_id: form.connection_type_id,
    is_active: form.is_active,
    description: form.description || null,
  }
}

/** Проверка перед отправкой: текст первой ошибки или null. */
export function validateConnectionForm(form: Pick<ConnectionForm, 'source_interface_id' | 'destination_interface_id' | 'connection_type_id'>): string | null {
  if (!form.source_interface_id) return 'Выберите исходное устройство и его порт.'
  if (!form.destination_interface_id) return 'Выберите конечное устройство и его порт.'
  if (form.source_interface_id === form.destination_interface_id) return 'Исходный и конечный порт не могут совпадать.'
  if (!form.connection_type_id) return 'Выберите тип физической линии связи.'
  return null
}

/** Подпись устройства во всём интерфейсе: системное имя, а без него серийный номер. */
export function connectionDeviceLabel(d: Pick<Device, 'system_name' | 'serial_number'>): string {
  return d.system_name || d.serial_number
}

/**
 * Порты устройства, из которых можно выбирать: исключены занятые активным подключением (сервер всё равно ответил бы 409). Порт,
 * выбранный сейчас (currentlySelectedId), остаётся — иначе при правке нельзя было бы поменять, например, тип линии, не трогая порты.
 */
export function freeInterfacesForDevice(
  all: readonly DeviceInterface[],
  occupied: ReadonlySet<string>,
  deviceId: string,
  currentlySelectedId: string,
): DeviceInterface[] {
  if (!deviceId) return []
  return all.filter((i) => i.physical_device_id === deviceId && (i.id === currentlySelectedId || !occupied.has(i.id)))
}

/** Сколько портов у устройства вообще (до фильтра по занятости): «нет портов» и «все заняты» — разные причины пустого списка. */
export function countDeviceInterfaces(all: readonly DeviceInterface[], deviceId: string): number {
  if (!deviceId) return 0
  return all.filter((i) => i.physical_device_id === deviceId).length
}
