// Проверка формы устройства перед сохранением (DeviceFormModal.vue): обязательные поля, порты, группы, подключения и блок
// «VLAN устройства». Чистая функция: возвращает первую найденную проблему, ничего не показывает и не раскрывает.
import { validateInterfaceDraftRows } from '../api/deviceInterfaces'
import type { DeviceVlanDraftRow, InterfaceDraftRow, InterfaceGroupDraft, ProtocolPortCatalogEntry, VLANDefinition } from '../api/types'
import type { DeviceForm } from './deviceForm'
import { duplicateVlansMessage } from './deviceVlans'
import { validateConnectionDrafts, type ConnectionBaseline } from './interfaceConnections'
import { validateInterfaceGroups } from './interfaceGroups'
import { isValidIPv4, isValidPrefixLength } from './ipValidation'

export interface DeviceDraftToValidate {
  form: Pick<DeviceForm, 'device_type_id' | 'serial_number'>
  interfaces: InterfaceDraftRow[]
  interfaceGroups: InterfaceGroupDraft[]
  deviceVlans: DeviceVlanDraftRow[]
  vlanDefinitions: readonly VLANDefinition[]
  protocolPortCatalog: readonly ProtocolPortCatalogEntry[]
  /** id VLAN, допустимых на портах устройства. */
  portVlanIds: ReadonlySet<string>
  initialConnections: ConnectionBaseline
}

export interface DeviceDraftIssue {
  message: string
  /** Проблема в строке блока «VLAN устройства»: форма раскрывает блок, чтобы подсвеченные строки были видны даже при сворачивании по порогу. */
  expandVlanEditor?: boolean
}

export function validateDeviceDraft(draft: DeviceDraftToValidate): DeviceDraftIssue | null {
  if (!draft.form.device_type_id) return { message: 'Укажите тип устройства.' }
  if (!draft.form.serial_number.trim()) return { message: 'Укажите серийный номер.' }
  const interfaceError =
    validateInterfaceDraftRows(draft.interfaces, draft.protocolPortCatalog, draft.portVlanIds) ??
    validateInterfaceGroups(draft.interfaceGroups, draft.protocolPortCatalog, draft.portVlanIds) ??
    validateConnectionDrafts(draft.interfaces, draft.initialConnections)
  if (interfaceError) return { message: interfaceError }
  // Фикс п.3 ("применить исправление [валидации IP] ко всем полям с ip"): "VLAN устройства"
  // (DeviceVlanListEditor.vue) — свой собственный IP/префикс на связи устройство-VLAN, отдельный
  // от IP на портах (interfaces.*.ips, уже проверены выше в validateInterfaceDraftRows).
  // Повторы VLAN — как повторы портов (бэкенд всё равно ответил бы 422): сообщаем сразу.
  const duplicateVlans = duplicateVlansMessage(draft.deviceVlans, draft.vlanDefinitions)
  if (duplicateVlans) return { message: duplicateVlans, expandVlanEditor: true }
  for (const row of draft.deviceVlans) {
    if (!isValidIPv4(row.ip_address)) return { message: `Некорректный IP-адрес «${row.ip_address}» в блоке "VLAN устройства".`, expandVlanEditor: true }
    if (!isValidPrefixLength(row.prefix_length))
      return { message: `Некорректный префикс «${row.prefix_length}» в блоке "VLAN устройства" — допустимо 0-32.`, expandVlanEditor: true }
  }
  return null
}
