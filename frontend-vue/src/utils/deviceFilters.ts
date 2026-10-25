import type { Device } from '../api/types'
import type { useCatalogsStore } from '../stores/catalogs'

/**
 * Устройства, которые можно использовать как хост ВМ или как физический источник ИС —
 * определяется по названию типа устройства (device-types), поскольку явного флага "это сервер"
 * на PhysicalDevice в модели нет. Используется в VMFormModal.vue (хост ВМ) и
 * ISSourcesListEditor.vue (физический источник ИС) — вынесено сюда, чтобы оба места не
 * разошлись в определении "что считается сервером/СХД" при будущих правках. Совпадает с
 * фильтром бэкенда (validate_vm_host в backend/app/services/validation.py) и с vanilla-версией
 * (openInformationSystemForm прежнего vanilla-фронтенда (до 2.60.0)) — фильтрация здесь не
 * замена серверной проверке, а просто не даёт пользователю выбрать заведомо неподходящее
 * устройство в выпадающем списке.
 */
const HOST_TYPE_KEYWORDS = ['сервер', 'система хранения', 'storage']

export function filterHostDevices(devices: Device[], catalogs: ReturnType<typeof useCatalogsStore>): Device[] {
  return devices.filter((d) => {
    const typeName = catalogs.label('device-types', d.device_type_id, '').toLowerCase()
    return HOST_TYPE_KEYWORDS.some((kw) => typeName.includes(kw))
  })
}
